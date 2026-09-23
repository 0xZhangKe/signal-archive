import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

from scripts.ai_sources import AiSource
from scripts.build_pages import build_pages, parse_feed, source_state_metrics
from scripts.fetch_ai import article_guid, fetch_ai_catalog, merge_feed
from scripts.fetch_sources import fetch_all


NOW = "2026-09-23T10:00:00Z"
LATER = "2026-09-23T16:00:00Z"
URL = "https://example.com/release"
ITEM = {"title": "新版本", "url": URL, "publishedAt": None, "summary": "摘要",
        "keyPoints": ["要点"], "references": [{"title": "原文", "url": URL}]}
RSS = b'<rss version="2.0"><channel><title>RSS</title><item><title>RSS item</title><link>https://example.com/rss-post</link></item></channel></rss>'


def ai_node(source):
    return {"type": "ai", "title": source.title, "feedPath": source.feed_path,
            "lastSuccessfulFetchAt": None, "lastContentChangedAt": None}


class FetchAiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        prompt = self.root / "prompt.md"
        prompt.write_text("Recent releases")
        self.source = AiSource("releases", "Releases", prompt)
        self.node = ai_node(self.source)
        self.catalog = {"children": [self.node]}

    def agent(self, items=None, failure=None):
        return Mock(run=Mock(return_value=[copy.deepcopy(ITEM)] if items is None else items,
                             side_effect=failure), usage={})

    def test_duplicate_url_and_paraphrase_do_not_change_feed_or_article_id(self):
        old = merge_feed(self.source, None, [ITEM], NOW)
        changed = {**ITEM, "title": "Different wording", "url": URL + "?utm_source=news#section"}
        self.assertEqual(old, merge_feed(self.source, old, [changed], LATER))
        self.assertEqual(article_guid(self.source.id, URL), article_guid(self.source.id, changed["url"]))
        path = self.root / "feed.xml"
        path.write_bytes(old)
        article = parse_feed(path, self.node)[0]
        self.assertIsNone(article["publishedAt"])
        self.assertGreater(article["sortTime"], 0)
        self.assertIn("原文", article["content"])
        self.assertIn(URL, article["content"])

    def test_html_in_model_text_is_escaped_in_article_body(self):
        path = self.root / "feed.xml"
        path.write_bytes(merge_feed(self.source, None, [{**ITEM, "summary": '<script>alert(1)</script>'}], NOW))
        body = parse_feed(path, self.node)[0]["content"]
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertEqual('<script>alert(1)</script>', parse_feed(path, self.node)[0]["summary"])

    def test_empty_success_preserves_feed_but_updates_fetch_time(self):
        destination = self.root / self.source.feed_path
        destination.parent.mkdir()
        content = merge_feed(self.source, None, [ITEM], NOW)
        destination.write_bytes(content)
        self.node["lastContentChangedAt"] = NOW
        result = fetch_ai_catalog(self.catalog, self.root, [self.source], lambda: self.agent([]), now=lambda: LATER)
        self.assertEqual((1, 1, 0, []), result)
        self.assertEqual(content, destination.read_bytes())
        self.assertEqual(LATER, self.node["lastSuccessfulFetchAt"])
        self.assertEqual(NOW, self.node["lastContentChangedAt"])

    def test_failure_preserves_previous_feed_and_timestamps(self):
        destination = self.root / self.source.feed_path
        destination.parent.mkdir()
        content = merge_feed(self.source, None, [ITEM], NOW)
        destination.write_bytes(content)
        self.node["lastSuccessfulFetchAt"] = NOW
        result = fetch_ai_catalog(self.catalog, self.root, [self.source],
                                  lambda: self.agent(failure=ValueError("invalid AI output")), now=lambda: LATER)
        self.assertEqual((1, 0, 0), result[:3])
        self.assertEqual(1, len(result[3]))
        self.assertEqual(content, destination.read_bytes())
        self.assertEqual(NOW, self.node["lastSuccessfulFetchAt"])

    def test_malformed_existing_feed_is_not_overwritten(self):
        destination = self.root / self.source.feed_path
        destination.parent.mkdir()
        destination.write_bytes(b"corrupt archive")
        agent = self.agent()
        result = fetch_ai_catalog(self.catalog, self.root, [self.source], lambda: agent)
        self.assertEqual(1, len(result[3]))
        self.assertEqual(b"corrupt archive", destination.read_bytes())
        agent.run.assert_not_called()

    def test_retention_keeps_newest_items(self):
        items = [{**ITEM, "url": f"https://example.com/{i}",
                  "publishedAt": f"2026-09-{1 + i % 20:02d}T00:00:00Z"} for i in range(201)]
        feed = ET.fromstring(merge_feed(self.source, None, items, NOW))
        entries = feed.findall("channel/item")
        self.assertEqual(200, len(entries))
        self.assertIn("20 Sep", entries[0].findtext("pubDate"))

    def test_unified_round_writes_one_state_record_and_builds_pages(self):
        self.catalog["children"].append({"type": "rss", "title": "RSS", "feedPath": "rss/abcdef.xml",
            "originalUrl": "https://example.com/rss", "lastSuccessfulFetchAt": None, "lastContentChangedAt": None})
        result = fetch_all(self.catalog, self.root, [self.source], lambda _: RSS, lambda: self.agent(), now=lambda: NOW)
        self.assertEqual((2, 2, 2), (result["total"], result["successful"], result["changed"]))
        records = json.loads((self.root / "source_state.json").read_text())
        self.assertEqual(1, len(records))
        self.assertEqual(["ai", "rss"], records[0]["sourceTypes"])
        self.assertEqual([], records[0]["failed"])
        site = self.root / "site"
        site.mkdir()
        (site / "index.html").write_text("reader")
        build_pages(self.root / "catalog.json", self.root, site, self.root / "output")
        rendered = json.loads((self.root / "output/data/rendered.json").read_text())
        self.assertEqual(["ai", "rss"], [n["type"] for n in rendered["children"]])
        self.assertEqual(1, rendered["children"][0]["articleCount"])
        self.assertEqual(1, rendered["children"][0]["state"])
        self.assertEqual(2, len(list((self.root / "output/data/articles").glob("*.json"))))

    def test_failed_ai_does_not_discard_successful_rss_or_other_ai(self):
        second = AiSource("other", "Other", self.source.prompt_file)
        self.catalog["children"].extend([ai_node(second), {"type": "rss", "title": "RSS",
            "feedPath": "rss/abcdef.xml", "originalUrl": "https://example.com/rss"}])
        agents = iter([self.agent(failure=RuntimeError("offline")), self.agent()])
        result = fetch_all(self.catalog, self.root, [self.source, second], lambda _: RSS, lambda: next(agents), now=lambda: NOW)
        self.assertEqual(2, result["successful"])
        self.assertEqual(1, len(result["errors"]))
        self.assertEqual(RSS, (self.root / "rss/abcdef.xml").read_bytes())
        self.assertTrue((self.root / second.feed_path).exists())
        records = json.loads((self.root / "source_state.json").read_text())
        self.assertEqual([self.source.id], records[0]["failed"])

    def test_legacy_rss_rounds_do_not_inflate_ai_success_rate(self):
        def record(date, failed, **extra):
            return {"startedAt": date, "finishedAt": date, "durationSeconds": 0, "failed": failed, **extra}
        records = [record(NOW, []), record(LATER, ["releases"], sourceTypes=["rss", "ai"])]
        rates, failed, _ = source_state_metrics(records, ["releases", "rss-source"],
            {"folder": ["ai/releases.xml", "rss/rss-source.xml"]}, {"releases": "ai", "rss-source": "rss"})
        self.assertEqual({"releases": 0, "rss-source": 1}, rates)
        self.assertEqual(1, failed["folder"])


if __name__ == "__main__":
    unittest.main()
