#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re

from crystallize import first_meaningful_line, text_tokens, write_page
from utils import (
    collect_wiki_pages,
    extract_summary,
    file_uri,
    find_repo_root,
    normalize_repo_path,
    parse_frontmatter,
    read_text,
    refresh_output_home_if_present,
    today_str,
    write_text,
)

CONFIDENCE_BONUS = {
    "verified": 8,
    "extracted": 5,
    "mixed": 2,
    "inferred": 0,
}
STATUS_BONUS = {
    "active": 3,
    "stale": -4,
    "archived": -7,
    "superseded": -9,
}
TYPE_BONUS = {
    "source": 5,
    "normalized": 4,
    "topic": 4,
    "concept": 3,
    "decision": 2,
    "synthesis": 1,
    "query": -4,
}
SECTION_PREFERENCE = {
    "Summary": 5,
    "Decision": 5,
    "Answer": 5,
    "Key Points": 4,
    "Findings": 4,
    "Reasoning": 4,
    "Details": 3,
    "Evidence": 1,
    "Consulted Pages": 0,
    "Follow-ups": 0,
}
BLOCKED_SECTIONS = {
    "Connections",
    "Open Questions",
    "Consulted Pages",
    "Raw Source",
    "Extracted Markdown",
    "Extracted Excerpt",
}
PLACEHOLDER_PATTERNS = [
    re.compile(r"\bnone yet\b", re.IGNORECASE),
    re.compile(r"\btodo\b", re.IGNORECASE),
    re.compile(r"\bwhat should this source update\b", re.IGNORECASE),
    re.compile(r"\bno relevant pages found\b", re.IGNORECASE),
    re.compile(r"\bno matching evidence snippets found\b", re.IGNORECASE),
]
META_LINE_PREFIXES = ("来源：", "作者：", "发布日期：", "原文链接：")
NOISE_MARKERS = (
    "<ama-doc>",
    "文件编号",
    "文档版本",
    "最后修改日期",
    "修订页",
    "编 写 人",
    "编写时间",
    "目录",
)
DEFINITION_HINTS = ("是", "定义", "本质", "指的是", "意味着", "可概括为")
DECISION_HINTS = ("建议", "应", "因此", "因为", "关键", "核心", "推荐")
ANSWER_HINTS = ("定义为", "本质上是", "指的是", "意味着", "换句话说", "可归纳为")
QUESTION_SEGMENT_HINTS = ("研究问题", "问题一", "问题二", "问题三", "问题四")


def parse_iso_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def freshness_bonus(updated: str) -> int:
    parsed = parse_iso_date(updated)
    if parsed is None:
        return 0
    age_days = max((date.today() - parsed).days, 0)
    if age_days <= 30:
        return 3
    if age_days <= 90:
        return 1
    if age_days > 365:
        return -2
    return 0


def candidate_record(root: Path, page: Path) -> dict[str, object]:
    meta, body = parse_frontmatter(read_text(page))
    title = str(meta.get("title") or page.stem)
    summary = extract_summary(meta, body)
    confidence = str(meta.get("confidence") or "").strip().lower()
    status = str(meta.get("status") or "active").strip().lower()
    updated = str(meta.get("updated") or meta.get("created") or "")
    page_type = str(meta.get("type") or page.parent.name[:-1])
    source_paths = [normalize_repo_path(root, str(item)) for item in meta.get("sources", [])]
    return {
        "path": page,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "status": status,
        "updated": updated,
        "type": page_type,
        "sources": source_paths,
        "body": body,
    }


