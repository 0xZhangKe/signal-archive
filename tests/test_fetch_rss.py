import tempfile
import unittest
from pathlib import Path

from scripts.fetch_rss import collect_sources, fetch_catalog, safe_feed_file, validate_feed


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


if __name__ == "__main__":
    unittest.main()
