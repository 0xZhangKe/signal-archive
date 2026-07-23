import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_pages import build_navigation, build_pages, sanitize_html


RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel><title>Example</title><item>
    <title>First article</title>
    <link>https://example.com/first</link>
    <guid>first</guid>
    <pubDate>Tue, 21 Jul 2026 08:00:00 +0000</pubDate>
    <description><![CDATA[<p>A useful summary with <b>detail</b>.</p>]]></description>
    <content:encoded><![CDATA[<p>Full article.</p><script>alert(1)</script><img src="https://example.com/a.jpg">]]></content:encoded>
  </item></channel>
</rss>"""


ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Example</title><entry>
    <title>Atom article</title><id>tag:example.com,2026:atom</id>
    <updated>2026-07-22T09:30:00Z</updated>
    <link href="https://example.com/atom" />
    <summary type="html">Atom summary</summary>
  </entry>
</feed>"""


def rss_node(title: str, path: str) -> dict:
    return {
        "type": "rss",
        "title": title,
        "feedPath": path,
        "originalUrl": f"https://example.com/{path}",
        "lastSuccessfulFetchAt": None,
        "lastContentChangedAt": None,
    }


class BuildPagesTest(unittest.TestCase):
    def test_flattens_nested_categories_and_deduplicates_sources(self) -> None:
        first = rss_node("First", "rss/first.xml")
        duplicate = rss_node("First duplicate", "rss/first.xml")
        second = rss_node("Second", "rss/second.xml")
        catalog = {"children": [{
            "type": "category",
            "title": "Technology",
            "children": [first, {
                "type": "category",
                "title": "Nested",
                "children": [duplicate, second],
            }],
        }]}

        navigation, sources = build_navigation(catalog)

        category = navigation["items"][0]
        self.assertEqual("Technology", category["title"])
        self.assertEqual(["First", "Second"], [item["title"] for item in category["sources"]])
        self.assertEqual("https://example.com/rss/first.xml", category["sources"][0]["originalUrl"])
        self.assertEqual(2, len(sources))

    def test_builds_navigation_lists_and_article_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "archive"
            site = root / "site"
            output = root / "output"
            (archive / "rss").mkdir(parents=True)
            site.mkdir()
            (site / "index.html").write_text("reader", encoding="utf-8")
            (archive / "rss/first.xml").write_text(RSS, encoding="utf-8")
            (archive / "rss/second.xml").write_text(ATOM, encoding="utf-8")
            catalog = {"children": [{
                "type": "category",
                "title": "Technology",
                "children": [
                    rss_node("First", "rss/first.xml"),
                    {"type": "category", "title": "Nested", "children": [rss_node("Second", "rss/second.xml")]},
                ],
            }]}
            catalog_path = archive / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            source_state = [{
                "startedAt": "2026-07-22T08:00:00Z",
                "finishedAt": "2026-07-22T08:01:00Z",
                "durationSeconds": 60,
                "failed": ["first"],
            }]
            (archive / "source_state.json").write_text(json.dumps(source_state), encoding="utf-8")

            summary = build_pages(catalog_path, archive, site, output)

            self.assertEqual({"sources": 2, "articles": 2, "failures": 0}, summary)
            navigation = json.loads((output / "data/navigation.json").read_text())
            category_list = output / navigation["items"][0]["listPath"]
            items = json.loads(category_list.read_text())["items"]
            self.assertEqual(["Atom article", "First article"], [item["title"] for item in items])
            detail = json.loads((output / items[1]["detailPath"]).read_text())
            self.assertIn("Full article", detail["content"])
            self.assertNotIn("script", detail["content"])
            self.assertEqual("https://example.com/a.jpg", detail["image"])
            self.assertEqual(
                source_state,
                json.loads((output / "data/source_state.json").read_text()),
            )

    def test_sanitizes_dangerous_html(self) -> None:
        rendered = sanitize_html('<p onclick="bad()">Safe</p><script>bad()</script><iframe/><a href="javascript:bad()">link</a>')
        self.assertEqual('<p>Safe</p><a target="_blank" rel="noopener noreferrer">link</a>', rendered)


if __name__ == "__main__":
    unittest.main()
