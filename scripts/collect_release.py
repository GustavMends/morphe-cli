#!/usr/bin/env python3
"""Collect a complete matrix before allowing any release publication."""
import json
import os
from pathlib import Path
import shutil


def collect(matrix, artifacts=Path("artifacts"), destination=Path("release"), meta=Path("meta")):
    expected = {app["name"] for app in matrix["include"]}
    if not expected or len(expected) != len(matrix["include"]):
        raise ValueError("The release matrix must contain unique apps and cannot be empty")
    results = {}
    filenames = set()
    for path in artifacts.glob("*/meta-*.json"):
        app = json.loads(path.read_text(encoding="utf-8"))
        name, filename = app["name"], app["asset_name"]
        if name not in expected or name in results:
            raise ValueError(f"Unexpected or duplicate result: {name}")
        if (Path(filename).name != filename or "/" in filename or "\\" in filename
                or not filename.endswith(".apk") or filename in filenames):
            raise ValueError(f"Invalid or duplicate asset filename: {filename}")
        apk = path.parent / filename
        if not apk.is_file() or apk.stat().st_size == 0:
            raise ValueError(f"Missing or empty APK for {name}")
        results[name] = (path, apk)
        filenames.add(filename)
    if results.keys() != expected:
        raise ValueError(f"Missing results: {', '.join(sorted(expected - results.keys()))}")
    destination.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    for name, (metadata, apk) in results.items():
        shutil.copy2(metadata, meta / f"meta-{name}.json")
        shutil.copy2(apk, destination / apk.name)


if __name__ == "__main__":
    collect(json.loads(os.environ["MATRIX_JSON"]))
