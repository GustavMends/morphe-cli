import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_release
import publish_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.original)
        self.matrix = {"include": [{"name": "one"}, {"name": "two"}]}

    def result(self, name, filename=None, content=b"apk"):
        folder = self.root / "artifacts" / f"build-1-{name}"
        folder.mkdir(parents=True)
        filename = filename or f"{name}.apk"
        (folder / f"meta-{name}.json").write_text(json.dumps({"name": name, "asset_name": filename}))
        if content is not None:
            (folder / filename).write_bytes(content)

    def test_complete_matrix_is_collected(self):
        self.result("one")
        self.result("two")
        collect_release.collect(self.matrix)
        self.assertEqual({p.name for p in Path("release").iterdir()}, {"one.apk", "two.apk"})

    def test_incomplete_matrix_cannot_publish(self):
        self.result("one")
        with self.assertRaisesRegex(ValueError, "Missing results"):
            collect_release.collect(self.matrix)
        self.assertFalse(Path("release").exists())

    def test_missing_apk_is_rejected(self):
        self.result("one", content=None)
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            collect_release.collect(self.matrix)

    def test_empty_apk_is_rejected(self):
        self.result("one", content=b"")
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            collect_release.collect(self.matrix)

    def test_duplicate_asset_names_are_rejected(self):
        self.result("one", "same.apk")
        self.result("two", "same.apk")
        with self.assertRaisesRegex(ValueError, "duplicate asset"):
            collect_release.collect(self.matrix)

    def publish(self, releases=None, fail_upload=False, wrong_assets=False):
        Path("release").mkdir(exist_ok=True)
        Path("release/one.apk").write_bytes(b"apk")
        Path("release-title.txt").write_text("title")
        Path("release-body.md").write_text("notes")
        calls = []

        def fake_gh(*args):
            calls.append(args)
            if args[0] == "api":
                return json.dumps([releases or []])
            if args[:2] == ("release", "upload") and fail_upload:
                raise RuntimeError("upload failed")
            if args[:2] == ("release", "view"):
                return json.dumps({"assets": [] if wrong_assets else [{"name": "one.apk", "size": 3}]})
            return ""

        env = {"GITHUB_REPOSITORY": "owner/repo", "TAG": "build-1", "GITHUB_SHA": "abc"}
        with patch.dict(os.environ, env), patch.object(publish_release, "gh", side_effect=fake_gh):
            try:
                publish_release.publish()
            except (ValueError, RuntimeError) as error:
                return calls, error
        return calls, None

    def test_release_is_draft_until_verified_uploads(self):
        calls, error = self.publish()
        self.assertIsNone(error)
        self.assertIn("--draft", calls[1])
        self.assertIn("--target", calls[1])
        self.assertIn("--draft=false", calls[-1])
        self.assertEqual(calls[-2][:2], ("release", "view"))

    def test_upload_failure_leaves_draft(self):
        calls, error = self.publish(fail_upload=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertFalse(any("--draft=false" in call for call in calls))

    def test_asset_mismatch_leaves_draft(self):
        calls, error = self.publish(wrong_assets=True)
        self.assertIsInstance(error, ValueError)
        self.assertFalse(any("--draft=false" in call for call in calls))

    def test_published_release_cannot_be_overwritten(self):
        calls, error = self.publish([{"tag_name": "build-1", "draft": False}])
        self.assertIsInstance(error, ValueError)
        self.assertEqual(len(calls), 1)

    def test_failed_publication_can_resume_its_draft(self):
        calls, error = self.publish([{"tag_name": "build-1", "draft": True, "target_commitish": "abc"}])
        self.assertIsNone(error)
        self.assertNotIn(("release", "create"), [call[:2] for call in calls])
        self.assertIn("--draft=false", calls[-1])


if __name__ == "__main__":
    unittest.main()
