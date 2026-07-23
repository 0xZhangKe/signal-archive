import json
import tempfile
import unittest
from pathlib import Path

from scripts.preview_pages import build_mock_preview


class PreviewPagesTest(unittest.TestCase):
    def test_builds_mock_preview_with_ui_states_and_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            site = root / "site"
            output = root / "preview"
            site.mkdir()
            (site / "index.html").write_text("preview", encoding="utf-8")

            summary = build_mock_preview(site, output)

            self.assertEqual(7, summary["sources"])
            self.assertGreater(summary["articles"], 100)
            rendered = json.loads((output / "data/rendered.json").read_text())
            self.assertEqual("2026-07-22T20:00:00Z", rendered["startedAt"])
            self.assertEqual("2026-07-22T20:01:09Z", rendered["finishedAt"])
            self.assertEqual(69, rendered["durationSeconds"])
            engineering = rendered["children"][0]
            independent = rendered["children"][1]
            release_radar = rendered["children"][2]
            self.assertEqual(2, engineering["failed_count"])
            self.assertEqual(0, independent["failed_count"])
            self.assertEqual(2, len(engineering["pages"]))
            self.assertEqual(0.375, engineering["children"][1]["state"])
            self.assertEqual(0.875, release_radar["state"])
            self.assertTrue((output / "data/source_state.json").is_file())


if __name__ == "__main__":
    unittest.main()
