import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_pages import build_pages, build_rendered, folder_id, sanitize_html


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


def rss_with_items(count: int) -> str:
    items = "".join(
        f"""
        <item>
          <title>Article {index:03d}</title>
          <link>https://example.com/{index}</link>
          <guid>article-{index}</guid>
          <description>Summary {index}</description>
        </item>
        """
        for index in range(count)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


class BuildPagesTest(unittest.TestCase):
    def test_flattens_nested_categories_and_deduplicates_sources(self) -> None:
        first_path = "rss/1111111111111111.xml"
        second_path = "rss/2222222222222222.xml"
        first = rss_node("First", first_path)
        duplicate = rss_node("First duplicate", first_path)
        second = rss_node("Second", second_path)
        catalog = {"children": [{
            "type": "category",
            "title": "Technology",
            "children": [first, {
                "type": "category",
                "title": "Nested",
                "children": [duplicate, second],
            }],
        }]}

        rendered, sources, folders = build_rendered(catalog)

        category = rendered["children"][0]
        self.assertEqual("Technology", category["title"])
        self.assertEqual(["First", "Second"], [item["title"] for item in category["children"]])
        self.assertEqual(f"https://example.com/{first_path}", category["children"][0]["originalUrl"])
        self.assertEqual(
            [first_path, second_path],
            folders[folder_id("Technology")],
        )
        self.assertEqual(2, len(sources))

    def test_builds_rendered_pages_and_article_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "archive"
            site = root / "site"
            output = root / "output"
            (archive / "rss").mkdir(parents=True)
            site.mkdir()
            (site / "index.html").write_text("reader", encoding="utf-8")
            first_path = "rss/1111111111111111.xml"
            second_path = "rss/2222222222222222.xml"
            (archive / first_path).write_text(RSS, encoding="utf-8")
            (archive / second_path).write_text(ATOM, encoding="utf-8")
            catalog = {"children": [{
                "type": "category",
                "title": "Technology",
                "children": [
                    rss_node("First", first_path),
                    {"type": "category", "title": "Nested", "children": [rss_node("Second", second_path)]},
                ],
            }]}
            catalog_path = archive / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            source_state = [
                {
                    "startedAt": "2026-07-22T02:00:00Z",
                    "finishedAt": "2026-07-22T02:01:00Z",
                    "durationSeconds": 60,
                    "failed": [],
                },
                {
                    "startedAt": "2026-07-22T08:00:00Z",
                    "finishedAt": "2026-07-22T08:01:00Z",
                    "durationSeconds": 60,
                    "failed": ["1111111111111111"],
                },
            ]
            (archive / "source_state.json").write_text(json.dumps(source_state), encoding="utf-8")

            summary = build_pages(catalog_path, archive, site, output)

            self.assertEqual({"sources": 2, "articles": 2, "failures": 0}, summary)
            rendered = json.loads((output / "data/rendered.json").read_text())
            self.assertEqual("2026-07-22T08:00:00Z", rendered["startedAt"])
            self.assertEqual("2026-07-22T08:01:00Z", rendered["finishedAt"])
            self.assertEqual(60, rendered["durationSeconds"])
            category = rendered["children"][0]
            self.assertEqual(2, len(category["children"]))
            self.assertEqual(2, category["articleCount"])
            self.assertEqual(1, category["failed_count"])
            self.assertEqual(1, category["children"][0]["articleCount"])
            self.assertEqual(1, category["children"][1]["articleCount"])
            self.assertEqual(0.5, category["children"][0]["state"])
            self.assertEqual(1.0, category["children"][1]["state"])
            self.assertEqual(
                [f"categories/{folder_id('Technology')}/page-001.json"],
                category["pages"],
            )
            category_page = output / "data" / category["pages"][0]
            items = json.loads(category_page.read_text())["items"]
            self.assertEqual(["Atom article", "First article"], [item["title"] for item in items])
            detail = json.loads((output / "data" / items[1]["detailPath"]).read_text())
            self.assertIn("Full article", detail["content"])
            self.assertNotIn("script", detail["content"])
            self.assertEqual("https://example.com/a.jpg", detail["image"])
            self.assertEqual("1111111111111111", detail["sourceId"])
            self.assertNotIn("detailPath", detail)
            self.assertNotIn("feedPath", detail)
            self.assertEqual(
                ["categories/1111111111111111/page-001.json"],
                category["children"][0]["pages"],
            )
            self.assertEqual(
                source_state,
                json.loads((output / "data/source_state.json").read_text()),
            )
            self.assertFalse((output / "data/catalog.json").exists())
            self.assertFalse((output / "data/navigation.json").exists())
            self.assertFalse((output / "data/lists").exists())
            self.assertFalse((output / "data/build.json").exists())

    def test_paginates_source_and_folder_articles_by_sixty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "archive"
            site = root / "site"
            output = root / "output"
            (archive / "rss").mkdir(parents=True)
            site.mkdir()
            (site / "index.html").write_text("reader", encoding="utf-8")
            feed_path = "rss/3333333333333333.xml"
            (archive / feed_path).write_text(rss_with_items(61), encoding="utf-8")
            catalog = {"children": [{
                "type": "category",
                "title": "Many",
                "children": [rss_node("Many source", feed_path)],
            }]}
            catalog_path = archive / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

            build_pages(catalog_path, archive, site, output)

            rendered = json.loads((output / "data/rendered.json").read_text())
            folder = rendered["children"][0]
            source = folder["children"][0]
            self.assertEqual(61, folder["articleCount"])
            self.assertEqual(61, source["articleCount"])
            self.assertEqual(0, folder["failed_count"])
            self.assertEqual(1.0, source["state"])
            self.assertEqual(2, len(folder["pages"]))
            self.assertEqual(2, len(source["pages"]))
            self.assertEqual(
                60,
                len(json.loads((output / "data" / source["pages"][0]).read_text())["items"]),
            )
            self.assertEqual(
                1,
                len(json.loads((output / "data" / source["pages"][1]).read_text())["items"]),
            )

    def test_rejects_duplicate_folder_titles(self) -> None:
        catalog = {"children": [
            {"type": "category", "title": "Same", "children": []},
            {"type": "category", "title": "Same", "children": []},
        ]}
        with self.assertRaisesRegex(ValueError, "globally unique"):
            build_rendered(catalog)

    def test_deduplicates_repeated_article_ids_within_a_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "archive"
            site = root / "site"
            output = root / "output"
            (archive / "rss").mkdir(parents=True)
            site.mkdir()
            (site / "index.html").write_text("reader", encoding="utf-8")
            feed_path = "rss/4444444444444444.xml"
            item_fragment = RSS[RSS.index("<item>"):RSS.index("</channel>")]
            duplicate_rss = RSS.replace("</channel>", item_fragment + "</channel>")
            (archive / feed_path).write_text(duplicate_rss, encoding="utf-8")
            catalog = {"children": [rss_node("Repeated", feed_path)]}
            catalog_path = archive / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

            build_pages(catalog_path, archive, site, output)

            rendered = json.loads((output / "data/rendered.json").read_text())
            source = rendered["children"][0]
            items = json.loads((output / "data" / source["pages"][0]).read_text())["items"]
            self.assertEqual(1, source["articleCount"])
            self.assertEqual(1, len(items))

    def test_sanitizes_dangerous_html(self) -> None:
        rendered = sanitize_html('<p onclick="bad()">Safe</p><script>bad()</script><iframe/><a href="javascript:bad()">link</a>')
        self.assertEqual('<p>Safe</p><a target="_blank" rel="noopener noreferrer">link</a>', rendered)


if __name__ == "__main__":
    unittest.main()
