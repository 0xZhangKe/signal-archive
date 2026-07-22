import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_catalog import feed_path, generate_catalog, normalize_feed_url


class GenerateCatalogTest(unittest.TestCase):
    def write(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_generates_nested_catalog_and_fallback_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            opml = self.write(
                directory,
                "feeds.opml",
                """<?xml version="1.0"?>
                <opml version="2.0"><body>
                  <outline text="Technology">
                    <outline title="Example" type="rss"
                      xmlUrl="HTTPS://Example.COM:443/feed.xml#fragment" />
                    <outline type="rss" xmlUrl="https://untitled.example/feed" />
                  </outline>
                </body></opml>""",
            )

            catalog = generate_catalog(opml)

            category = catalog["children"][0]
            self.assertEqual("category", category["type"])
            self.assertEqual("Technology", category["title"])
            source = category["children"][0]
            self.assertEqual("rss", source["type"])
            self.assertEqual("Example", source["title"])
            self.assertEqual(feed_path("https://example.com/feed.xml"), source["feedPath"])
            self.assertIsNone(source["lastSuccessfulFetchAt"])
            self.assertEqual("untitled.example", category["children"][1]["title"])

    def test_preserves_timestamps_by_feed_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            url = "https://example.com/feed.xml"
            path = feed_path(url)
            existing = self.write(
                directory,
                "catalog.json",
                json.dumps(
                    {
                        "children": [
                            {
                                "type": "rss",
                                "title": "Old title",
                                "feedPath": path,
                                "originalUrl": url,
                                "lastSuccessfulFetchAt": "2026-07-22T08:00:00Z",
                                "lastContentChangedAt": "2026-07-21T08:00:00Z",
                            }
                        ]
                    }
                ),
            )
            opml = self.write(
                directory,
                "feeds.opml",
                f'<opml><body><outline text="New title" xmlUrl="{url}" /></body></opml>',
            )

            source = generate_catalog(opml, existing)["children"][0]

            self.assertEqual("New title", source["title"])
            self.assertEqual("2026-07-22T08:00:00Z", source["lastSuccessfulFetchAt"])
            self.assertEqual("2026-07-21T08:00:00Z", source["lastContentChangedAt"])

    def test_url_normalization_keeps_meaningful_parts(self) -> None:
        self.assertEqual(
            "https://example.com:8443/path/?b=2&a=1",
            normalize_feed_url("HTTPS://EXAMPLE.COM:8443/path/?b=2&a=1#section"),
        )

    def test_rejects_non_http_feed_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid HTTP"):
            normalize_feed_url("file:///tmp/feed.xml")


if __name__ == "__main__":
    unittest.main()
