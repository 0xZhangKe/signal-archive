import json
import tempfile
import unittest
from pathlib import Path

from scripts.fetch_rss import (
    collect_sources,
    fetch_catalog,
    safe_feed_file,
    source_identifier,
    update_source_state,
    validate_feed,
)


RSS_A = b'<?xml version="1.0"?><rss version="2.0"><channel><title>A</title></channel></rss>'
RSS_B = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>B</title></feed>'


def source(title: str, path: str, url: str) -> dict:
    return {
        "type": "rss",
        "title": title,
        "feedPath": path,
        "originalUrl": url,
        "lastSuccessfulFetchAt": None,
        "lastContentChangedAt": None,
    }


class FetchRssTest(unittest.TestCase):
    def test_fetches_unique_sources_and_updates_duplicate_nodes(self) -> None:
        first = source("A", "rss/a.xml", "https://example.com/a.xml")
        duplicate = source("A again", "rss/a.xml", "https://example.com/a.xml")
        second = source("B", "rss/b.xml", "https://example.com/b.xml")
        catalog = {
            "children": [
                first,
                {"type": "category", "title": "Other", "children": [duplicate, second]},
            ]
        }
        responses = {
            "https://example.com/a.xml": RSS_A,
            "https://example.com/b.xml": RSS_B,
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            total, successful, changed, errors = fetch_catalog(
                catalog,
                root,
                responses.__getitem__,
                workers=2,
                now=lambda: "2026-07-22T08:00:00Z",
            )

            self.assertEqual((2, 2, 2, []), (total, successful, changed, errors))
            self.assertEqual(RSS_A, (root / "rss/a.xml").read_bytes())
            self.assertEqual(RSS_B, (root / "rss/b.xml").read_bytes())
            self.assertEqual("2026-07-22T08:00:00Z", first["lastSuccessfulFetchAt"])
            self.assertEqual(first["lastSuccessfulFetchAt"], duplicate["lastSuccessfulFetchAt"])

    def test_unchanged_feed_only_updates_success_time(self) -> None:
        node = source("A", "rss/a.xml", "https://example.com/a.xml")
        node["lastContentChangedAt"] = "2026-07-20T08:00:00Z"
        catalog = {"children": [node]}

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "rss/a.xml"
            destination.parent.mkdir()
            destination.write_bytes(RSS_A)

            result = fetch_catalog(
                catalog,
                root,
                lambda _: RSS_A,
                workers=1,
                now=lambda: "2026-07-22T08:00:00Z",
            )

            self.assertEqual((1, 1, 0, []), result)
            self.assertEqual("2026-07-22T08:00:00Z", node["lastSuccessfulFetchAt"])
            self.assertEqual("2026-07-20T08:00:00Z", node["lastContentChangedAt"])

    def test_failed_source_does_not_update_timestamps(self) -> None:
        node = source("A", "rss/a.xml", "https://example.com/a.xml")
        catalog = {"children": [node]}

        with tempfile.TemporaryDirectory() as temporary_directory:
            result = fetch_catalog(
                catalog,
                Path(temporary_directory),
                lambda _: (_ for _ in ()).throw(OSError("offline")),
                workers=1,
            )

        self.assertEqual((1, 0, 0), result[:3])
        self.assertEqual(1, len(result[3]))
        self.assertIsNone(node["lastSuccessfulFetchAt"])

    def test_rejects_unsafe_feed_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe"):
            safe_feed_file(Path("archive"), "../main/opml.xml")

    def test_rejects_conflicting_duplicate_path(self) -> None:
        catalog = {
            "children": [
                source("A", "rss/a.xml", "https://example.com/a.xml"),
                source("B", "rss/a.xml", "https://example.com/b.xml"),
            ]
        }
        with self.assertRaisesRegex(ValueError, "multiple URLs"):
            collect_sources(catalog)

    def test_validates_feed_root(self) -> None:
        validate_feed(RSS_A, "https://example.com/rss")
        validate_feed(RSS_B, "https://example.com/atom")
        with self.assertRaisesRegex(ValueError, "not an RSS/Atom"):
            validate_feed(b"<html><body>Not a feed</body></html>", "https://example.com")

    def test_source_identifier_uses_feed_filename(self) -> None:
        self.assertEqual("05ada84875558017", source_identifier("rss/05ada84875558017.xml"))

    def test_source_state_keeps_only_the_latest_fifteen_days(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "source_state.json"
            path.write_text(json.dumps([
                {
                    "startedAt": "2026-07-07T00:00:00Z",
                    "finishedAt": "2026-07-07T00:01:00Z",
                    "durationSeconds": 60,
                    "failed": ["old"],
                },
                {
                    "startedAt": "2026-07-08T00:00:00Z",
                    "finishedAt": "2026-07-08T00:02:00Z",
                    "durationSeconds": 120,
                    "failed": [],
                },
            ]), encoding="utf-8")

            records = update_source_state(
                path,
                started_at="2026-07-23T00:00:00Z",
                finished_at="2026-07-23T00:01:30Z",
                duration_seconds=90,
                failed=["9a41b0d6fa07d21e", "05ada84875558017", "05ada84875558017"],
            )

            self.assertEqual(2, len(records))
            self.assertEqual("2026-07-08T00:02:00Z", records[0]["finishedAt"])
            self.assertEqual(90, records[1]["durationSeconds"])
            self.assertEqual(
                ["05ada84875558017", "9a41b0d6fa07d21e"],
                records[1]["failed"],
            )
            self.assertEqual(records, json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
