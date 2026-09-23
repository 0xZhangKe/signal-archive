#!/usr/bin/env python3
"""Fetch RSS and AI sources as one archive transaction and one state record."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ai_agent import AgentSettings, DEFAULT_MODEL, ResearchAgent
from scripts.ai_sources import AiSource, load_ai_sources
from scripts.fetch_ai import collect_ai_nodes, fetch_ai_catalog
from scripts.fetch_rss import (DEFAULT_MAX_BYTES, collect_sources, download, fetch_catalog,
                               source_identifier, update_source_state, utc_now, write_catalog)


def fetch_all(catalog: dict, archive_root: Path, sources: list[AiSource],
              rss_fetcher: Callable, agent_factory: Callable, *, workers: int = 16,
              now: Callable[[], str] = utc_now) -> dict:
    # Validate before either collector starts mutating the archive.
    collect_sources(catalog)
    if set(collect_ai_nodes(catalog)) != {source.feed_path for source in sources}:
        raise ValueError("AI configuration and catalog differ; regenerate the catalog before fetching")
    started_at = now()
    started_monotonic = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        rss = executor.submit(fetch_catalog, catalog, archive_root, rss_fetcher, workers=workers, now=now)
        ai = executor.submit(fetch_ai_catalog, catalog, archive_root, sources, agent_factory, now=now)
        results = [rss.result(), ai.result()]
    errors = [failure for result in results for failure in result[3]]
    write_catalog(archive_root / "catalog.json", catalog)
    update_source_state(
        archive_root / "source_state.json", started_at=started_at, finished_at=now(),
        duration_seconds=round(time.monotonic() - started_monotonic),
        failed=[source_identifier(failure.source.feed_path) for failure in errors],
        source_types=["rss", "ai"],
    )
    return {"total": sum(result[0] for result in results),
            "successful": sum(result[1] for result in results),
            "changed": sum(result[2] for result in results), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--ai-sources", type=Path, default=Path("ai_sources.json"))
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout <= 0:
        parser.error("workers and timeout must be positive")
    try:
        sources = load_ai_sources(args.ai_sources)
        catalog = json.loads((args.archive_root / "catalog.json").read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            raise ValueError("catalog must contain a JSON object")
        result = fetch_all(
            catalog, args.archive_root, sources,
            lambda url: download(url, args.timeout, DEFAULT_MAX_BYTES),
            lambda: ResearchAgent(os.environ.get("OPENROUTER_API_KEY", ""), os.environ.get("TAVILY_API_KEY", ""),
                                  settings=AgentSettings(model=os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL)),
            workers=args.workers,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    summary = (f"Fetch complete: total={result['total']} successful={result['successful']} "
               f"changed={result['changed']} failed={len(result['errors'])}")
    print(summary)
    for failure in result["errors"]:
        message = f"{failure.source.feed_path}: {failure.error}"
        # Escape workflow command syntax in remote/model error strings.
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning::{message}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(summary + "\n")
            for failure in result["errors"]:
                output.write(f"\n- Failed: `{failure.source.feed_path}`\n")
    # Source failures are recorded, but must not prevent committing successful results.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
