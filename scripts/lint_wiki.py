#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from urllib import error, request

import rebuild_index
from utils import REQUIRED_FIELDS, append_log, collect_wiki_pages, extract_summary, find_repo_root, is_external_link, markdown_links, parse_frontmatter, read_text, today_str, write_text

SUMMARY_PLACEHOLDERS = {
    "",
    "(no summary)",
    "Imported source. Refine this summary with the agent.",
}
SUMMARY_NOISE_HINTS = (
    "<ama-doc>",
    "文件编号",
    "文档版本",
    "修订页",
    "研究问题",
    "作者：",
    "日期：",
    "日期:",
)
CONTINUATION_ENDINGS = tuple("的了和与及并而按把将向在于为是小会度案等其")
TERMINAL_PUNCTUATION = ("。", "！", "？", ".", "!", "?")
BAD_TRAILING_PUNCTUATION = ("：", ":", "；", ";", "，", ",", "、", "（", "(")
LOW_CONFIDENCE = {"mixed", "inferred", ""}
ARCHIVEABLE_STATUS = {"active", "stale", ""}
PLACEHOLDER_PATTERNS = [
    re.compile(r"\bnone yet\b", re.IGNORECASE),
    re.compile(r"\btodo\b", re.IGNORECASE),
    re.compile(r"\bwhat should this source update\b", re.IGNORECASE),
    re.compile(r"\bno relevant pages found\b", re.IGNORECASE),
]
PLACEHOLDER_LINE_PATTERNS = [
    re.compile(r"^(?:[-*]\s*)?none yet\s*$", re.IGNORECASE),
    re.compile(r"^(?:[-*]\s*)?todo(?:[:\s].*)?$", re.IGNORECASE),
    re.compile(r"^(?:[-*]\s*)?what should this source update.*$", re.IGNORECASE),
    re.compile(r"^(?:[-*]\s*)?no relevant pages found.*$", re.IGNORECASE),
]


def parse_iso_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalized_summary(summary: str) -> str:
    return " ".join(summary.strip().split())


def weak_summary_reason(summary: str) -> str | None:
    clean = normalized_summary(summary)
    lowered = clean.lower()
    if clean in SUMMARY_PLACEHOLDERS or len(clean) < 12:
        return "is missing or too short"
    if any(hint in lowered for hint in SUMMARY_NOISE_HINTS):
        return "contains likely metadata or noise"
    if clean.endswith(BAD_TRAILING_PUNCTUATION):
        return "ends with dangling punctuation"
    if re.search(r"\d+$", clean):
        return "appears truncated at a trailing number"
    if len(clean) >= 36 and not clean.endswith(TERMINAL_PUNCTUATION):
        return "looks incomplete because it lacks terminal punctuation"
    if len(clean) >= 24 and clean[-1] in CONTINUATION_ENDINGS:
        return "looks incomplete because it ends mid-sentence"
    if re.search(r"(?:^|\s)(?:\d+(?:\.\d+)+|[一二三四五六七八九十]+、)\s*[\u4e00-\u9fffA-Za-z]{0,20}$", clean):
        return "looks like a section heading fragment"
    return None


def is_weak_summary(summary: str) -> bool:
    return weak_summary_reason(summary) is not None


def is_weak_source_list(raw_sources: object) -> bool:
    if not isinstance(raw_sources, list):
        return True
    meaningful = [str(item).strip() for item in raw_sources if str(item).strip()]
    if not meaningful:
        return True
    return all(item in {"log.md", "index.md"} for item in meaningful)


def has_placeholder_content(body: str) -> bool:
    compact = " ".join(body.split())
    return any(pattern.search(compact) for pattern in PLACEHOLDER_PATTERNS)


def companion_normalized_path(root: Path, page: Path, meta: dict[str, object]) -> Path | None:
    if page.parent.name != "sources":
        return None
    raw_sources = meta.get("sources", [])
    if not isinstance(raw_sources, list) or not raw_sources:
        return None
    raw_path = Path(str(raw_sources[0]))
    if len(raw_path.parts) < 3 or raw_path.parts[0] != "raw":
        return None
    return root / Path("normalized", *raw_path.parts[1:]).with_suffix(".md")