def extract_title_from_body(body: str, fallback: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title
    return fallback


def meaningful_body_summary(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if is_noise_line(line):
            continue
        if line.startswith(("- 来源：", "- 作者：", "- 发布日期：", "- 原文链接：")):
            continue
        if line.startswith(("更新时间", "更新于", "Published:", "Updated:")):
            continue
        if line.startswith(("http://", "https://")):
            continue
        return plain_text(line)[:120]
    return "(no summary)"


def normalized_record(root: Path, page: Path) -> dict[str, object]:
    body = read_text(page)
    title = extract_title_from_body(body, page.stem)
    raw_candidates = list((root / "raw").glob(f"**/{page.stem}.*"))
    sources = [candidate.relative_to(root).as_posix() for candidate in raw_candidates[:1]]
    return {
        "path": page,
        "title": title,
        "summary": meaningful_body_summary(body),
        "confidence": "extracted",
        "status": "active",
        "updated": "",
        "type": "normalized",
        "sources": sources,
        "body": body,
    }


def slugify_section_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "section"


def is_placeholder_text(text: str) -> bool:
    compact = " ".join(text.split()).strip()
    if not compact:
        return True
    if len(compact) <= 4:
        return True
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(compact):
            return True
    return False


def is_metadata_only_text(text: str) -> bool:
    compact = " ".join(text.split()).strip(" -")
    if not compact:
        return True
    parts = [part.strip() for part in compact.split(" - ") if part.strip()]
    if not parts:
        return True
    return all(part.startswith(META_LINE_PREFIXES) for part in parts)


def plain_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    return " ".join(text.split()).strip(" -|,;")


def is_table_like_text(text: str) -> bool:
    compact = text.strip()
    if not compact:
        return False
    if compact.count("|") >= 4:
        return True
    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    if lines and sum(1 for line in lines if "|" in line) >= max(2, len(lines) // 2 + 1):
        return True
    return False


def is_toc_like_text(text: str) -> bool:
    compact = plain_text(text)
    if not compact:
        return False
    if compact.startswith(("1.", "1.1", "2.", "2.1")) and len(compact) <= 40:
        return True
    if re.match(r"^\d+(?:\.\d+){0,3}\s*[\u4e00-\u9fffA-Za-z].*\d+$", compact):
        return True
    return False


def is_noise_line(line: str) -> bool:
    compact = plain_text(line)
    if not compact:
        return True
    if compact in {"---", "***"}:
        return True
    if compact.startswith(NOISE_MARKERS):
        return True
    if is_table_like_text(compact):
        return True
    if is_toc_like_text(compact):
        return True
    if compact.startswith(("**")) and any(marker in compact for marker in NOISE_MARKERS):
        return True
    return False


def cjk_ngrams(text: str, size: int = 2) -> set[str]:
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    if len(chars) < size:
        return set(chars)
    return {"".join(chars[index : index + size]) for index in range(len(chars) - size + 1)}


def text_match_score(query: str, query_tokens: set[str], text: str) -> int:
    normalized = plain_text(text)
    if not normalized:
        return 0
    normalized_tokens = text_tokens(normalized)
    overlap = query_tokens.intersection(normalized_tokens)
    score = len(overlap) * 4
    query_lower = query.strip().lower()
    lowered = normalized.lower()
    if query_lower and query_lower in lowered:
        score += 8
    query_ngrams = cjk_ngrams(query)
    if query_ngrams:
        text_ngrams = cjk_ngrams(normalized)
        score += len(query_ngrams.intersection(text_ngrams))
    return score


def segment_quality_bonus(section: str, text: str, question: str) -> int:
    normalized = plain_text(text)
    if not normalized:
        return -20
    score = SECTION_PREFERENCE.get(section, 0)
    if is_table_like_text(text):
        score -= 10
    if is_toc_like_text(text):
        score -= 8
    if len(normalized) < 20:
        score -= 3
    if normalized.endswith(("？", "?")):
        score -= 4
    if any(hint in normalized for hint in QUESTION_SEGMENT_HINTS):
        score -= 6
    if any(hint in normalized for hint in ANSWER_HINTS):
        score += 6
    if any(hint in normalized for hint in DEFINITION_HINTS) and any(token in question for token in ("什么", "定义", "本质")):
        score += 8
    if any(hint in normalized for hint in DECISION_HINTS) and any(token in question for token in ("为什么", "如何", "建议", "应")):
        score += 6
    return score


def informative_segments(body: str, limit: int = 6) -> list[dict[str, str]]:
    candidates: list[tuple[int, dict[str, str]]] = []
    for item in body_segments(body):
        snippet = item["snippet"]
        section = item["section"]
        if is_noise_line(snippet):
            continue
        quality = segment_quality_bonus(section, snippet, "")
        if quality <= -5:
            continue
        candidates.append((quality, item))
    candidates.sort(key=lambda item: (-item[0], item[1]["section"], item[1]["snippet"]))
    return [item for _score, item in candidates[:limit]]


def body_segments(body: str) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    current_section = "Overview"
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_lines
        lines = [line.strip() for line in block_lines if line.strip()]
        block_lines = []
        if not lines:
            return
        if all(line.startswith("- [") and "](" in line for line in lines):
            return
        text = " ".join(line for line in lines if not line.startswith("```")).strip()
        text = re.sub(r"^(?:-\s+)+", "", text).strip()
        if not text:
            return
        text = plain_text(text)
        if not text:
            return
        text_without_links = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text).strip(" -|")
        if not text_without_links:
            return
        if current_section in BLOCKED_SECTIONS:
            return
        if is_placeholder_text(text_without_links):
            return
        if is_metadata_only_text(text_without_links):
            return
        if is_noise_line(text_without_links):
            return
        segments.append({
            "section": current_section,
            "snippet": text[:400],
        })

    for raw_line in body.replace("\r\n", "\n").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped in {"---", "***"}:
            continue
        if stripped.startswith("![]("):
            continue
        if stripped.startswith("<") and stripped.endswith(">"):
            continue
        if stripped.startswith("## "):
            flush_block()
            current_section = stripped[3:].strip() or "Overview"
            continue
        if stripped.startswith("### "):
            flush_block()
            current_section = stripped[4:].strip() or current_section
            continue
        if not stripped:
            flush_block()
            continue
        if stripped.startswith("#"):
            continue
        block_lines.append(stripped)

    flush_block()
    return segments


def candidate_score(question: str, question_tokens: set[str], record: dict[str, object]) -> int:
    title = str(record["title"])
    summary = str(record["summary"])
    body = str(record["body"])
    confidence = str(record["confidence"])
    status = str(record["status"])
    page_type = str(record["type"])

    score = text_match_score(question, question_tokens, title) * 2
    score += text_match_score(question, question_tokens, summary)
    best_segment_score = 0
    for item in informative_segments(body, limit=6):
        segment_score = text_match_score(question, question_tokens, item["snippet"])
        segment_score += segment_quality_bonus(item["section"], item["snippet"], question)
        if segment_score > best_segment_score:
            best_segment_score = segment_score
    score += best_segment_score
    score += CONFIDENCE_BONUS.get(confidence, 0)
    score += STATUS_BONUS.get(status, 0)
    score += TYPE_BONUS.get(page_type, 0)
    score += freshness_bonus(str(record["updated"]))

    question_lower = question.strip().lower()
    joined = " ".join([title.lower(), summary.lower(), plain_text(body).lower()])
    if question_lower and question_lower in joined:
        score += 6
    if question_lower and plain_text(title).lower() in question_lower:
        score += 4
    if is_table_like_text(summary):
        score -= 10
    if any(marker in plain_text(summary) for marker in NOISE_MARKERS):
        score -= 8
    return score


def evidence_score(question: str, question_tokens: set[str], record: dict[str, object], section: str, segment: str, page_score: int) -> int:
    if section in BLOCKED_SECTIONS or is_placeholder_text(segment) or is_metadata_only_text(segment):
        return 0
    score = text_match_score(question, question_tokens, " ".join([section, segment]))
    if score <= 0:
        return 0
    score += segment_quality_bonus(section, segment, question)
    score += min(page_score, 18)
    score += CONFIDENCE_BONUS.get(str(record["confidence"]), 0)
    score += STATUS_BONUS.get(str(record["status"]), 0)
    return score


def collect_candidate_records(root: Path) -> list[dict[str, object]]:
    records = [candidate_record(root, page) for page in collect_wiki_pages(root)]
    normalized_root = root / "normalized"
    if normalized_root.exists():
        for page in sorted(normalized_root.glob("**/*.md")):
            records.append(normalized_record(root, page))
    return records


def evidence_items(question: str, question_tokens: set[str], ranked: list[tuple[int, dict[str, object]]], per_page_limit: int = 2, total_limit: int = 5) -> list[dict[str, object]]:
    items_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for page_score, record in ranked:
        segments = body_segments(str(record["body"]))
        local_items: list[tuple[int, str, str]] = []
        for item in segments:
            section = item["section"]
            segment = item["snippet"]
            score = evidence_score(question, question_tokens, record, section, segment, page_score)
            if score <= 0:
                continue
            local_items.append((score, section, segment))
        local_items.sort(key=lambda item: (-item[0], item[2].lower()))
        for score, section, segment in local_items[:per_page_limit]:
            dedupe_key = (str(record["title"]), segment.casefold())
            candidate = {
                "page_title": str(record["title"]),
                "page_path": Path(str(record["path"])),
                "page_type": str(record["type"]),
                "section": section,
                "section_anchor": slugify_section_name(section),
                "confidence": str(record["confidence"] or "n/a"),
                "status": str(record["status"] or "n/a"),
                "score": score,
                "snippet": segment,
            }
            existing = items_by_key.get(dedupe_key)
            if existing is None:
                items_by_key[dedupe_key] = candidate
                continue
            existing_pref = SECTION_PREFERENCE.get(str(existing["section"]), 0)
            candidate_pref = SECTION_PREFERENCE.get(section, 0)
            if candidate_pref > existing_pref:
                items_by_key[dedupe_key] = candidate
                continue
            if candidate_pref == existing_pref and int(candidate["score"]) > int(existing["score"]):
                items_by_key[dedupe_key] = candidate
    items = list(items_by_key.values())
    items.sort(key=lambda item: (-int(item["score"]), str(item["page_title"]).lower(), str(item["section"])))
    return items[:total_limit]


def prioritize_evidence_for_best_record(evidence: list[dict[str, object]], best_record: dict[str, object]) -> list[dict[str, object]]:
    best_path = str(best_record["path"])
    best_title = str(best_record["title"]).casefold()
    prioritized = sorted(
        evidence,
        key=lambda item: (
            0 if str(item["page_path"]) == best_path else 1 if str(item["page_title"]).casefold() == best_title else 2,
            -int(item["score"]),
            str(item["page_title"]).lower(),
            str(item["section"]),
        ),
    )
    return prioritized


def expanded_evidence_pool(
    ranked: list[tuple[int, dict[str, object]]],
    limited: list[tuple[int, dict[str, object]]],
    extra_limit: int = 8,
) -> list[tuple[int, dict[str, object]]]:
    if not limited:
        return limited
    best_title = str(limited[0][1]["title"]).casefold()
    pool = list(limited)
    seen_paths = {str(item[1]["path"]) for item in pool}
    for score, record in ranked:
        if str(record["path"]) in seen_paths:
            continue
        if str(record["title"]).casefold() != best_title:
            continue
        pool.append((score, record))
        seen_paths.add(str(record["path"]))
        if len(pool) >= len(limited) + extra_limit:
            break
    return pool


def fallback_evidence_items(ranked: list[tuple[int, dict[str, object]]], total_limit: int = 3) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_titles: set[tuple[str, str]] = set()
    type_priority = {"normalized": 0, "source": 1, "topic": 2, "concept": 3, "decision": 4, "synthesis": 5, "query": 6}
    best_title = str(ranked[0][1]["title"]).casefold() if ranked else ""

    def collect_from_pool(pool: list[tuple[int, dict[str, object]]]) -> None:
        for page_score, record in pool:
            title_key = (str(record["title"]).casefold(), str(record["type"]))
            if title_key in seen_titles:
                continue
            for item in body_segments(str(record["body"])):
                snippet = item["snippet"]
                if is_placeholder_text(snippet):
                    continue
                items.append({
                    "page_title": str(record["title"]),
                    "page_path": Path(str(record["path"])),
                    "page_type": str(record["type"]),
                    "section": item["section"],
                    "section_anchor": slugify_section_name(item["section"]),
                    "confidence": str(record["confidence"] or "n/a"),
                    "status": str(record["status"] or "n/a"),
                    "score": page_score,
                    "snippet": snippet,
                })
                seen_titles.add(title_key)
                break
            if len(items) >= total_limit:
                return

    prioritized = sorted(
        ranked,
        key=lambda item: (
            type_priority.get(str(item[1]["type"]), 99),
            -item[0],
            str(item[1]["title"]).lower(),
        ),
    )
    same_title_pool = [item for item in prioritized if str(item[1]["title"]).casefold() == best_title]
    collect_from_pool(same_title_pool)
    if not items:
        collect_from_pool(prioritized)
    return items


def bullet_label(record: dict[str, object], score: int, root: Path) -> str:
    path = Path(str(record["path"])).relative_to(root).as_posix()
    confidence = str(record["confidence"] or "n/a")
    status = str(record["status"] or "n/a")
    updated = str(record["updated"] or "n/a")
    return (
        f"- {record['title']} | path: {path} | type: {record['type']} | "
        f"confidence: {confidence} | status: {status} | updated: {updated} | score: {score}"
    )


def build_answer(question: str, ranked: list[tuple[int, dict[str, object]]], evidence: list[dict[str, object]]) -> str:
    if not ranked:
        return (
            f"- 当前知识库里没有找到足够相关的页面来回答“{question}”。\n"
            "- 建议先导入相关资料，或补充一个 topic/source 页面后再查询。"
        )

    answer_lines = []
    best_score, best = ranked[0]
    answer_lines.append(
        f"- 当前最相关的条目是《{best['title']}》，类型为 {best['type']}，"
        f"置信度为 {best['confidence'] or 'n/a'}，状态为 {best['status'] or 'n/a'}。"
    )
    answer_lines.append(f"- 该页摘要：{best['summary']}")
    if evidence:
        top = evidence[0]
        answer_lines.append(
            f"- 最直接的证据摘录来自《{top['page_title']}》的“{top['section']}”部分：{top['snippet']}"
        )

    if len(ranked) > 1:
        other_titles = "；".join(f"《{record['title']}》" for _score, record in ranked[1:4])
        answer_lines.append(f"- 其他可交叉参考的页面有：{other_titles}。")

    low_confidence = [
        record["title"]
        for _score, record in ranked
        if str(record["confidence"]) in {"mixed", "inferred", ""}
    ]
    if low_confidence:
        answer_lines.append(f"- 需要额外验证的页面包括：{'；'.join(f'《{title}》' for title in low_confidence[:3])}。")

    stale_pages = [
        record["title"]
        for _score, record in ranked
        if str(record["status"]) in {"stale", "archived", "superseded"}
    ]
    if stale_pages:
        answer_lines.append(f"- 其中有较旧或已降权的内容：{'；'.join(f'《{title}》' for title in stale_pages[:3])}。")

    answer_lines.append(f"- 检索排序优先考虑标题命中、摘要命中、置信度、状态和更新时间；最佳匹配得分为 {best_score}。")
    return "\n".join(answer_lines)


def evidence_label(item: dict[str, object], root: Path) -> str:
    path = Path(str(item["page_path"])).relative_to(root).as_posix()
    ref = f"{path}#{item['section_anchor']}"
    return (
        f"- 《{item['page_title']}》 | path: {path} | type: {item['page_type']} | "
        f"section: {item['section']} | ref: {ref} | confidence: {item['confidence']} | status: {item['status']} | score: {item['score']} | "
        f"snippet: {item['snippet']}"
    )


def answer_with_evidence(answer: str, evidence: list[dict[str, object]], root: Path) -> str:
    if not evidence:
        return answer
    lines = [answer, "", "### Evidence", ""]
    lines.extend(evidence_label(item, root) for item in evidence)
    return "\n".join(lines)


def sanitize_saved_query_page(page_path: Path, root: Path) -> None:
    page_text = read_text(page_path)
    if not page_text:
        return
    self_repo_path = page_path.relative_to(root).as_posix()
    page_name = page_path.name
    lines = page_text.splitlines()
    cleaned: list[str] = []
    in_sources = False
    in_consulted = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("sources:"):
            in_sources = True
            in_consulted = False
            cleaned.append(line)
            continue
        if stripped.startswith("## "):
            in_sources = False
            in_consulted = stripped == "## Consulted Pages"
            cleaned.append(line)
            continue
        if in_sources and stripped.startswith("-"):
            if self_repo_path in stripped:
                continue
            cleaned.append(line)
            continue
        if in_sources and stripped.startswith("-") is False and stripped.startswith("tags:"):
            in_sources = False
            cleaned.append(line)
            continue
        if in_sources and stripped.startswith("-") is False and stripped:
            in_sources = False
        if in_consulted and f"]({page_name})" in stripped:
            continue
        cleaned.append(line)

    write_text(page_path, "\n".join(cleaned))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the wiki a question using lightweight page ranking.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--question", required=True, help="Question to ask the wiki")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of pages to consult")
    parser.add_argument("--save", action="store_true", help="Persist the ask result into wiki/queries")
    parser.add_argument("--title", default="", help="Optional query page title when --save is used")
    parser.add_argument("--follow-up", action="append", default=[], help="Optional follow-up item when --save is used")
    parser.add_argument("--slug", default="", help="Explicit query page slug when --save is used")
    parser.add_argument("--update", action="store_true", help="Update an existing query page when --save is used")
    parser.add_argument("--merge-mode", choices=["append", "replace", "dedupe"], default="replace", help="How to merge fields when --save is used")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    question_tokens = text_tokens(args.question)
    ranked: list[tuple[int, dict[str, object]]] = []

    for record in collect_candidate_records(root):
        score = candidate_score(args.question, question_tokens, record)
        if score <= 0:
            continue
        ranked.append((score, record))

    ranked.sort(key=lambda item: (-item[0], str(item[1]["title"]).lower()))
    non_query_ranked = [item for item in ranked if str(item[1]["type"]) != "query"]
    primary_ranked = non_query_ranked or ranked
    limited = primary_ranked[: max(args.limit, 1)]
    evidence_pool = expanded_evidence_pool(primary_ranked, limited)
    evidence = evidence_items(args.question, question_tokens, evidence_pool)
    if not evidence:
        evidence = fallback_evidence_items(evidence_pool)
    if limited and evidence:
        evidence = prioritize_evidence_for_best_record(evidence, limited[0][1])
    answer = build_answer(args.question, limited, evidence)
    consulted_paths = [Path(str(record["path"])).relative_to(root).as_posix() for _score, record in limited]

    lines = [
        "# Ask Result",
        "",
        f"- Date: {today_str()}",
        f"- Question: {args.question}",
        f"- Consulted: {len(limited)}",
        "",
        "## Answer",
        "",
        answer,
        "",
        "## Evidence",
        "",
    ]

    if evidence:
        lines.extend(evidence_label(item, root) for item in evidence)
    else:
        lines.append("- No matching evidence snippets found")

    lines.extend([
        "",
        "## Consulted Pages",
        "",
    ])

    if limited:
        lines.extend(bullet_label(record, score, root) for score, record in limited)
    else:
        lines.append("- No relevant pages found")

    if args.save:
        title = args.title.strip() or args.question.strip()
        summary = first_meaningful_line(answer, title)
        saved_content = answer_with_evidence(answer, evidence, root)
        page_path, action = write_page(
            root=root,
            kind="query",
            title=title,
            summary=summary,
            content=saved_content,
            source_paths=consulted_paths or ["index.md"],
            related_paths=[],
            follow_ups=args.follow_up,
            findings=[],
            tensions=[],
            key_points=[],
            action_label="ask",
            slug=args.slug,
            update=args.update,
            merge_mode=args.merge_mode,
        )
        sanitize_saved_query_page(page_path, root)
        lines.extend([
            "",
            "## Query Page",
            "",
            f"- {action}: {page_path.relative_to(root).as_posix()}",
        ])

    output_home = refresh_output_home_if_present(root)
    if output_home is not None:
        lines.extend([
            "",
            "## Output Pages",
            "",
            "- Open output/index.html to quickly access the local viewer and graph pages.",
            f"- file URI: {file_uri(output_home)}",
        ])

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
