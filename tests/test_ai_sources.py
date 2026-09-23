import json
import tempfile
import unittest
from pathlib import Path

from scripts.ai_sources import load_ai_sources
from scripts.generate_catalog import feed_path, generate_catalog


class AiSourcesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "prompt.md").write_text("Collect recent official releases.")
        self.config = self.root / "ai_sources.json"
        self.item = {"id": "releases", "title": "Releases", "promptFile": "prompt.md"}
        self.opml = self.root / "opml.xml"
        self.opml.write_text('<opml><body><outline text="Blogs"><outline text="Blog" xmlUrl="https://example.com/rss" /></outline></body></opml>')

    def write(self, items):
        self.config.write_text(json.dumps({"sources": items}))

    def test_ai_sources_precede_opml_roots_and_preserve_timestamps(self):
        self.write([self.item, {**self.item, "id": "papers", "title": "Papers"}])
        existing = self.root / "catalog.json"
        existing.write_text(json.dumps({"children": [{"type": "ai", "title": "Old",
            "feedPath": "ai/releases.xml", "lastSuccessfulFetchAt": "2026-09-22T00:00:00Z"}]}))
        catalog = generate_catalog(self.opml, existing, self.config)
        self.assertEqual(["ai", "ai", "category"], [n["type"] for n in catalog["children"]])
        self.assertEqual(["Releases", "Papers", "Blogs"], [n["title"] for n in catalog["children"]])
        self.assertEqual("2026-09-22T00:00:00Z", catalog["children"][0]["lastSuccessfulFetchAt"])
        self.assertNotIn("promptFile", catalog["children"][0])

    def test_rejects_unsafe_ids_duplicate_ids_extra_fields_and_bad_prompts(self):
        invalid = [
            [{**self.item, "id": "../oops"}],
            [{**self.item, "id": "folder-reserved"}],
            [self.item, self.item],
            [{**self.item, "intervalHours": 24}],
            [{**self.item, "promptFile": "../prompt.md"}],
            [{**self.item, "promptFile": str(self.root / "prompt.md")}],
            [{**self.item, "promptFile": "missing.md"}],
        ]
        for items in invalid:
            with self.subTest(items=items):
                self.write(items)
                with self.assertRaises((ValueError, OSError)):
                    load_ai_sources(self.config)

    def test_symlink_cannot_escape_config_directory(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "prompt.md"
            outside.write_text("outside")
            (self.root / "escape.md").symlink_to(outside)
            self.write([{**self.item, "promptFile": "escape.md"}])
            with self.assertRaisesRegex(ValueError, "inside"):
                load_ai_sources(self.config)

    def test_empty_sources_keeps_rss_only_catalog(self):
        self.write([])
        self.assertEqual(["category"], [n["type"] for n in generate_catalog(self.opml, ai_sources_path=self.config)["children"]])

    def test_rejects_collision_with_rss_source_id(self):
        # Find a real RSS hash beginning with a letter, also a syntactically valid AI ID.
        for number in range(100):
            url = f"https://example.com/{number}"
            identifier = Path(feed_path(url)).stem
            if identifier[0].isalpha():
                break
        self.opml.write_text(f'<opml><body><outline text="RSS" xmlUrl="{url}" /></body></opml>')
        self.write([{**self.item, "id": identifier}])
        with self.assertRaisesRegex(ValueError, "collision"):
            generate_catalog(self.opml, ai_sources_path=self.config)


if __name__ == "__main__":
    unittest.main()