def is_placeholder_line(text: str) -> bool:
    compact = text.strip()
    if not compact:
        return False
    return any(pattern.match(compact) for pattern in PLACEHOLDER_LINE_PATTERNS)


def rebuild_page_text(text: str, body_lines: list[str]) -> str:
    split = text.split("\n---\n", 1)
    if text.startswith("---\n") and len(split) == 2:
        return f"{split[0]}\n---\n" + "\n".join(body_lines).rstrip() + "\n"
    return "\n".join(body_lines).rstrip() + "\n"


def clean_page_body(page: Path) -> tuple[bool, str]:
    text = read_text(page)
    if not text:
        return False, text
    _meta, body = parse_frontmatter(text)
    lines = body.splitlines()
    cleaned: list[str] = []
    changed = False
    seen_in_section: set[tuple[str, str]] = set()
    current_section = ""
    page_resolved = page.resolve()
    pending_blank = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            seen_in_section = set()
            if cleaned and cleaned[-1].strip():
                cleaned.append("")
            cleaned.append(line)
            pending_blank = False
            continue
        if is_placeholder_line(stripped):
            changed = True
            continue
        if not stripped:
            if not cleaned or not cleaned[-1].strip():
                changed = True
                continue
            pending_blank = True
            continue
        if stripped.startswith("- [") and "](" in stripped:
            links = markdown_links(stripped)
            if links:
                target = links[0]
                if not is_external_link(target):
                    resolved = (page.parent / target).resolve()
                    if resolved == page_resolved:
                        changed = True
                        continue
                    key = (current_section, resolved.as_posix())
                    if key in seen_in_section:
                        changed = True
                        continue
                    seen_in_section.add(key)
        if pending_blank and cleaned and cleaned[-1].strip():
            cleaned.append("")
        pending_blank = False
        cleaned.append(line)

    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
        changed = True

    updated = rebuild_page_text(text, cleaned)
    if not changed and updated == text:
        return False, text
    return True, updated


