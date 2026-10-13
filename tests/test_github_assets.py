import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import github_assets


class GitHubAssetTests(unittest.TestCase):
    def asset(self, data=b"asset"):
        return {"id": 1, "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "url": "https://api.github.com/repos/owner/repo/releases/assets/1"}

    def test_asset_selection_requires_exactly_one_match(self):
        for assets in ([], [{"name": "one.mpp"}, {"name": "two.mpp"}]):
            with self.subTest(assets=assets), self.assertRaisesRegex(ValueError, "exactly one"):
                github_assets.select_asset({"assets": assets}, "owner/repo", lambda name: name.endswith(".mpp"))

    def test_asset_metadata_requires_positive_size_and_id(self):
        for values in ({"size": 0, "id": 1}, {"size": 1, "id": -1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                github_assets.select_asset({"assets": [{"name": "one.mpp", **values}]}, "owner/repo", lambda _: True)

    def test_latest_versions_are_resolved_once_per_repository(self):
        apps = [{"name": name, "output_name": name, "patches_repo": "owner/patches",
                 "mirror_repo": "owner/mirror", "mirror_tag": "v1", "mirror_asset": "input.apk"}
                for name in ("one", "two")]

        def fake_api(endpoint, token):
            if "morphe-desktop" in endpoint:
                name = "desktop-all.jar"
            elif "patches" in endpoint:
                name = "patches.mpp"
            else:
                name = "input.apk"
            return {"tag_name": "v1", "body": "notes", "assets": [{"name": name, "id": 1, "size": 5}]}

        with patch.object(github_assets, "api", side_effect=fake_api) as api:
            snapshot = github_assets.resolve(apps, "public-token", "mirror-token")
        self.assertEqual(api.call_count, 3)
        self.assertEqual(snapshot["apps"][0]["patches"], snapshot["apps"][1]["patches"])
        self.assertEqual(api.call_args_list[-1].args[1], "mirror-token")

    def test_valid_cache_skips_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "asset.jar"
            path.write_bytes(b"asset")
            with patch.object(github_assets, "curl") as curl:
                github_assets.fetch(self.asset(), path, "token")
                curl.assert_not_called()

    def test_corrupt_cache_is_replaced_only_by_verified_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "asset.jar"
            path.write_bytes(b"wrong")

            def download(url, token, *args, **kwargs):
                Path(args[1]).write_bytes(b"asset")

            with patch.object(github_assets, "curl", side_effect=download):
                github_assets.fetch(self.asset(), path, "token")
            self.assertEqual(path.read_bytes(), b"asset")
            self.assertFalse(path.with_name("asset.jar.part").exists())

    def test_bad_download_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "asset.jar"
            for data in (b"wrong", b"short file"):
                with self.subTest(data=data):
                    def download(url, token, *args, **kwargs):
                        Path(args[1]).write_bytes(data)
                    with patch.object(github_assets, "curl", side_effect=download), self.assertRaises(ValueError):
                        github_assets.fetch(self.asset(), path, "token")
                    self.assertFalse(path.exists())
                    self.assertFalse(path.with_name("asset.jar.part").exists())

    def test_transfer_failure_cleans_partial_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "asset.jar"
            def download(url, token, *args, **kwargs):
                Path(args[1]).write_bytes(b"partial")
                raise RuntimeError("HTTP error")
            with patch.object(github_assets, "curl", side_effect=download), self.assertRaises(RuntimeError):
                github_assets.fetch(self.asset(), path, "token")
            self.assertFalse(path.exists())
            self.assertFalse(path.with_name("asset.jar.part").exists())

    def test_curl_failure_does_not_disclose_authentication(self):
        result = subprocess.CompletedProcess([], 22, "")
        with patch.object(subprocess, "run", return_value=result) as run:
            with self.assertRaises(RuntimeError) as error:
                github_assets.curl("https://api.github.com/test", "secret-token")
        self.assertNotIn("secret-token", str(error.exception))
        command = run.call_args.args[0]
        self.assertIn("--fail", command)
        self.assertIn("--retry", command)
        self.assertIn("--max-time", command)
        self.assertIn("--proto-redir", command)

    def test_environment_file_rejects_line_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "env"
            with self.assertRaises(ValueError):
                github_assets.write_values(path, {"TAG": "v1\nGH_TOKEN=injected"})
            self.assertEqual(path.read_text(), "")


if __name__ == "__main__":
    unittest.main()
