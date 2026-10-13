#!/usr/bin/env python3
"""Resolve GitHub assets once per run and verify every downloaded/cached file."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

SNAPSHOT = Path("resolved-inputs.json")


def curl(url, token, *args, binary=False):
    command = ["curl", "--fail", "--silent", "--show-error", "--location",
               "--retry", "3", "--retry-delay", "2", "--retry-max-time", "600",
               "--connect-timeout", "15", "--max-time", "600" if binary else "60",
               "--proto", "=https", "--proto-redir", "=https",
               "-H", f"Authorization: Bearer {token}",
               "-H", "Accept: application/octet-stream" if binary else "Accept: application/vnd.github+json",
               "-H", "X-GitHub-Api-Version: 2022-11-28", *args, url]
    result = subprocess.run(command, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    if result.returncode:
        # Never include the command line (and its authentication header) in an exception.
        raise RuntimeError(f"GitHub transfer failed with curl exit code {result.returncode}")
    return result.stdout


def api(endpoint, token):
    if not token:
        raise ValueError("A GitHub token is required to resolve release assets")
    return json.loads(curl(f"https://api.github.com/{endpoint}", token))


def repository(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError(f"Invalid GitHub repository: {value}")
    return value


def single_line(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Expected a nonempty single-line value")
    return value


def select_asset(release, repo, matches):
    assets = [asset for asset in release["assets"] if matches(asset["name"])]
    if len(assets) != 1:
        raise ValueError(f"Expected exactly one matching asset in {repo}; found {len(assets)}")
    asset = assets[0]
    if type(asset["id"]) is not int or asset["id"] <= 0 or type(asset["size"]) is not int or asset["size"] <= 0:
        raise ValueError(f"Invalid asset ID or size in {repo}")
    digest = asset.get("digest")
    if digest is not None and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError(f"Unsupported asset digest in {repo}")
    return {"url": f"https://api.github.com/repos/{repository(repo)}/releases/assets/{asset['id']}",
            "id": asset["id"], "size": asset["size"], "digest": digest}


def write_values(path, values):
    with Path(path).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={single_line(str(value))}\n")


def resolve(apps, token, mirror_token):
    cli_repo = "MorpheApp/morphe-desktop"
    cli_release = api(f"repos/{cli_repo}/releases/latest", token)
    cli = {"tag": single_line(cli_release["tag_name"]),
           "asset": select_asset(cli_release, cli_repo, lambda name: name.endswith("-all.jar"))}
    bundles, mirrors, resolved = {}, {}, []
    for app in apps:
        repo = repository(app["patches_repo"])
        if repo not in bundles:
            release = api(f"repos/{repo}/releases/latest", token)
            bundles[repo] = {"tag": single_line(release["tag_name"]), "changelog": release.get("body") or "",
                             "asset": select_asset(release, repo, lambda name: name.endswith(".mpp"))}
        mirror_repo = repository(app["mirror_repo"])
        mirror_key = (mirror_repo, app["mirror_tag"])
        if mirror_key not in mirrors:
            endpoint = f"repos/{mirror_repo}/releases/tags/{quote(app['mirror_tag'], safe='')}"
            mirrors[mirror_key] = api(endpoint, mirror_token)
        mirror = select_asset(mirrors[mirror_key], mirror_repo, lambda name: name == app["mirror_asset"])
        extension = app["mirror_asset"].rsplit(".", 1)[-1]
        if extension not in {"apk", "apkm"}:
            raise ValueError(f"Unsupported input extension: {extension}")
        resolved.append({"app": app, "patches": bundles[repo], "input": mirror,
                         "input_file": f"{app['output_name']}.{extension}"})
    return {"cli": cli, "apps": resolved}


def get_app(snapshot, name):
    return next(item for item in snapshot["apps"] if item["app"]["name"] == name)


def export(snapshot, name):
    item = get_app(snapshot, name)
    outputs = {"jar_tag": snapshot["cli"]["tag"], "jar_id": snapshot["cli"]["asset"]["id"],
               "patches_version": item["patches"]["tag"], "patches_id": item["patches"]["asset"]["id"],
               "repo_slug": item["app"]["patches_repo"].replace("/", "-"),
               "asset_id": item["input"]["id"], "input_file": item["input_file"]}
    write_values(os.environ["GITHUB_OUTPUT"], outputs)
    write_values(os.environ["GITHUB_ENV"], {"PATCHES_VERSION": item["patches"]["tag"], "INPUT_FILE": item["input_file"]})
    Path(f"changelog-{name}.md").write_text(item["patches"]["changelog"], encoding="utf-8")


def verify(path, asset):
    if not path.is_file() or path.stat().st_size != asset["size"]:
        raise ValueError(f"Asset size mismatch: {path}")
    if asset["digest"]:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != asset["digest"].split(":", 1)[1].lower():
            raise ValueError(f"Asset SHA-256 mismatch: {path}")


def fetch(asset, path, token):
    if not token:
        raise ValueError("A GitHub token is required to download release assets")
    if path.exists():
        try:
            verify(path, asset)
            return
        except ValueError:
            print(f"Discarding invalid cached asset: {path}")
    temporary = path.with_name(path.name + ".part")
    try:
        curl(asset["url"], token, "--output", str(temporary), binary=True)
        verify(temporary, asset)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["resolve", "export", "fetch"])
    parser.add_argument("--name")
    parser.add_argument("--kind", choices=["cli", "patches", "apk"])
    args = parser.parse_args()
    if args.command == "resolve":
        import yaml
        apps = yaml.safe_load(Path("apps.yml").read_text(encoding="utf-8"))["apps"]
        snapshot = resolve(apps, os.environ["GH_TOKEN"], os.environ["MIRROR_REPO_TOKEN"])
        SNAPSHOT.write_text(json.dumps(snapshot), encoding="utf-8")
        return
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if args.command == "export":
        export(snapshot, args.name)
        return
    item = get_app(snapshot, args.name)
    if args.kind == "cli":
        asset, path = snapshot["cli"]["asset"], Path("morphe-desktop-all.jar")
    elif args.kind == "patches":
        asset, path = item["patches"]["asset"], Path(f"patches-{args.name}.mpp")
    elif args.kind == "apk":
        asset, path = item["input"], Path(item["input_file"])
    else:
        parser.error("fetch requires --kind")
    token = os.environ["MIRROR_REPO_TOKEN"] if args.kind == "apk" else os.environ["GH_TOKEN"]
    fetch(asset, path, token)


if __name__ == "__main__":
    main()
