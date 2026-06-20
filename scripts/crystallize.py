#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

import rebuild_index
from utils import (
    PAGE_TYPE_TO_DIR,
    append_log,
    collect_wiki_pages,
    extract_summary,
    file_uri,
    find_repo_root,
    frontmatter_list,
    load_template,
    markdown_link_list,
    markdown_links,
    normalize_repo_path,
    parse_frontmatter,
    read_text,
    relative_link,
    render_template,
    slugify,
    today_str,
    unique_path,
    write_text,
    refresh_output_home_if_present,
)

TEMPLATE_BY_KIND = {
    "query": "pages/query.md",
    "synthesis": "pages/synthesis.md",
    "decision": "pages/decision.md",
    "concept": "pages/concept.md",
}
MERGE_MODES = ("append", "replace", "dedupe")
TYPE_BONUS_BY_KIND = {
    "query": {"source": 3, "topic": 2, "concept": 1},
    "synthesis": {"topic": 3, "concept": 2, "source": 1},
    "decision": {"decision": 3, "concept": 2, "topic": 1},
    "concept": {"concept": 3, "topic": 2, "source": 1},
}
WIKI_SECTION_DIRS = {"concepts", "topics", "sources", "syntheses", "queries", "decisions"}
BLOCKED_SECTIONS = {
    "Connections",
    "Related Pages",
    "Open Questions",
    "Consulted Pages",
    "Sources",
    "Raw Source",
    "Extracted Markdown",
    "Extracted Excerpt",
}
META_PREFIXES = ("来源：", "作者：", "发布日期：", "原文链接：")
LOW_VALUE_LINE_HINTS = (
    "本报告旨在回答",
    "研究问题",
    "副院长",
    "资深专家",
    "日期：",
    "日期:",
    "page ",
)
DEFINITION_HINTS = ("定义为", "本质上是", "指的是", "意味着", "可概括为")
DECISION_HINTS = ("不适合", "应按", "应采用", "建议", "推荐", "换句话说", "关键在于", "核心判断")
STRATEGY_HINTS = ("缓解策略", "首要评判标准", "产品管理思维", "开发者体验（DevEx）", "开发者体验(DevEx)")
ROLE_HINTS = ("典型角色包括", "职责包括", "角色包括")
SYNTHESIS_HINTS = ("这意味着", "因此", "换句话说", "核心判断", "说明", "首先是一种", "本质上是")
ORGANIZATION_HINTS = ("团队", "组织", "平台", "协作", "运行机制", "交付系统")
CONTINUATION_ENDINGS = tuple("的了和与及并而按把将向在于为是小会度案等其")


def first_meaningful_line(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:140]
    return fallback


def bullet_block(items: list[str], fallback: str) -> str:
    values = [item.strip() for item in items if item.strip()]
    if not values:
        return fallback
    return "\n".join(f"- {item}" for item in values)


def ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def text_tokens(text: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower()):
        if raw.isascii() and len(raw) <= 1:
            continue
        tokens.add(raw)
    return tokens


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())


