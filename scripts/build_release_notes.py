#!/usr/bin/env python3
"""Build the release title and notes from the matrix's per-app metadata."""
import glob
from html import escape
import json
import os
import re
from urllib.parse import quote


RELEASE_BODY_LIMIT = 125_000
FENCE = re.compile(
    r"^((?:[ \t]{0,3}>[ \t]?)*)([ \t]*)((?:[-+*]|\d+[.)])[ \t]+)?(\x60{3,}|~{3,})(.*)$"
)
BLOCK_START = re.compile(r"^ {0,3}(?:#{1,6}|[-+*]|\d+[.)])\s")
HTML_MARKER = re.compile(r"<!--|-->|</?(?:details|pre|table|div|blockquote)\b[^>]*>", re.IGNORECASE)

PATCH_NAMES = {
    "morpheapp/morphe-patches": "Morphe Patches",
    "crimera/piko": "Piko",
    "icysymmetra/tiktok-patches-for-morphe": "TikTok Patches",
}


def table_text(value):
    # Prevent external names and tags from breaking Markdown links or table cells.
    return escape(value, quote=False).translate(
        {ord(char): f"&#{ord(char)};" for char in "\\|`[]*_"}
    )


def release_link(repo, tag, asset_name):
    return f"https://github.com/{repo}/releases/download/{quote(tag, safe='')}/{quote(asset_name, safe='')}"


def downloads_line(repo, tag, app):
    parts = [f"[GitHub]({release_link(repo, tag, app['asset_name'])})"]
    if app.get("mirror_url"):
        mirror_label = table_text(app.get("mirror_label") or "Mirror")
        parts.append(f"[{mirror_label}]({app['mirror_url']})")
    return " · ".join(parts)


def patch_key(app):
    return app["patches_repo"].lower(), app["patches_version"]


def markdown_prefix(body, budget):
    """Keep whole Markdown blocks and list entries; never slice a fenced block."""
    offset = cut = html_depth = 0
    fence = None
    in_comment = False
    for line in body.splitlines(keepends=True):
        if offset > budget:
            break

        marker = FENCE.match(line.rstrip("\r\n"))
        if fence is None and not in_comment and not html_depth:
            if not line.strip() or BLOCK_START.match(line) or marker:
                cut = offset

        if fence is not None:
            if (marker and marker[1].count(">") == fence[0] and not marker[3]
                    and len(marker[2].expandtabs(4)) <= fence[1]
                    and marker[4][0] == fence[2][0] and len(marker[4]) >= len(fence[2])
                    and not marker[5].strip()):
                fence = None
                if not html_depth and offset + len(line.rstrip()) <= budget:
                    cut = offset + len(line.rstrip())
        elif marker and not in_comment:
            indent = len((marker[2] + (marker[3] or "")).expandtabs(4))
            fence = (marker[1].count(">"), indent + 3 if marker[3] else max(3, indent), marker[4])
        else:
            # Ignore markup inside comments. Nested upstream details must close
            # before our preview can end, or our own closing tag would close theirs.
            for token in HTML_MARKER.finditer(line):
                value = token[0]
                if value == "<!--":
                    in_comment = True
                elif value == "-->":
                    in_comment = False
                elif not in_comment:
                    html_depth = max(0, html_depth + (-1 if value.startswith("</") else 1))

        offset += len(line)

    return body[:cut].rstrip()


def changelog_block(heading, source_url, body, *, truncated=False):
    if truncated:
        content = [body, f"Veja o registro completo em: [release do módulo]({source_url})."]
    else:
        content = [f"[Original patch release]({source_url})", body or "_No changelog available._"]
    return "\n\n".join([heading, *content, "</details>"])


def validate_body_size(body, limit=RELEASE_BODY_LIMIT):
    if len(body) > limit:
        raise ValueError(f"Release body has {len(body):,} characters; the limit is {limit:,}.")


