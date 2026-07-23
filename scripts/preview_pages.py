#!/usr/bin/env python3
"""Build realistic mock Pages data and serve the live site locally."""

from __future__ import annotations

import argparse
import html
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

try:
    from scripts.build_pages import build_pages
except ModuleNotFoundError:
    from build_pages import build_pages


SOURCES = [
    {
        "id": "1000000000000001",
        "title": "Open Systems Journal",
        "count": 34,
        "tone": "protocol design, distributed systems, and careful engineering trade-offs",
    },
    {
        "id": "1000000000000002",
        "title": "AI Research Dispatch",
        "count": 28,
        "tone": "model behavior, evaluation methods, and applied machine intelligence",
    },
    {
        "id": "1000000000000003",
        "title": "Infrastructure Weekly with an Intentionally Long Source Name",
        "count": 22,
        "tone": "reliability, observability, databases, and production incidents",
    },
    {
        "id": "2000000000000001",
        "title": "Small Web Notes",
        "count": 18,
        "tone": "independent publishing, personal websites, and thoughtful software",
    },
    {
        "id": "2000000000000002",
        "title": "Field Notes from a Quiet Studio",
        "count": 16,
        "tone": "design practice, creative tools, and the texture of everyday work",
    },
    {
        "id": "2000000000000003",
        "title": "Reading Machines",
        "count": 12,
        "tone": "digital reading, archives, annotation, and knowledge systems",
    },
    {
        "id": "3000000000000001",
        "title": "Release Radar",
        "count": 12,
        "tone": "product releases, changelogs, and developer platform updates",
    },
]

TITLE_PATTERNS = [
    "A practical field guide to {topic}",
    "What changed when we rebuilt {topic} from first principles",
    "Notes on {topic}, maintenance, and the cost of small decisions",
    "The quiet architecture behind {topic}",
    "Seven observations after a year of working with {topic}",
    "A deliberately long headline about {topic} that exercises truncation in narrow reading columns",
]

TOPICS = [
    "durable event streams",
    "small language models",
    "local-first interfaces",
    "operational simplicity",
    "distributed tracing",
    "personal archives",
    "reader-focused typography",
    "incremental delivery",
    "open protocols",
    "calm software",
]


def source_node(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "rss",
        "title": source["title"],
        "feedPath": f"rss/{source['id']}.xml",
        "originalUrl": f"https://feeds.example.test/{source['id']}.xml",
        "lastSuccessfulFetchAt": "2026-07-23T12:01:00Z",
        "lastContentChangedAt": "2026-07-23T12:00:20Z",
    }


def mock_catalog() -> dict[str, Any]:
    by_id = {source["id"]: source for source in SOURCES}
    return {
        "children": [
            {
                "type": "category",
                "title": "Engineering Systems",
                "children": [
                    source_node(by_id["1000000000000001"]),
                    {
                        "type": "category",
                        "title": "Applied Research",
                        "children": [
                            source_node(by_id["1000000000000002"]),
                            source_node(by_id["1000000000000003"]),
                        ],
                    },
                ],
            },
            {
                "type": "category",
                "title": "Independent Notes",
                "children": [
                    source_node(by_id["2000000000000001"]),
                    source_node(by_id["2000000000000002"]),
                    source_node(by_id["2000000000000003"]),
                ],
            },
            source_node(by_id["3000000000000001"]),
        ]
    }


def mock_source_state() -> list[dict[str, Any]]:
    failures = [
        [],
        ["1000000000000002"],
        ["1000000000000002", "2000000000000001"],
        ["1000000000000003"],
        ["1000000000000002", "2000000000000001"],
        ["1000000000000003"],
        ["1000000000000002"],
        ["1000000000000002", "1000000000000003", "3000000000000001"],
    ]
    records: list[dict[str, Any]] = []
    started = datetime(2026, 7, 21, 2, tzinfo=timezone.utc)
    for index, failed in enumerate(failures):
        run_started = started + timedelta(hours=index * 6)
        run_finished = run_started + timedelta(seconds=48 + index * 3)
        records.append({
            "startedAt": run_started.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "finishedAt": run_finished.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "durationSeconds": int((run_finished - run_started).total_seconds()),
            "failed": failed,
        })
    return records