def plain_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[\d+\]\]\([^)]+\)", "", text)
    text = re.sub(r"\[\[\d+\]\]\(?", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`~#>]+", " ", text)
    return normalize_text(text).strip(" -|,;")


def short_text(text: str, limit: int = 180) -> str:
    value = plain_text(text)
    if len(value) <= limit:
        return value
    window = value[: limit - 1]
    cut = max(window.rfind("。"), window.rfind("；"), window.rfind("."), window.rfind(";"), window.rfind(" "))
    if cut >= max(20, limit // 3):
        window = window[:cut]
    return window.rstrip() + "…"


def cleaned_line(raw: str) -> str:
    return raw.strip().lstrip("-* ").strip()


def looks_like_placeholder(text: str) -> bool:
    compact = normalize_text(text).lower()
    if not compact:
        return True
    return compact in {"none yet", "todo", "- todo", "(no summary)"}


def is_metadata_line(text: str) -> bool:
    return cleaned_line(text).startswith(META_PREFIXES)


def is_link_only(text: str) -> bool:
    clean = cleaned_line(text)
    if clean.startswith(("http://", "https://", "<http://", "<https://")):
        return True
    return bool(re.fullmatch(r"\d+\.\s*https?://\S+", clean))


def is_image_only(text: str) -> bool:
    clean = cleaned_line(text)
    return clean.startswith("![](") and clean.endswith(")")


def low_value_summary(text: str) -> bool:
    clean = plain_text(text)
    if not clean:
        return True
    if is_metadata_line(clean) or is_link_only(clean) or is_image_only(clean):
        return True
    return clean.startswith("以下为") or any(hint in clean.lower() for hint in LOW_VALUE_LINE_HINTS)


def split_sentences(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    merged_lines: list[str] = []
    buffer = ""
    for raw in normalized.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if not buffer:
            buffer = line
            continue
        if buffer.endswith(("。", "！", "？", ".", "!", "?", "；", ";", "：", ":")):
            merged_lines.append(buffer.strip())
            buffer = line
            continue
        if re.match(r"^(?:[-*]|\d+[.)、])\s*", line):
            merged_lines.append(buffer.strip())
            buffer = line
            continue
        buffer = f"{buffer} {line}"
    if buffer:
        merged_lines.append(buffer.strip())

    parts: list[str] = []
    for chunk in merged_lines:
        parts.extend(re.split(r"(?<=[。！？!?\.])\s+", chunk))
    return [part.strip(" -") for part in parts if part.strip(" -")]


def looks_incomplete_sentence(text: str) -> bool:
    clean = plain_text(text)
    if not clean:
        return True
    if clean.endswith(("。", "！", "？", ".", "!", "?")):
        return False
    if clean.endswith(("…", "；", ";", "：", ":")):
        return True
    if clean[-1] in CONTINUATION_ENDINGS:
        return True
    if len(clean) < 30:
        return True
    return False


def is_low_value_sentence(text: str) -> bool:
    clean = plain_text(text)
    lowered = clean.lower()
    if len(clean) < 12:
        return True
    if looks_like_placeholder(clean):
        return True
    if is_metadata_line(clean) or is_link_only(clean) or is_image_only(clean):
        return True
    if any(hint in lowered for hint in LOW_VALUE_LINE_HINTS):
        return True
    if clean.endswith(("：", ":")):
        return True
    return False


def sentence_priority(text: str) -> int:
    clean = plain_text(text)
    score = 0
    if any(hint in clean for hint in DEFINITION_HINTS):
        score += 8
    if any(hint in clean for hint in DECISION_HINTS):
        score += 7
    if "定义为" in clean:
        score += 8
    if "不适合" in clean or "应采用" in clean or "推荐采用" in clean:
        score += 10
    if "本质上是" in clean:
        score += 4
    if "指的是" in clean:
        score += 2
    if len(clean) >= 30:
        score += 2
    if len(clean) >= 80:
        score += 2
    if len(clean) > 200:
        score -= 2
    if "？" in clean or "?" in clean:
        score -= 6
    return score


def summary_candidate_score(text: str) -> int:
    clean = plain_text(text)
    score = sentence_priority(clean)
    if len(clean) < 24:
        score -= 6
    elif len(clean) <= 140:
        score += 4
    elif len(clean) <= 220:
        score += 1
    else:
        score -= 4
    has_terminal_punctuation = clean.endswith(("。", "！", "？", ".", "!", "?"))
    if has_terminal_punctuation:
        score += 4
    else:
        score -= 14
    if clean.endswith(("…", "；", ";", "：", ":")):
        score -= 6
    if clean and clean[-1] in CONTINUATION_ENDINGS:
        score -= 30
    if re.search(r"\d+$", clean):
        score -= 4
    return score


def kind_summary_score(text: str, kind: str, title: str = "") -> int:
    clean = plain_text(text)
    score = summary_candidate_score(clean)
    normalized_kind = kind.strip().lower()
    title_clean = plain_text(title)

    if normalized_kind == "concept":
        if any(hint in clean for hint in DEFINITION_HINTS):
            score += 18
        if "首先是一种" in clean or "可一句话概括" in clean:
            score += 10
        if "关键不在于" in clean or "围绕可执行规格" in clean:
            score += 10
        if "软件交付团队" in clean or "其关键不在于" in clean:
            score += 12
        if title_clean and (clean.startswith(title_clean) or clean.startswith(f"{title_clean}（")):
            score += 14
        if title_clean and title_clean in clean and any(
            hint in clean for hint in ("定义为", "本质上是", "指的是", "意味着", "首先是一种")
        ):
            score += 8
        if clean.startswith("本报告不将") or "并列的独立概念来讨论" in clean:
            score -= 24
        if "而不是另一套平行的方法论" in clean:
            score -= 10
        if "本报告" in clean and ("系统论证" in clean or "应运而生" in clean):
            score -= 16
        if any(hint in clean for hint in STRATEGY_HINTS):
            score -= 20
        if any(hint in clean for hint in ROLE_HINTS):
            score -= 10
        if "团队应" in clean or "建议" in clean:
            score -= 8
    elif normalized_kind == "decision":
        if any(hint in clean for hint in DECISION_HINTS):
            score += 18
        if "不适合" in clean or "应按" in clean or "应采用" in clean or "推荐采用" in clean:
            score += 14
        if any(hint in clean for hint in DEFINITION_HINTS):
            score -= 6
        if clean.startswith(("缓解策略", "建议采用")) and "不适合" not in clean and "应按" not in clean:
            score -= 12
    else:
        if any(hint in clean for hint in SYNTHESIS_HINTS):
            score += 12
        if any(hint in clean for hint in DEFINITION_HINTS):
            score += 8
        if any(hint in clean for hint in DECISION_HINTS):
            score += 8
        if "首先是一种组织模式" in clean or "组织模式而非工具清单" in clean:
            score += 16
        if "关键不在于" in clean and "团队是否" in clean:
            score += 10
        if "不能只理解为" in clean or "真正难点并不在于" in clean:
            score += 12
        if clean.startswith("本报告不将") or "并列的独立概念来讨论" in clean:
            score -= 20
        if "而不是另一套平行的方法论" in clean:
            score -= 10
        if any(hint in clean for hint in STRATEGY_HINTS):
            score -= 18
        if any(hint in clean for hint in ROLE_HINTS):
            score -= 10
        if any(hint in clean for hint in ORGANIZATION_HINTS):
            score += 4
        if "团队应" in clean or "建议采用" in clean:
            score -= 8
        if len(clean) > 180:
            score -= 12
        if len(clean) > 240:
            score -= 10
        if clean.count("。") >= 3:
            score -= 6

    if clean.count("；") + clean.count(";") >= 2:
        score -= 4
    return score


def summary_sentence_candidates(text: str, summary_kind: str, title: str, limit: int = 12) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    for index, part in enumerate(split_sentences(text)):
        clean = plain_text(part).strip(" -")
        if clean.startswith("#") or is_low_value_sentence(clean):
            continue
        candidates.append((kind_summary_score(clean, summary_kind, title), index, clean))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[2] for item in candidates[:limit]]


def choose_best_summary(summary: str, primary_body: str, title: str, summary_kind: str = "concept") -> str:
    candidates: list[str] = []
    summary_clean = plain_text(summary)
    if summary_clean and not low_value_summary(summary_clean):
        candidates.append(summary_clean)
    candidates.extend(summary_sentence_candidates(primary_body, summary_kind, title, limit=12))
    candidates = ordered_unique(candidates)
    if not candidates:
        return title
    scored = sorted(
        ((kind_summary_score(candidate, summary_kind, title), index, candidate) for index, candidate in enumerate(candidates)),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    return scored[0][2]


def meaningful_sentences(text: str, limit: int = 8) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    for index, part in enumerate(split_sentences(text)):
        clean = plain_text(part).strip(" -")
        if clean.startswith("#") or is_low_value_sentence(clean):
            continue
        if looks_incomplete_sentence(clean):
            continue
        candidates.append((sentence_priority(clean), index, clean))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[2] for item in candidates[:limit]]


def extract_title_from_body(body: str, fallback: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def section_bullets(sections: dict[str, str], name: str) -> list[str]:
    result: list[str] = []
    for line in sections.get(name, "").splitlines():
        clean = line.strip()
        if clean.startswith("- "):
            result.append(clean[2:].strip())
    return result


def section_targets(sections: dict[str, str], name: str) -> list[str]:
    return [item for item in markdown_links(sections.get(name, "")) if item]


def normalize_section_targets(page_path: Path, root: Path, targets: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in targets:
        clean = value.strip()
        if not clean:
            continue
        if clean.startswith(("http://", "https://", "mailto:", "#")):
            normalized.append(clean)
            continue
        candidate = Path(clean)
        if candidate.is_absolute():
            normalized.append(normalize_repo_path(root, clean))
            continue
        resolved = (page_path.parent / candidate).resolve()
        try:
            repo_relative = resolved.relative_to(root.resolve()).as_posix()
            repo_path = Path(repo_relative)
            if repo_path.parts and repo_path.parts[0] in WIKI_SECTION_DIRS:
                normalized.append(Path("wiki", repo_relative).as_posix())
            else:
                normalized.append(repo_relative)
        except ValueError:
            parts = [part for part in candidate.parts if part not in {"", ".", ".."}]
            section_index = next((index for index, part in enumerate(parts) if part in WIKI_SECTION_DIRS), -1)
            if section_index >= 0:
                normalized.append(Path("wiki", *parts[section_index:]).as_posix())
            else:
                normalized.append(normalize_repo_path(root, clean))
    return ordered_unique(normalized)


def resolve_input_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    normalized = normalize_repo_path(root, value)
    return root / normalized


def source_page_companion(root: Path, page_path: Path) -> Path | None:
    if page_path.parent.name != "sources":
        return None
    text = read_text(page_path)
    meta, _body = parse_frontmatter(text)
    source_values = meta.get("sources", [])
    if not isinstance(source_values, list) or not source_values:
        return None
    raw_path = Path(str(source_values[0]))
    if len(raw_path.parts) < 3 or raw_path.parts[0] != "raw":
        return None
    normalized_path = root / Path("normalized", *raw_path.parts[1:]).with_suffix(".md")
    if normalized_path.exists():
        return normalized_path
    return None


def collect_related_paths(root: Path, body: str, page_path: Path) -> list[str]:
    related: list[str] = []
    for match in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
        if match.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = (page_path.parent / match).resolve()
        try:
            related.append(target.relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    return ordered_unique([item for item in related if item.startswith("wiki/") and item.endswith(".md")])


def source_record(root: Path, raw_path: Path, summary_kind: str = "concept", summary_focus: str = "") -> dict[str, object]:
    text = read_text(raw_path)
    if not text:
        raise SystemExit(f"Cannot read source content: {raw_path}")

    if raw_path.suffix.lower() == ".md" and "wiki" in raw_path.parts:
        meta, body = parse_frontmatter(text)
        title = str(meta.get("title") or raw_path.stem)
        summary = str(meta.get("summary") or "").strip()
        source_values = meta.get("sources", [])
        source_paths = [normalize_repo_path(root, str(item)) for item in source_values] if isinstance(source_values, list) else []
        related_paths = collect_related_paths(root, body, raw_path)
        companion = source_page_companion(root, raw_path)
        primary_body = read_text(companion) if companion else body
    else:
        title = extract_title_from_body(text, raw_path.stem)
        summary = ""
        primary_body = text
        source_paths = [raw_path.relative_to(root).as_posix()] if raw_path.is_relative_to(root) else []
        related_paths = []

    sections = extract_sections(primary_body)
    bullets: list[tuple[int, str]] = []
    for section_name, section_body in sections.items():
        if section_name in BLOCKED_SECTIONS:
            continue
        for raw_line in meaningful_sentences(section_body, limit=6):
            clean = cleaned_line(raw_line)
            if clean.startswith("#") or is_low_value_sentence(clean):
                continue
            bullets.append((sentence_priority(clean), clean))

    sentences = meaningful_sentences(primary_body, limit=10)
    summary_title = summary_focus.strip() or title
    summary = short_text(choose_best_summary(summary, primary_body, summary_title, summary_kind))
    return {
        "path": raw_path,
        "title": title,
        "summary": summary,
        "source_paths": ordered_unique(source_paths),
        "related_paths": ordered_unique(related_paths),
        "snippets": ordered_unique([item for _score, item in sorted(bullets, key=lambda value: (-value[0], value[1]))] + sentences),
    }


def auto_summary(records: list[dict[str, object]], fallback: str, summary_kind: str = "concept") -> str:
    parts = ordered_unique([str(record["summary"]).strip() for record in records if str(record["summary"]).strip()])
    if not parts:
        return fallback
    if len(parts) == 1:
        return short_text(parts[0], limit=220)
    ranked = sorted(
        ((kind_summary_score(part, summary_kind, fallback), index, part) for index, part in enumerate(parts)),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    lead = ranked[0][2]
    support = next((part for _score, _index, part in ranked[1:] if part != lead), "")
    if support:
        return short_text(f"{lead} 这一判断也得到其他来源的支持，说明相关结论并非单点材料中的孤立观点。", limit=220)
    return short_text(lead, limit=220)


def auto_key_points(records: list[dict[str, object]], limit: int = 5) -> list[str]:
    items: list[str] = []
    for record in records:
        title = str(record["title"])
        for snippet in list(record["snippets"])[:3]:
            items.append(f"{title}: {snippet}")
            if len(items) >= limit:
                return ordered_unique(items)
    return ordered_unique(items)


def auto_body(records: list[dict[str, object]], kind: str, summary: str) -> str:
    points = auto_key_points(records, limit=4)
    if kind == "decision":
        return "\n".join(f"- {item}" for item in points) if points else summary.strip()
    if kind == "concept":
        lines = [summary.strip()]
        if points:
            lines.extend(["", *[f"- {item}" for item in points]])
        return "\n".join(lines).strip()
    if kind == "query":
        lines = [summary.strip()]
        if points:
            lines.extend(["", *[f"- {item}" for item in points]])
        return "\n".join(lines).strip()
    return "\n".join(f"- {item}" for item in points) if points else summary.strip()


def update_frontmatter_field(text: str, key: str, value: str) -> str:
    prefix = f"{key}: "
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text


def merge_text_mode(existing: str, incoming: str, fallback: str, merge_mode: str) -> str:
    current = existing.strip()
    new_value = incoming.strip()
    if merge_mode == "replace":
        if new_value:
            return new_value
        if current:
            return current
        return fallback
    if merge_mode == "append":
        if current and new_value:
            return f"{current}\n\n{new_value}"
        if current:
            return current
        if new_value:
            return new_value
        return fallback
    if current and new_value:
        if new_value in current:
            return current
        return f"{current}\n\n{new_value}"
    if current:
        return current
    if new_value:
        return new_value
    return fallback


def merge_list_mode(existing: list[str], incoming: list[str], merge_mode: str, fallback: list[str] | None = None) -> list[str]:
    fallback = fallback or []
    if merge_mode == "replace":
        merged = [item for item in incoming if item.strip()] or [item for item in existing if item.strip()] or fallback
        return merged
    if merge_mode == "append":
        merged = [item for item in existing if item.strip()] + [item for item in incoming if item.strip()]
        return merged or fallback
    merged = ordered_unique([item for item in existing if item.strip()] + [item for item in incoming if item.strip()])
    return merged or fallback


def build_page_values(
    root: Path,
    page_path: Path,
    kind: str,
    title: str,
    summary: str,
    content: str,
    source_paths: list[str],
    related_paths: list[str],
    follow_ups: list[str],
    findings: list[str],
    tensions: list[str],
    key_points: list[str],
    merge_mode: str,
) -> tuple[dict[str, str], str, str]:
    existing_text = read_text(page_path)
    meta, body = parse_frontmatter(existing_text)
    sections = extract_sections(body) if existing_text else {}

    created = str(meta.get("created") or today_str())
    existing_sources = [str(item) for item in meta.get("sources", [])]
    incoming_sources = [normalize_repo_path(root, value) for value in source_paths]
    normalized_sources = merge_list_mode(existing_sources, incoming_sources, merge_mode, ["log.md"])
    self_path = page_path.relative_to(root).as_posix()

    related_section = "Connections" if kind == "concept" else "Related Pages"
    normalized_related = merge_list_mode(
        normalize_section_targets(page_path, root, section_targets(sections, related_section)),
        [normalize_repo_path(root, value) for value in related_paths],
        merge_mode,
    )
    normalized_related = [item for item in normalized_related if item != self_path]
    summary_input = summary.strip()
    if merge_mode == "replace":
        summary_value = summary_input or str(meta.get("summary") or "") or first_meaningful_line(content, title)
    else:
        summary_value = summary_input or str(meta.get("summary") or "") or first_meaningful_line(content, title)

    consulted_targets = merge_list_mode(
        normalize_section_targets(page_path, root, section_targets(sections, "Consulted Pages")),
        normalized_sources,
        "dedupe",
        ["index.md"],
    )
    consulted_targets = [item for item in consulted_targets if item != self_path]
    follow_up_values = merge_list_mode(section_bullets(sections, "Follow-ups"), follow_ups, merge_mode)
    finding_values = merge_list_mode(section_bullets(sections, "Findings"), findings, merge_mode)
    tension_values = merge_list_mode(section_bullets(sections, "Tensions"), tensions, merge_mode)
    key_point_values = merge_list_mode(section_bullets(sections, "Key Points"), key_points, merge_mode)

    values = {
        "TITLE": title,
        "DATE": created,
        "UPDATED": today_str(),
        "SUMMARY": summary_value,
        "SOURCE_ITEMS": frontmatter_list(normalized_sources, "log.md"),
        "SOURCE_LINKS": markdown_link_list(page_path, root, normalized_sources),
        "RELATED_LINKS": markdown_link_list(page_path, root, normalized_related),
        "ANSWER": merge_text_mode(sections.get("Answer", ""), content, summary_value, merge_mode),
        "CONSULTED_LINKS": markdown_link_list(page_path, root, consulted_targets),
        "FOLLOW_UPS": bullet_block(follow_up_values, ""),
        "FINDINGS": bullet_block(
            finding_values,
            content.strip() or sections.get("Findings", "").strip(),
        ),
        "TENSIONS": bullet_block(tension_values, ""),
        "REASONING": merge_text_mode(sections.get("Reasoning", ""), content, "", merge_mode),
        "KEY_POINTS": bullet_block(key_point_values, ""),
        "DETAILS": merge_text_mode(sections.get("Details", ""), content, "", merge_mode),
    }

    if kind == "synthesis":
        values["FINDINGS"] = bullet_block(
            finding_values,
            content.strip() or sections.get("Findings", "").strip(),
        )
    if kind == "decision":
        values["REASONING"] = merge_text_mode(sections.get("Reasoning", ""), content, "", merge_mode)
    if kind == "concept":
        values["DETAILS"] = merge_text_mode(sections.get("Details", ""), content, "", merge_mode)
    if kind == "query":
        values["ANSWER"] = merge_text_mode(sections.get("Answer", ""), content, summary_value, merge_mode)

    if kind in {"synthesis", "concept"}:
        values["SUMMARY"] = summary_value
    if kind == "decision":
        values["SUMMARY"] = summary_value

    action = "updated" if existing_text else "created"
    return values, created, action


def find_existing_page(root: Path, kind: str, title: str, slug: str) -> Path | None:
    page_dir = root / "wiki" / PAGE_TYPE_TO_DIR[kind]
    candidate = page_dir / f"{slugify(slug or title, kind)}.md"
    if candidate.exists():
        return candidate

    target_title = title.strip()
    if not target_title:
        return None
    for page in sorted(page_dir.glob("*.md")):
        meta, _body = parse_frontmatter(read_text(page))
        if str(meta.get("title") or "").strip() == target_title:
            return page
    return None


def resolve_page_path(root: Path, kind: str, title: str, slug: str, update: bool) -> Path:
    page_dir = PAGE_TYPE_TO_DIR[kind]
    base = root / "wiki" / page_dir / f"{slugify(slug or title, kind)}.md"
    if update:
        return find_existing_page(root, kind, title, slug) or base
    return unique_path(base)


def backlink_section_name(page_text: str, page_type: str) -> str:
    body = parse_frontmatter(page_text)[1]
    sections = extract_sections(body)
    if "Connections" in sections:
        return "Connections"
    if "Related Pages" in sections:
        return "Related Pages"
    if page_type == "source":
        return "Connections"
    return "Related Pages"


def append_backlink(page_path: Path, root: Path, new_page_path: Path, new_page_title: str) -> bool:
    if not page_path.exists() or page_path.resolve() == new_page_path.resolve():
        return False

    page_text = read_text(page_path)
    if not page_text:
        return False

    meta, body = parse_frontmatter(page_text)
    page_type = str(meta.get("type") or page_path.parent.name[:-1])
    section_name = backlink_section_name(page_text, page_type)
    link_line = f"- [{new_page_title}]({relative_link(page_path, root, new_page_path.relative_to(root).as_posix())})"
    if link_line in body:
        return False

    marker = f"## {section_name}\n"
    if marker in page_text:
        head, tail = page_text.split(marker, 1)
        tail_lines = tail.splitlines()
        insert_at = 0
        while insert_at < len(tail_lines) and not tail_lines[insert_at].startswith("## "):
            insert_at += 1
        section_block = tail_lines[:insert_at]
        while section_block and not section_block[-1].strip():
            section_block.pop()
        if section_block:
            section_block.extend(["", link_line, ""])
        else:
            section_block = ["", link_line, ""]
        updated_tail_lines = section_block + tail_lines[insert_at:]
        updated_text = head + marker + "\n".join(updated_tail_lines).rstrip() + "\n"
    else:
        updated_text = page_text.rstrip() + f"\n\n## {section_name}\n\n{link_line}\n"

    updated_text = update_frontmatter_field(updated_text, "updated", today_str())
    write_text(page_path, updated_text)
    return True


def backlink_targets(root: Path, source_paths: list[str], related_paths: list[str]) -> list[Path]:
    targets: list[Path] = []
    for raw in source_paths + related_paths:
        normalized = normalize_repo_path(root, raw)
        if normalized.startswith("wiki/") and normalized.endswith(".md"):
            target = root / normalized
            if target.exists():
                targets.append(target)
            continue
        if normalized.startswith(("raw/", "normalized/")):
            companion = source_page_for_material(root, normalized)
            if companion is not None:
                targets.append(companion)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for item in targets:
        resolved = item.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(item)
    return deduped


def source_page_for_material(root: Path, material_path: str) -> Path | None:
    normalized_material = normalize_repo_path(root, material_path)
    if not normalized_material.startswith(("raw/", "normalized/")):
        return None
    for page in sorted((root / "wiki" / "sources").glob("*.md")):
        meta, _body = parse_frontmatter(read_text(page))
        source_values = meta.get("sources", [])
        if not isinstance(source_values, list):
            continue
        page_source = normalize_repo_path(root, str(source_values[0])) if source_values else ""
        if page_source == normalized_material:
            return page
        if page_source.startswith("raw/") and normalized_material.startswith("normalized/"):
            raw_path = Path(page_source)
            companion = Path("normalized", *raw_path.parts[1:]).with_suffix(".md").as_posix()
            if companion == normalized_material:
                return page
        if page_source.startswith("raw/") and normalized_material.startswith("raw/") and page_source == normalized_material:
            return page
    return None


def infer_anchor_paths(
    root: Path,
    kind: str,
    title: str,
    summary: str,
    content: str,
    page_path: Path,
    limit: int = 2,
) -> list[str]:
    query_tokens = text_tokens(" ".join([title, summary, content]))
    if not query_tokens:
        query_tokens = text_tokens(title)

    scored: list[tuple[int, str]] = []
    for candidate in collect_wiki_pages(root):
        if candidate.resolve() == page_path.resolve():
            continue
        meta, body = parse_frontmatter(read_text(candidate))
        candidate_type = str(meta.get("type") or candidate.parent.name[:-1])
        candidate_title = str(meta.get("title") or candidate.stem)
        candidate_summary = extract_summary(meta, body)
        candidate_tokens = text_tokens(" ".join([candidate_title, candidate_summary, candidate.stem]))
        overlap = query_tokens.intersection(candidate_tokens)
        score = len(overlap) * 10 + TYPE_BONUS_BY_KIND.get(kind, {}).get(candidate_type, 0)
        if score <= 0:
            continue
        scored.append((score, candidate.relative_to(root).as_posix()))

    if not scored:
        fallback_order = ("topics", "concepts", "sources", "entities", "decisions", "queries", "syntheses")
        grouped: dict[str, list[str]] = {}
        for path in collect_wiki_pages(root):
            if path.resolve() == page_path.resolve():
                continue
            grouped.setdefault(path.parent.name, []).append(path.relative_to(root).as_posix())
        for directory in fallback_order:
            if grouped.get(directory):
                return [sorted(grouped[directory])[0]]
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [path for _score, path in scored[:limit]]


def create_page(
    root: Path,
    kind: str,
    title: str,
    summary: str,
    content: str,
    source_paths: list[str],
    related_paths: list[str],
    follow_ups: list[str],
    findings: list[str],
    tensions: list[str],
    key_points: list[str],
    action_label: str = "crystallize",
    confidence: str = "",
    status: str = "",
) -> tuple[Path, str]:
    return write_page(
        root=root,
        kind=kind,
        title=title,
        summary=summary,
        content=content,
        source_paths=source_paths,
        related_paths=related_paths,
        follow_ups=follow_ups,
        findings=findings,
        tensions=tensions,
        key_points=key_points,
        action_label=action_label,
        confidence=confidence,
        status=status,
    )


def write_page(
    root: Path,
    kind: str,
    title: str,
    summary: str,
    content: str,
    source_paths: list[str],
    related_paths: list[str],
    follow_ups: list[str],
    findings: list[str],
    tensions: list[str],
    key_points: list[str],
    action_label: str = "crystallize",
    slug: str = "",
    update: bool = False,
    merge_mode: str = "dedupe",
    confidence: str = "",
    status: str = "",
) -> tuple[Path, str]:
    page_path = resolve_page_path(root, kind, title, slug, update)
    values, _created, action = build_page_values(
        root=root,
        page_path=page_path,
        kind=kind,
        title=title,
        summary=summary,
        content=content,
        source_paths=source_paths,
        related_paths=related_paths,
        follow_ups=follow_ups,
        findings=findings,
        tensions=tensions,
        key_points=key_points,
        merge_mode=merge_mode,
    )
    rendered = render_template(load_template(TEMPLATE_BY_KIND[kind]), values).replace("{{UPDATED}}", today_str())
    if confidence.strip():
        rendered = update_frontmatter_field(rendered, "confidence", confidence.strip())
    if status.strip():
        rendered = update_frontmatter_field(rendered, "status", status.strip())
    write_text(page_path, rendered)
    linked_back = []
    for target_path in backlink_targets(root, source_paths, related_paths):
        if append_backlink(target_path, root, page_path, title):
            linked_back.append(target_path.relative_to(root).as_posix())
    write_text(root / "index.md", rebuild_index.build_index(root))
    log_lines = [
        f"- {action}: {page_path.relative_to(root).as_posix()}",
        f"- sources: {', '.join([normalize_repo_path(root, value) for value in source_paths] or ['log.md'])}",
    ]
    log_lines.extend(f"- backlink: {item}" for item in linked_back)
    append_log(root, f"[{today_str()}] {action_label}:{kind} | {title}", log_lines)
    return page_path, action


def main() -> int:
    parser = argparse.ArgumentParser(description="Crystallize structured knowledge into a wiki page.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--kind", required=True, choices=sorted(TEMPLATE_BY_KIND), help="Target page type")
    parser.add_argument("--title", required=True, help="Page title")
    parser.add_argument("--summary", default="", help="Short summary stored in frontmatter")
    parser.add_argument("--content", default="", help="Main body content for the page")
    parser.add_argument("--source-path", action="append", default=[], help="Root-relative or absolute source page path")
    parser.add_argument("--related-path", action="append", default=[], help="Related wiki page path")
    parser.add_argument("--follow-up", action="append", default=[], help="Follow-up item for query pages")
    parser.add_argument("--finding", action="append", default=[], help="Finding item for synthesis pages")
    parser.add_argument("--tension", action="append", default=[], help="Tension item for synthesis pages")
    parser.add_argument("--key-point", action="append", default=[], help="Key point for concept pages")
    parser.add_argument("--slug", default="", help="Explicit target slug")
    parser.add_argument("--update", action="store_true", help="Update an existing page with the same title or slug")
    parser.add_argument("--merge-mode", choices=list(MERGE_MODES), default="dedupe", help="How to merge fields when --update is used")
    parser.add_argument("--confidence", default="", help="Optional confidence override for the target page")
    parser.add_argument("--status", default="", help="Optional status override for the target page")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    records: list[dict[str, object]] = []
    for raw in args.source_path:
        path = resolve_input_path(root, raw)
        if not path.exists():
            raise SystemExit(f"Source path not found: {raw}")
        records.append(source_record(root, path, summary_kind=args.kind, summary_focus=args.title))

    auto_source_paths = ordered_unique([
        source_path
        for record in records
        for source_path in list(record["source_paths"]) or ([Path(record["path"]).relative_to(root).as_posix()] if Path(record["path"]).is_relative_to(root) else [])
    ])
    auto_related_paths = ordered_unique([item for record in records for item in list(record["related_paths"])])
    auto_summary_text = auto_summary(records, first_meaningful_line(args.content, args.title), summary_kind=args.kind)
    auto_points = auto_key_points(records)
    auto_content = auto_body(records, args.kind, auto_summary_text)

    summary = args.summary.strip() or auto_summary_text
    content = args.content.strip() or auto_content
    related_paths = ordered_unique(args.related_path + auto_related_paths)
    source_paths = ordered_unique(args.source_path + auto_source_paths)
    key_points = ordered_unique(args.key_point + auto_points) if args.kind == "concept" else args.key_point
    findings = ordered_unique(args.finding + auto_points) if args.kind == "synthesis" else args.finding
    tensions = args.tension
    page_path, action = write_page(
        root=root,
        kind=args.kind,
        title=args.title,
        summary=summary,
        content=content,
        source_paths=source_paths,
        related_paths=related_paths,
        follow_ups=args.follow_up,
        findings=findings,
        tensions=tensions,
        key_points=key_points,
        action_label="crystallize",
        slug=args.slug,
        update=args.update,
        merge_mode=args.merge_mode,
        confidence=args.confidence,
        status=args.status,
    )
    output_home = refresh_output_home_if_present(root)
    print(f"{action.title()} {page_path.relative_to(root).as_posix()}")
    if output_home is not None:
        print("Output hub: output/index.html")
        print(f"Output hub URI: {file_uri(output_home)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
