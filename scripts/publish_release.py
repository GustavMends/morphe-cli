#!/usr/bin/env python3
"""Upload to a draft and publish only after every asset has been uploaded."""
import json
import os
from pathlib import Path
import subprocess


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def publish():
    repo, tag, commit = os.environ["GITHUB_REPOSITORY"], os.environ["TAG"], os.environ["GITHUB_SHA"]
    assets = sorted(Path("release").glob("*.apk"))
    if not assets:
        raise ValueError("No APKs to publish")
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    releases = [release for page in pages for release in page if release["tag_name"] == tag]
    title = Path("release-title.txt").read_text(encoding="utf-8")
    if releases:
        release = releases[0]
        if not release["draft"]:
            raise ValueError("This run already published its release; start a new workflow run")
        if release["target_commitish"] != commit:
            raise ValueError("The existing draft belongs to a different commit")
        gh("release", "edit", tag, "--repo", repo, "--draft", "--title", title,
           "--notes-file", "release-body.md")
    else:
        gh("release", "create", tag, "--repo", repo, "--draft", "--target", commit,
           "--title", title, "--notes-file", "release-body.md")
    for asset in assets:
        gh("release", "upload", tag, str(asset.resolve()), "--repo", repo, "--clobber")
    uploaded = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))["assets"]
    expected = {asset.name: asset.stat().st_size for asset in assets}
    actual = {asset["name"]: asset["size"] for asset in uploaded}
    if actual != expected:
        raise ValueError("The draft assets do not match the complete build output")
    gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest")


if __name__ == "__main__":
    publish()
