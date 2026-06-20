#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from utils import append_log, ensure_runtime_dirs, load_template, output_access_lines, render_template, today_str, write_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a new portable ThinkWiki workspace.")
    parser.add_argument("--root", default=".", help="Target wiki root path")
    parser.add_argument("--title", default="My Knowledge Base", help="Knowledge base title")
    parser.add_argument("--language", default="中文", help="Primary language label")
    parser.add_argument("--force", action="store_true", help="Overwrite existing root files from templates")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs(root)

    values = {"TITLE": args.title, "TODAY": today_str(), "LANGUAGE": args.language}
    for source_name, target_name in [
        ("root/.wiki-schema.md", ".wiki-schema.md"),
        ("root/AGENTS.md", "AGENTS.md"),
        ("root/index.md", "index.md"),
        ("root/overview.md", "overview.md"),
        ("root/log.md", "log.md"),
        ("root/purpose.md", "purpose.md"),
    ]:
        target = root / target_name
        if target.exists() and not args.force:
            continue
        write_text(target, render_template(load_template(source_name), values))

    append_log(root, f"[{today_str()}] init | {args.title}", [
        "- created: wiki directories and root files",
        "- next: run ingest or add your first source",
    ])
    print(f"Initialized wiki at {root}")
    for line in output_access_lines(root):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
