#!/usr/bin/env python3
"""Generate catalog.json from OPML and AI subscription configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

if __package__:
    from .ai_sources import load_ai_sources
else:
    from ai_sources import load_ai_sources


TIMESTAMP_FIELDS = ("lastSuccessfulFetchAt", "lastContentChangedAt")


def normalize_feed_url(value: str) -> str:
    """Return a stable representation without changing URL semantics."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"invalid HTTP(S) feed URL: {value!r}")

    scheme = parts.scheme.lower()
    hostname = parts.hostname.lower()
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError(f"invalid feed URL port: {value!r}") from error

    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    if parts.username is not None or parts.password is not None:
        raise ValueError(f"feed URL must not contain credentials: {value!r}")

    return urlunsplit((scheme, host, parts.path or "/", parts.query, ""))


def feed_path(xml_url: str) -> str:
    digest = hashlib.sha256(normalize_feed_url(xml_url).encode("utf-8")).hexdigest()
    return f"rss/{digest[:16]}.xml"


def node_title(element: ET.Element, *, fallback: str | None = None) -> str:
    title = (element.get("title") or element.get("text") or "").strip()
    if title:
        return title
    if fallback:
        return fallback
    raise ValueError("an OPML category is missing both title and text")


def collect_timestamps(catalog: Any) -> dict[str, dict[str, str | None]]:
    timestamps: dict[str, dict[str, str | None]] = {}

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        path = node.get("feedPath")
        if isinstance(path, str):
            timestamps[path] = {field: node.get(field) for field in TIMESTAMP_FIELDS}
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                visit(child)

    if isinstance(catalog, dict):
        for child in catalog.get("children", []):
            visit(child)
    return timestamps


def parse_outline(
    element: ET.Element,
    old_timestamps: dict[str, dict[str, str | None]],
) -> dict[str, Any]:
    xml_url = (element.get("xmlUrl") or "").strip()
    child_outlines = element.findall("outline")

    if xml_url:
        if child_outlines:
            raise ValueError("an OPML feed outline cannot also contain child outlines")
        normalized_url = normalize_feed_url(xml_url)
        path = feed_path(normalized_url)
        hostname = urlsplit(normalized_url).hostname
        node: dict[str, Any] = {
            "type": "rss",
            "title": node_title(element, fallback=hostname),
            "feedPath": path,
            "originalUrl": xml_url,
        }
        previous = old_timestamps.get(path, {})
        for field in TIMESTAMP_FIELDS:
            value = previous.get(field)
            node[field] = value if isinstance(value, str) else None
        return node

    if not child_outlines:
        raise ValueError(
            f"OPML outline {node_title(element)!r} has neither xmlUrl nor children"
        )

    return {
        "type": "category",
        "title": node_title(element),
        "children": [parse_outline(child, old_timestamps) for child in child_outlines],
    }


def load_existing_catalog(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read existing catalog {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"existing catalog {path} must contain a JSON object")
    return value


def generate_catalog(
    opml_path: Path,
    existing_path: Path | None = None,
    ai_sources_path: Path | None = None,
) -> dict[str, Any]:
    try:
        root = ET.parse(opml_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"cannot parse OPML {opml_path}: {error}") from error

    if root.tag.lower() != "opml":
        raise ValueError(f"expected an OPML document, got <{root.tag}>")
    body = root.find("body")
    if body is None:
        raise ValueError("OPML document is missing <body>")

    outlines = body.findall("outline")
    if not outlines:
        raise ValueError("OPML body does not contain any outlines")

    old_timestamps = collect_timestamps(load_existing_catalog(existing_path))
    rss_nodes = [parse_outline(outline, old_timestamps) for outline in outlines]
    ai_nodes = []
    ai_sources = load_ai_sources(ai_sources_path) if ai_sources_path is not None else []
    for source in ai_sources:
        previous = old_timestamps.get(source.feed_path, {})
        ai_nodes.append({
            "type": "ai",
            "title": source.title,
            "feedPath": source.feed_path,
            **{field: previous.get(field) if isinstance(previous.get(field), str) else None
               for field in TIMESTAMP_FIELDS},
        })
    identifiers: dict[str, str] = {}

    def check_ids(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if node["type"] == "category":
                check_ids(node["children"])
                continue
            path = node["feedPath"]
            identifier = Path(path).stem
            if identifier in identifiers and identifiers[identifier] != path:
                raise ValueError(f"source ID collision: {identifier}")
            identifiers[identifier] = path

    children = ai_nodes + rss_nodes
    check_ids(children)
    return {"children": children}


def write_catalog(catalog: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="source OPML file")
    parser.add_argument("--output", type=Path, required=True, help="catalog JSON file")
    parser.add_argument("--ai-sources", type=Path, default=Path("ai_sources.json"))
    parser.add_argument(
        "--existing",
        type=Path,
        help="existing catalog used to preserve fetch timestamps",
    )
    args = parser.parse_args()

    try:
        catalog = generate_catalog(args.input, args.existing, args.ai_sources)
        write_catalog(catalog, args.output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
