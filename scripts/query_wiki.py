#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from crystallize import first_meaningful_line, write_page
from utils import file_uri, find_repo_root, refresh_output_home_if_present


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist a high-value wiki answer into wiki/queries.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--question", required=True, help="Original user question")
    parser.add_argument("--answer", required=True, help="Answer to persist")
    parser.add_argument("--title", default="", help="Optional page title")
    parser.add_argument("--source-path", action="append", default=[], help="Consulted page path")
    parser.add_argument("--follow-up", action="append", default=[], help="Follow-up question or TODO")
    parser.add_argument("--slug", default="", help="Explicit target slug")
    parser.add_argument("--update", action="store_true", help="Update an existing query page with the same title or slug")
    parser.add_argument("--merge-mode", choices=["append", "replace", "dedupe"], default="dedupe", help="How to merge fields when --update is used")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    title = args.title.strip() or args.question.strip()
    summary = first_meaningful_line(args.answer, title)
    default_sources = args.source_path or ["index.md"]
    page_path, action = write_page(
        root=root,
        kind="query",
        title=title,
        summary=summary,
        content=args.answer,
        source_paths=default_sources,
        related_paths=[],
        follow_ups=args.follow_up,
        findings=[],
        tensions=[],
        key_points=[],
        action_label="query",
        slug=args.slug,
        update=args.update,
        merge_mode=args.merge_mode,
    )
    output_home = refresh_output_home_if_present(root)
    print(f"{action.title()} {page_path.relative_to(root).as_posix()}")
    if output_home is not None:
        print("Output hub: output/index.html")
        print(f"Output hub URI: {file_uri(output_home)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