def fit_changelogs(header, sections, limit):
    def render(blocks):
        return "\n\n".join([header, *blocks]) + "\n"

    full = [changelog_block(*section) for section in sections]
    body = render(full)
    if len(body) <= limit:
        return body

    # Reserve room for every link and closing tag before distributing any preview
    # text. Short notes that cost less than an empty preview stay intact.
    reserved = [
        changelog_block(heading, url, "", truncated=True) if text else original
        for (heading, url, text), original in zip(sections, full)
    ]
    blocks = [min((original, reserve), key=len) for original, reserve in zip(full, reserved)]
    minimum = len(render(blocks))
    if minimum > limit:
        raise ValueError(
            f"Release skeleton and changelog links need {minimum:,} characters; "
            f"the limit is {limit:,}. Shorten the release metadata."
        )
    remaining = limit - minimum
    needs = [len(original) - len(block) for original, block in zip(full, blocks)]
    pending = sorted((i for i, need in enumerate(needs) if need), key=needs.__getitem__)
    for position, i in enumerate(pending):
        share = remaining // (len(pending) - position)
        if needs[i] <= share:
            blocks[i] = full[i]
        else:
            heading, url, text = sections[i]
            preview = markdown_prefix(text, share)
            blocks[i] = changelog_block(heading, url, preview, truncated=True)
        remaining -= len(blocks[i]) - len(reserved[i])

    body = render(blocks)
    validate_body_size(body, limit)
    return body


def build_notes(repo, tag, apps, *, limit=RELEASE_BODY_LIMIT):
    groups = {}
    for app in apps:
        groups.setdefault(patch_key(app), []).append(app)

    def module_name(key):
        return PATCH_NAMES.get(key[0], groups[key][0]["patches_repo"])

    ordered_keys = sorted(groups, key=lambda key: (module_name(key).casefold(), key))
    anchors = {key: f"patch-changelog-{i}" for i, key in enumerate(ordered_keys, start=1)}

    lines = ["## 🚀 New release is out!", "", "Fresh patched builds are available in this release."]
    if any(app.get("mirror_url") for app in apps):
        lines.extend(["", "Use the temporary mirror if GitHub assets are still processing."])
    lines.extend([
        "", "## Included apps", "",
        "| App | Base version | Patches | Download |",
        "|---|---|---|---|",
    ])
    for app in apps:
        key = patch_key(app)
        label = f"{table_text(module_name(key))} <code>{table_text(key[1])}</code>"
        lines.append(
            f"| {table_text(app['display_name'])} | <code>{table_text(app['version'])}</code> | "
            f"[{label}](#{anchors[key]}) | {downloads_line(repo, tag, app)} |"
        )

    lines.extend([
        "", "## Changelogs", "",
        "These notes cover each patch module as a whole. Some changes may only apply to specific apps.",
    ])
    sections = []
    for key in ordered_keys:
        members = groups[key]
        source_repo = members[0]["patches_repo"]
        source_url = f"https://github.com/{source_repo}/releases/tag/{quote(key[1], safe='')}"
        names = ", ".join(escape(app["display_name"], quote=False) for app in members)
        label = escape(f"{module_name(key)} {key[1]}", quote=False)
        # The matrix shares a resolved release; its changelog is copied into each app's metadata.
        changelog = next((body for app in members if (body := app["changelog"].strip())), None)
        heading = (
            f'<a name="{anchors[key]}"></a>\n\n<details>\n'
            f"<summary><strong>{label}</strong> — {names}</summary>"
        )
        sections.append((heading, source_url, changelog))

    return fit_changelogs("\n".join(lines), sections, limit)


def main():
    repo = os.environ["REPO"]
    tag = os.environ["TAG"]

    apps = []
    for path in sorted(glob.glob("meta/meta-*.json")):
        with open(path, encoding="utf-8") as f:
            apps.append(json.load(f))

    with open("release-body.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(build_notes(repo, tag, apps))

    with open("release-title.txt", "w", encoding="utf-8") as f:
        f.write("Morphe CI Builds")


if __name__ == "__main__":
    main()
