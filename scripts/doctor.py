#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime_capabilities import CAPABILITY_LABELS, CAPABILITY_ORDER, runtime_report

ROOT_REQUIRED_FILES = [
    "SKILL.md",
    "requirements.txt",
    "scripts/thinkwiki",
]
ROOT_REQUIRED_SCRIPTS = [
    "scripts/thinkwiki",
    "scripts/bootstrap_runtime.py",
    "scripts/init_wiki.py",
    "scripts/convert_source.py",
    "scripts/ingest.py",
    "scripts/ask.py",
    "scripts/correct.py",
    "scripts/query_wiki.py",
    "scripts/digest.py",
    "scripts/crystallize.py",
    "scripts/rebuild_index.py",
    "scripts/lint_wiki.py",
    "scripts/build_graph.py",
    "scripts/build_viewer.py",
    "scripts/doctor.py",
    "scripts/runtime_capabilities.py",
    "scripts/utils.py",
]
ROOT_REQUIRED_TEMPLATES = [
    "templates/root/.wiki-schema.md",
    "templates/root/AGENTS.md",
    "templates/root/index.md",
    "templates/root/log.md",
    "templates/root/overview.md",
    "templates/root/purpose.md",
    "templates/pages/source.md",
    "templates/pages/topic.md",
    "templates/pages/query.md",
    "templates/pages/synthesis.md",
    "templates/pages/decision.md",
    "templates/pages/concept.md",
]
WIKI_REQUIRED_PATHS = [
    ".wiki-schema.md",
    "index.md",
    "log.md",
    "overview.md",
    "purpose.md",
    "raw",
    "normalized",
    "wiki",
    "output",
]
def check_root_skill_package(repo_root: Path, errors: list[str]) -> None:
    for relative_path in ROOT_REQUIRED_FILES:
        target = repo_root / relative_path
        if not target.exists():
            errors.append(f"[missing-root-asset] {target}")
    for script_path in ROOT_REQUIRED_SCRIPTS:
        if not (repo_root / script_path).exists():
            errors.append(f"[missing-script-asset] {repo_root / script_path}")
    for template_path in ROOT_REQUIRED_TEMPLATES:
        if not (repo_root / template_path).exists():
            errors.append(f"[missing-template-asset] {repo_root / template_path}")
def check_wiki_workspace(wiki_root: Path | None, errors: list[str]) -> None:
    if wiki_root is None or not wiki_root.exists():
        return
    for relative_path in WIKI_REQUIRED_PATHS:
        target = wiki_root / relative_path
        if not target.exists():
            errors.append(f"[missing-wiki-asset] {target}")


def check_runtime_dependencies(errors: list[str]) -> list[str]:
    lines: list[str] = []
    report = runtime_report()
    for capability in CAPABILITY_ORDER:
        missing = report[capability]
        label = CAPABILITY_LABELS[capability]
        if not missing:
            lines.append(f"- {label}: ready")
            continue
        modules = ", ".join(item["module"] for item in missing)
        lines.append(f"- {label}: missing {modules}")
        for item in missing:
            errors.append(
                f"[missing-runtime-dependency] {label} requires Python module `{item['module']}` "
                f"for {item['purpose']}: {item['reason']}"
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the ThinkWiki skill package is usable.")
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    parser.add_argument("--wiki-root", default="", help="Optional wiki workspace path to validate")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    wiki_root = Path(args.wiki_root).resolve() if args.wiki_root else None

    errors: list[str] = []
    check_root_skill_package(repo_root, errors)
    check_wiki_workspace(wiki_root, errors)
    capability_lines = check_runtime_dependencies(errors)

    lines = [
        "# Runtime Doctor Report",
        "",
        f"- Repo Root: {repo_root}",
        f"- Python: {Path(sys.executable).resolve()}",
        f"- Issues: {len(errors)}",
        "",
        "## Capability Status",
        "",
        *capability_lines,
        "",
    ]
    if errors:
        lines.extend(f"- {item}" for item in errors)
    else:
        lines.append("- All checks passed")

    print("\n".join(lines))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