def article_body(source: dict[str, Any], topic: str, index: int) -> str:
    return f"""
      <p>This mock article explores {html.escape(source['tone'])}. It is intentionally detailed enough
      to exercise the reading column, paragraph rhythm, links, and inline <strong>emphasis</strong>.</p>
      <h2>Working notes</h2>
      <p>The useful question is not whether {html.escape(topic)} is fashionable, but whether the system
      remains understandable after the novelty has worn off. The examples here are synthetic and safe
      to edit while tuning the interface.</p>
      <blockquote>Good archives preserve context without making the reader carry the machinery.</blockquote>
      <ul>
        <li>Prefer legible defaults over hidden cleverness.</li>
        <li>Make failure visible without making it visually dominant.</li>
        <li>Keep the path back to the original source obvious.</li>
      </ul>
      <pre><code>entry = archive.fetch(source_id="{source['id']}", page={index // 10 + 1})</code></pre>
      <p>Use this body to tune headings, code blocks, lists, quotations, and long-form measure.</p>
    """.strip()


def mock_feed(source: dict[str, Any], source_index: int) -> str:
    items: list[str] = []
    base_date = datetime(2026, 7, 23, 12, tzinfo=timezone.utc) - timedelta(hours=source_index)
    for index in range(source["count"]):
        topic = TOPICS[(index + source_index * 2) % len(TOPICS)]
        title = TITLE_PATTERNS[index % len(TITLE_PATTERNS)].format(topic=topic)
        published = base_date - timedelta(hours=index * 5 + source_index)
        summary = (
            f"A concise mock summary about {topic}. It gives the list card enough copy to test "
            f"one, two, and three-line layouts while representing {source['tone']}."
        )
        image = ""
        if index % 4 != 0:
            image_url = f"https://picsum.photos/seed/signal-{source['id']}-{index}/640/360"
            image = f'<media:thumbnail url="{image_url}" />'
        items.append(f"""
          <item>
            <title>{html.escape(title)}</title>
            <link>https://articles.example.test/{source['id']}/{index + 1}</link>
            <guid>mock:{source['id']}:{index + 1}</guid>
            <pubDate>{format_datetime(published)}</pubDate>
            <description><![CDATA[<p>{summary}</p>]]></description>
            <content:encoded><![CDATA[{article_body(source, topic, index)}]]></content:encoded>
            {image}
          </item>
        """)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
      <rss version="2.0"
        xmlns:content="http://purl.org/rss/1.0/modules/content/"
        xmlns:media="http://search.yahoo.com/mrss/">
        <channel>
          <title>{html.escape(source['title'])}</title>
          <link>https://feeds.example.test/{source['id']}</link>
          <description>Signal Archive UI mock feed</description>
          {''.join(items)}
        </channel>
      </rss>
    """


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_mock_preview(site_root: Path, output: Path) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="signal-archive-mock-") as temporary_directory:
        archive_root = Path(temporary_directory)
        catalog_path = archive_root / "catalog.json"
        write_json(catalog_path, mock_catalog())
        write_json(archive_root / "source_state.json", mock_source_state())
        for source_index, source in enumerate(SOURCES):
            feed_path = archive_root / "rss" / f"{source['id']}.xml"
            feed_path.parent.mkdir(parents=True, exist_ok=True)
            feed_path.write_text(mock_feed(source, source_index), encoding="utf-8")
        return build_pages(catalog_path, archive_root, site_root, output)


class PreviewRequestHandler(SimpleHTTPRequestHandler):
    site_root: Path
    preview_data_root: Path

    def translate_path(self, request_path: str) -> str:
        decoded_path = unquote(urlsplit(request_path).path)
        if decoded_path == "/data" or decoded_path.startswith("/data/"):
            base = self.preview_data_root
            relative = decoded_path.removeprefix("/data").lstrip("/")
        else:
            base = self.site_root
            relative = decoded_path.lstrip("/")

        parts = [part for part in PurePosixPath(relative).parts if part not in {"", "/"}]
        if any(part in {".", ".."} for part in parts):
            return str(base / "__not_found__")
        return str(base.joinpath(*parts))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, default=Path("site"))
    parser.add_argument("--output", type=Path, default=Path("_mock_preview"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()

    site_root = args.site_root.resolve()
    output = args.output.resolve()
    summary = build_mock_preview(site_root, output)
    print(
        "Mock Pages build complete: "
        f"sources={summary['sources']} articles={summary['articles']} failures={summary['failures']}"
    )
    if args.build_only:
        return 0

    handler = type(
        "ConfiguredPreviewRequestHandler",
        (PreviewRequestHandler,),
        {
            "site_root": site_root,
            "preview_data_root": output / "data",
        },
    )
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as error:
        print(f"error: cannot start preview server: {error}", file=sys.stderr)
        return 1
    print(f"Signal Archive preview: http://{args.host}:{args.port}/")
    print("Edit files in site/ and refresh the page to see UI changes.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