def check_external_link(url: str, timeout: float) -> str | None:
    headers = {"User-Agent": "thinkwiki-lint/1.0"}
    try:
        req = request.Request(url, headers=headers, method="HEAD")
        with request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                return f"HTTP {status}"
            return None
    except error.HTTPError as exc:
        if exc.code in {405, 501}:
            try:
                req = request.Request(url, headers=headers, method="GET")
                with request.urlopen(req, timeout=timeout) as response:
                    status = getattr(response, "status", 200)
                    if status >= 400:
                        return f"HTTP {status}"
                    return None
            except Exception as fallback_exc:  # pragma: no cover - network variance
                return str(fallback_exc)
        return f"HTTP {exc.code}"
    except Exception as exc:  # pragma: no cover - network variance
        return str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint the wiki structure and links.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--fix", action="store_true", help="Rebuild index before reporting")
    parser.add_argument("--stale-days", type=int, default=90, help="Age in days before a page is treated as stale")
    parser.add_argument("--check-external-links", action="store_true", help="Validate external links with HTTP requests")
    parser.add_argument("--external-timeout", type=float, default=5.0, help="Timeout in seconds for external link checks")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    if args.fix:
        write_text(root / "index.md", rebuild_index.build_index(root))

    pages = collect_wiki_pages(root)
    page_paths = {page.resolve() for page in pages}
    inbound: dict[Path, int] = {}
    issues: list[str] = []
    titles: dict[str, list[str]] = {}
    checked_external: set[str] = set()
    fixed_pages: list[str] = []

    if args.fix:
        for page in pages:
            changed, updated = clean_page_body(page)
            if changed:
                write_text(page, updated)
                fixed_pages.append(page.relative_to(root).as_posix())

    for page in pages:
        meta, body = parse_frontmatter(read_text(page))
        missing = [field for field in REQUIRED_FIELDS if field not in meta]
        if missing:
            issues.append(f"[frontmatter] {page.relative_to(root)} missing: {', '.join(missing)}")

        title = str(meta.get("title") or page.stem).strip()
        titles.setdefault(title.casefold(), []).append(page.relative_to(root).as_posix())

        summary = extract_summary(meta, body)
        weak_reason = weak_summary_reason(summary)
        if weak_reason:
            issues.append(f"[weak-summary] {page.relative_to(root)} summary {weak_reason}")

        raw_sources = meta.get("sources", [])
        if is_weak_source_list(raw_sources):
            issues.append(f"[weak-source] {page.relative_to(root)} has no meaningful source paths")
        companion_path = companion_normalized_path(root, page, meta)
        if companion_path is not None and not companion_path.exists():
            issues.append(f"[missing-normalized] {page.relative_to(root)} missing companion {companion_path.relative_to(root)}")
        if has_placeholder_content(body):
            issues.append(f"[placeholder-content] {page.relative_to(root)} still contains placeholder text")

        confidence = str(meta.get("confidence") or "").strip().lower()
        status = str(meta.get("status") or "").strip().lower()
        updated = str(meta.get("updated") or meta.get("created") or "")
        updated_date = parse_iso_date(updated)
        if updated_date is None:
            issues.append(f"[invalid-date] {page.relative_to(root)} has invalid updated date: {updated or 'missing'}")
        else:
            age_days = max((date.today() - updated_date).days, 0)
            if age_days > args.stale_days and status not in {"stale", "archived", "superseded"}:
                issues.append(f"[stale] {page.relative_to(root)} has not been updated for {age_days} days")
            if age_days > args.stale_days * 2 and confidence in LOW_CONFIDENCE and status in ARCHIVEABLE_STATUS:
                issues.append(f"[archive-candidate] {page.relative_to(root)} is old and low-confidence; consider archiving or revalidating")

        for link in markdown_links(body):
            if is_external_link(link):
                if args.check_external_links and link not in checked_external:
                    checked_external.add(link)
                    error_message = check_external_link(link, timeout=args.external_timeout)
                    if error_message:
                        issues.append(f"[broken-external-link] {page.relative_to(root)} -> {link} ({error_message})")
                continue
            target = (page.parent / link).resolve()
            if target.suffix != ".md":
                continue
            if target == page.resolve():
                issues.append(f"[self-link] {page.relative_to(root)} links to itself")
            inbound[target] = inbound.get(target, 0) + 1
            if target not in page_paths and not target.exists():
                issues.append(f"[broken-link] {page.relative_to(root)} -> {link}")
        section_seen: set[tuple[str, str]] = set()
        current_section = ""
        for raw_line in body.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip()
                section_seen = set()
                continue
            if not stripped.startswith("- [") or "](" not in stripped:
                continue
            links = markdown_links(stripped)
            if not links:
                continue
            target = links[0]
            if is_external_link(target):
                continue
            resolved = (page.parent / target).resolve().as_posix()
            key = (current_section, resolved)
            if key in section_seen:
                issues.append(f"[duplicate-link] {page.relative_to(root)} repeats {target} in section {current_section or 'Overview'}")
                continue
            section_seen.add(key)

    for page in pages:
        if inbound.get(page.resolve(), 0) == 0 and page.parent.name != "sources":
            issues.append(f"[orphan] {page.relative_to(root)} has no inbound wiki links")

    for _normalized_title, paths in sorted(titles.items()):
        if len(paths) > 1:
            issues.append(f"[duplicate-title] {', '.join(paths)}")

    report_lines = ["# Lint Report", "", f"- Date: {today_str()}", f"- Issues: {len(issues)}", ""]
    if fixed_pages:
        report_lines.extend([f"- Auto-fixed: {len(fixed_pages)} page(s)", *[f"  - {item}" for item in fixed_pages], ""])
    if issues:
        report_lines.extend(f"- {item}" for item in issues)
    else:
        report_lines.append("- No issues found")

    report_path = root / "output" / "exports" / "lint-report.md"
    write_text(report_path, "\n".join(report_lines))
    append_log(root, f"[{today_str()}] lint | {len(issues)} issues", [f"- report: {report_path.relative_to(root).as_posix()}"])
    print("\n".join(report_lines))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
