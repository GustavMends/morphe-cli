import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cleanup_releases


def release(number, **kwargs):
    return {"id": number, "tag_name": f"build-{number}", "draft": False, "prerelease": False,
            "published_at": f"2026-10-13T{number // 60:02}:{number % 60:02}:00Z", **kwargs}


class CleanupTests(unittest.TestCase):
    def test_keep_rejects_invalid_and_destructive_inputs(self):
        for value in ("", "0", "-1", "1.5", "1e2", "3:] | .[]", "three", " 3 "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cleanup_releases.positive_keep(value)
        self.assertEqual(cleanup_releases.positive_keep("3"), 3)

    def test_full_history_is_considered(self):
        pages = [[release(i) for i in range(100)], [release(i) for i in range(100, 150)]]
        selected = cleanup_releases.select_old_releases(pages, 3)
        self.assertEqual(len(selected), 147)
        self.assertEqual(selected[0]["tag_name"], "build-146")
        self.assertEqual(selected[-1]["tag_name"], "build-0")

    def test_other_series_and_unpublished_builds_are_preserved(self):
        releases = [release(1), release(2), release(3, draft=True), release(4, prerelease=True),
                    release(5, published_at=None), release(6, tag_name="v1.0"), release(7, tag_name="7")]
        self.assertEqual([r["tag_name"] for r in cleanup_releases.select_old_releases([releases], 1)], ["build-1"])

    def test_api_failure_cannot_be_mistaken_for_nothing_to_delete(self):
        with patch.dict(os.environ, KEEP="3", GITHUB_REPOSITORY="owner/repo"):
            with patch.object(cleanup_releases, "gh", side_effect=subprocess.CalledProcessError(1, "gh")) as gh:
                with self.assertRaises(subprocess.CalledProcessError):
                    cleanup_releases.cleanup()
        self.assertEqual(gh.call_count, 1)

    def test_invalid_keep_fails_before_any_api_request(self):
        with patch.dict(os.environ, KEEP="0", GITHUB_REPOSITORY="owner/repo"):
            with patch.object(cleanup_releases, "gh") as gh, self.assertRaises(ValueError):
                cleanup_releases.cleanup()
            gh.assert_not_called()

    def test_only_selected_builds_have_their_tags_deleted(self):
        with patch.dict(os.environ, KEEP="1", GITHUB_REPOSITORY="owner/repo"):
            with patch.object(cleanup_releases, "gh", side_effect=[json.dumps([[release(1), release(2)]]), ""]) as gh:
                cleanup_releases.cleanup()
        self.assertEqual(gh.call_args_list[-1].args,
                         ("release", "delete", "build-1", "--repo", "owner/repo", "--cleanup-tag", "--yes"))


if __name__ == "__main__":
    unittest.main()
