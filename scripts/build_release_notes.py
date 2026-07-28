#!/usr/bin/env python3
"""
build_release_notes.py

Lê todos os meta/meta-*.json gerados pelos jobs da matrix (um por app) e
monta:
  - release-title.txt : título da Release
  - release-body.md    : descrição da Release (tabela + seção por app)

Variáveis de ambiente esperadas:
  REPO - owner/repo (ex: GustavoMends/morphe-ci)
  TAG  - tag da release (ex: 7)
"""
import datetime
import glob
import json
import os


def release_link(repo, tag, asset_name):
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"


def downloads_line(repo, tag, app, label_release):
    parts = [f"[{label_release}]({release_link(repo, tag, app['asset_name'])})"]
    if app.get("mirror_url"):
        mirror_label = app.get("mirror_label") or "Mirror"
        parts.append(f"[{mirror_label}]({app['mirror_url']})")
    return " · ".join(parts)


def main():
    repo = os.environ["REPO"]
    tag = os.environ["TAG"]

    apps = []
    for path in sorted(glob.glob("meta/meta-*.json")):
        with open(path, encoding="utf-8") as f:
            apps.append(json.load(f))

    lines = []
    lines.append(f"## 🚀 New release is out!")
    lines.append("")
    lines.append("Fresh patched builds are available in this release.  ")
    lines.append("Use the temporary mirror if GitHub assets are still processing.")
    lines.append("")
    lines.append("## Included apps")
    lines.append("")
    lines.append("| App | App version | Patches | Quick download |")
    lines.append("|---|---|---|---|")
    for app in apps:
        patches_label = f"{app['patches_repo']} {app['patches_version']}"
        lines.append(
            f"| {app['display_name']} | {app['version']} | {patches_label} | "
            f"{downloads_line(repo, tag, app, 'Release')} |"
        )
    lines.append("")
    lines.append("---")

    for app in apps:
        lines.append("")
        lines.append(f"## {app['display_name']}")
        lines.append("")
        lines.append(f"**App version:** {app['version']}  ")
        lines.append(f"**Patches source:** {app['patches_repo']}  ")
        lines.append(f"**Patches version:** {app['patches_version']}  ")
        lines.append(f"**Downloads:** {downloads_line(repo, tag, app, 'GitHub Release')}")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary><strong>Changelog</strong></summary>")
        lines.append("")
        lines.append(app["changelog"].strip() or "_Sem changelog disponível._")
        lines.append("")
        lines.append("</details>")

    with open("release-body.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    with open("release-title.txt", "w", encoding="utf-8") as f:
        f.write("Morphe CI Builds")


if __name__ == "__main__":
    main()
