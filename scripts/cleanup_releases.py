#!/usr/bin/env python3
"""Keep the newest published build releases, leaving other release series alone."""
import json
import os
import re
import subprocess


def positive_keep(value):
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise ValueError("keep must be an integer greater than or equal to 1")
    return int(value)


def select_old_releases(pages, keep):
    releases = [release for page in pages for release in page
                if re.fullmatch(r"build-[0-9]+", release["tag_name"])
                and not release["draft"] and not release["prerelease"] and release["published_at"]]
    releases.sort(key=lambda release: (release["published_at"], release["id"]), reverse=True)
    return releases[keep:]


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def cleanup():
    keep = positive_keep(os.environ["KEEP"])
    repo = os.environ["GITHUB_REPOSITORY"]
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    releases = select_old_releases(pages, keep)
    print(f"Keeping the newest {keep} published build releases; deleting {len(releases)} older builds.")
    for release in releases:
        print(f"Deleting {release['tag_name']}")
        gh("release", "delete", release["tag_name"], "--repo", repo, "--cleanup-tag", "--yes")


if __name__ == "__main__":
    cleanup()
