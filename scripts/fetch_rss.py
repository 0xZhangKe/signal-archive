#!/usr/bin/env python3
"""Fetch every RSS/Atom document referenced by an archive catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


DEFAULT_MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = "signal-archive/1.0 (+https://github.com/0xZhangKe/signal-archive)"


@dataclass(frozen=True)
class Source:
    feed_path: str
    original_url: str
    nodes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class FetchResult:
    source: Source
    content: bytes | None
    error: str | None = None


@dataclass(frozen=True)
class FetchFailure:
    source: Source
    error: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_feed_file(archive_root: Path, feed_path: str) -> Path:
    path = PurePosixPath(feed_path)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("rss",):
        raise ValueError(f"unsafe RSS feedPath: {feed_path!r}")
    if path.suffix.lower() not in {".xml", ".rss", ".atom"}:
        raise ValueError(f"RSS feedPath must point to an XML feed: {feed_path!r}")
    return archive_root.joinpath(*path.parts)


def collect_sources(catalog: dict[str, Any]) -> list[Source]:
    by_path: dict[str, dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            raise ValueError("catalog nodes must be JSON objects")
        node_type = node.get("type")
        if node_type == "category":
            children = node.get("children")
            if not isinstance(children, list):
                raise ValueError("catalog category children must be a JSON array")
            for child in children:
                visit(child)
            return
        if node_type != "rss":
            return

        feed_path = node.get("feedPath")
        original_url = node.get("originalUrl")
        if not isinstance(feed_path, str) or not feed_path:
            raise ValueError("RSS catalog node is missing feedPath")
        if not isinstance(original_url, str) or not original_url:
            raise ValueError(f"RSS catalog node {feed_path!r} is missing originalUrl")
        safe_feed_file(Path("."), feed_path)

        entry = by_path.setdefault(
            feed_path, {"original_url": original_url, "nodes": []}
        )
        if entry["original_url"] != original_url:
            raise ValueError(f"RSS feedPath {feed_path!r} maps to multiple URLs")
        entry["nodes"].append(node)

    children = catalog.get("children")
    if not isinstance(children, list):
        raise ValueError("catalog must contain a children array")
    for child in children:
        visit(child)

    return [
        Source(path, entry["original_url"], tuple(entry["nodes"]))
        for path, entry in by_path.items()
    ]


def validate_feed(content: bytes, url: str) -> None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(f"response from {url} is not valid XML: {error}") from error
    local_name = root.tag.rsplit("}", 1)[-1].lower()
    if local_name not in {"rss", "feed", "rdf"}:
        raise ValueError(f"response from {url} is not an RSS/Atom document (<{root.tag}>)")


def download(url: str, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"response from {url} exceeds {max_bytes} bytes")
    validate_feed(content, url)
    return content


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def fetch_one(
    source: Source,
    fetcher: Callable[[str], bytes],
) -> FetchResult:
    try:
        return FetchResult(source=source, content=fetcher(source.original_url))
    except Exception as error:  # A failed source must not discard other successful fetches.
        return FetchResult(source=source, content=None, error=str(error))


def fetch_catalog(
    catalog: dict[str, Any],
    archive_root: Path,
    fetcher: Callable[[str], bytes],
    *,
    workers: int,
    now: Callable[[], str] = utc_now,
) -> tuple[int, int, int, list[FetchFailure]]:
    sources = collect_sources(catalog)
    successful = changed = 0
    errors: list[FetchFailure] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, source, fetcher): source for source in sources}
        for future in as_completed(futures):
            result = future.result()
            source = result.source
            if result.error is not None or result.content is None:
                errors.append(FetchFailure(source, result.error or "empty response"))
                continue

            fetched_at = now()
            destination = safe_feed_file(archive_root, source.feed_path)
            old_content = destination.read_bytes() if destination.exists() else None
            content_changed = old_content != result.content
            if content_changed:
                atomic_write(destination, result.content)
                changed += 1

            for node in source.nodes:
                node["lastSuccessfulFetchAt"] = fetched_at
                if content_changed:
                    node["lastContentChangedAt"] = fetched_at
            successful += 1

    return len(sources), successful, changed, errors


def write_catalog(path: Path, catalog: dict[str, Any]) -> None:
    rendered = (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(path, rendered)


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid source state timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_identifier(feed_path: str) -> str:
    return PurePosixPath(feed_path).stem


def update_source_state(
    path: Path,
    *,
    started_at: str,
    finished_at: str,
    duration_seconds: int,
    failed: list[str],
    retention_days: int = 15,
) -> list[dict[str, Any]]:
    records: list[Any] = []
    if path.exists():
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"cannot parse source state {path}: {error}") from error
        if not isinstance(records, list):
            raise ValueError(f"source state {path} must contain a JSON array")

    cutoff = parse_timestamp(finished_at) - timedelta(days=retention_days)
    retained: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("finishedAt"), str):
            raise ValueError(f"source state {path} contains an invalid record")
        if parse_timestamp(record["finishedAt"]) >= cutoff:
            retained.append(record)

    retained.append({
        "startedAt": started_at,
        "finishedAt": finished_at,
        "durationSeconds": max(0, int(duration_seconds)),
        "failed": sorted(set(failed)),
    })
    rendered = (json.dumps(retained, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(path, rendered)
    return retained


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()

    if args.workers < 1 or args.timeout <= 0 or args.max_bytes < 1:
        parser.error("workers, timeout and max-bytes must be positive")

    started_at = utc_now()
    started_monotonic = time.monotonic()
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            raise ValueError("catalog must contain a JSON object")
        total, successful, changed, errors = fetch_catalog(
            catalog,
            args.archive_root,
            lambda url: download(url, args.timeout, args.max_bytes),
            workers=args.workers,
        )
        write_catalog(args.catalog, catalog)
        finished_at = utc_now()
        update_source_state(
            args.archive_root / "source_state.json",
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.monotonic() - started_monotonic),
            failed=[source_identifier(failure.source.feed_path) for failure in errors],
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"RSS fetch complete: total={total} successful={successful} changed={changed} failed={len(errors)}")
    for failure in errors:
        print(f"::warning::{failure.source.original_url}: {failure.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
