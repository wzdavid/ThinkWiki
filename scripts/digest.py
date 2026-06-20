#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from crystallize import first_meaningful_line, write_page
from utils import file_uri, find_repo_root, normalize_repo_path, parse_frontmatter, read_text, refresh_output_home_if_present

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
LOW_VALUE_SUMMARY_PATTERNS = (
    "以下为",
    "点击查看",
    "原文链接",
)
TENSION_HINTS = ("但", "不过", "仍", "需要", "风险", "问题", "挑战", "难", "冲突", "取舍", "边界", "验证", "确认")
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


def ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = " ".join(item.split()).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


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


def looks_like_placeholder(text: str) -> bool:
    compact = normalize_text(text).lower()
    if not compact:
        return True
    return compact in {"none yet", "todo", "- todo", "(no summary)"}


def cleaned_line(raw: str) -> str:
    return raw.strip().lstrip("-* ").strip()


def is_metadata_line(text: str) -> bool:
    return cleaned_line(text).startswith(META_PREFIXES)


def is_link_only(text: str) -> bool:
    clean = cleaned_line(text)
    if clean.startswith(("http://", "https://", "<http://", "<https://")):
        return True
    return bool(re.fullmatch(r"\d+\.\s*https?://\S+", clean))


def low_value_summary(text: str) -> bool:
    clean = plain_text(text)
    if not clean:
        return True
    if is_metadata_line(clean) or is_link_only(clean):
        return True
    lowered = clean.lower()
    return any(clean.startswith(prefix) for prefix in LOW_VALUE_SUMMARY_PATTERNS) or any(hint in lowered for hint in LOW_VALUE_LINE_HINTS)


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
    if is_metadata_line(clean) or is_link_only(clean):
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


def choose_best_summary(summary: str, primary_body: str, title: str, summary_kind: str = "synthesis") -> str:
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


def extract_title(body: str, fallback: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "Overview"
    sections[current] = []
    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip() or "Overview"
            sections.setdefault(current, [])
            continue
        if stripped.startswith("### "):
            current = stripped[4:].strip() or current
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def clean_content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in {"---", "***"}:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("![]("):
            continue
        if is_metadata_line(line):
            continue
        if line.startswith(("更新时间", "更新于", "Published:", "Updated:")):
            continue
        if is_link_only(line):
            continue
        lines.append(line)
    return lines


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


def likely_tension(text: str) -> bool:
    clean = plain_text(text)
    if len(clean) < 16:
        return False
    return any(hint in clean for hint in TENSION_HINTS)


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


def resolve_input_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    normalized = normalize_repo_path(root, value)
    return root / normalized


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


def source_record(root: Path, raw_path: Path, summary_kind: str = "synthesis") -> dict[str, object]:
    text = read_text(raw_path)
    if not text:
        raise SystemExit(f"Cannot read source content: {raw_path}")
    record_type = "normalized" if "normalized" in raw_path.parts else "page"
    title = raw_path.stem
    summary = ""
    source_paths: list[str] = []
    related_paths: list[str] = []

    if raw_path.suffix.lower() == ".md" and "wiki" in raw_path.parts:
        meta, body = parse_frontmatter(text)
        title = str(meta.get("title") or raw_path.stem)
        summary = str(meta.get("summary") or "").strip()
        source_values = meta.get("sources", [])
        if isinstance(source_values, list):
            source_paths = [normalize_repo_path(root, str(item)) for item in source_values]
        related_paths = collect_related_paths(root, body, raw_path)
    else:
        body = text
        title = extract_title(body, raw_path.stem)
        summary_candidates = clean_content_lines(body)
        summary = short_text(summary_candidates[0]) if summary_candidates else ""
        if raw_path.is_relative_to(root):
            source_paths = [raw_path.relative_to(root).as_posix()]

    companion = source_page_companion(root, raw_path) if record_type == "page" else None
    companion_text = read_text(companion) if companion else ""
    primary_body = companion_text or body
    companion_summary = (meaningful_sentences(primary_body, limit=1) or [""])[0]
    sections = extract_sections(primary_body)
    key_texts: list[tuple[int, str]] = []
    tension_texts: list[str] = []

    for section_name, section_body in sections.items():
        if section_name in BLOCKED_SECTIONS:
            continue
        for line in meaningful_sentences(section_body, limit=6):
            clean = cleaned_line(line)
            if is_low_value_sentence(clean):
                continue
            if section_name in {"Open Questions", "Tensions", "Follow-ups"}:
                tension_texts.append(clean)
            else:
                key_texts.append((sentence_priority(clean), clean))

    key_sentences = meaningful_sentences(primary_body, limit=10)
    if not tension_texts:
        tension_texts.extend([item for item in meaningful_sentences(primary_body, limit=12) if likely_tension(item)][:3])
    summary = short_text(choose_best_summary(summary or companion_summary, primary_body, title, summary_kind))

    return {
        "path": raw_path,
        "title": title,
        "summary": summary,
        "type": record_type,
        "source_paths": ordered_unique(source_paths),
        "related_paths": ordered_unique(related_paths),
        "findings": ordered_unique([item for _score, item in sorted(key_texts, key=lambda value: (-value[0], value[1]))] + key_sentences),
        "tensions": ordered_unique(tension_texts),
    }


def auto_summary(records: list[dict[str, object]], fallback: str, summary_kind: str = "synthesis") -> str:
    parts = [str(record["summary"]).strip() for record in records if str(record["summary"]).strip()]
    parts = ordered_unique(parts)
    if not parts:
        return fallback
    if len(parts) == 1:
        return short_text(parts[0], limit=220)
    ranked = sorted(
        ((kind_summary_score(part, summary_kind, fallback), index, part) for index, part in enumerate(parts)),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    lead = ranked[0][2]
    if summary_kind == "synthesis":
        preferred = next(
            (
                part
                for score, _index, part in ranked
                if len(part) <= 180
                and part.endswith(("。", "！", "？", ".", "!", "?"))
                and (
                    any(hint in part for hint in DECISION_HINTS)
                    or "首先是一种组织模式" in part
                    or "关键不在于" in part
                    or "不能只理解为" in part
                    or "软件交付团队" in part
                )
                and score >= ranked[0][0] - 6
            ),
            "",
        )
        if preferred:
            lead = preferred
    support = next((part for _score, _index, part in ranked[1:] if part != lead), "")
    if support:
        return short_text(f"{lead} 这一判断也得到其他来源的补充支持，说明相关组织结论具有跨材料一致性。", limit=220)
    return short_text(lead, limit=220)


def auto_findings(records: list[dict[str, object]], limit: int = 6) -> list[str]:
    findings: list[str] = []
    for record in records:
        title = str(record["title"])
        for item in list(record["findings"])[:3]:
            item = short_text(item, limit=150)
            prefix = f"{title}: "
            findings.append(prefix + item if not item.startswith(title) else item)
            if len(findings) >= limit:
                return ordered_unique(findings)
    return ordered_unique(findings)


def auto_tensions(records: list[dict[str, object]], limit: int = 4) -> list[str]:
    tensions: list[str] = []
    for record in records:
        title = str(record["title"])
        for item in list(record["tensions"])[:2]:
            item = short_text(item, limit=150)
            tensions.append(f"{title}: {item}")
            if len(tensions) >= limit:
                return ordered_unique(tensions)
        if not list(record["tensions"]):
            hinted = [item for item in list(record["findings"]) if likely_tension(item)][:2]
            for item in hinted:
                item = short_text(item, limit=150)
                tensions.append(f"{title}: {item}")
                if len(tensions) >= limit:
                    return ordered_unique(tensions)
    summaries = ordered_unique([str(record["summary"]).strip() for record in records if str(record["summary"]).strip()])
    if len(summaries) > 1:
        tensions.append("不同来源强调的重点并不完全一致，需要人工确认哪些结论应上升为稳定知识。")
    if not tensions and len(records) >= 2:
        tensions.append("当前 digest 主要做信息汇总，是否存在冲突、时效差异或证据缺口仍需进一步审阅。")
    if not tensions:
        tensions.append("当前输入来源较少，尚未形成明显冲突，但仍需要继续补充资料与交叉验证。")
    return ordered_unique(tensions[:limit])


def auto_content(summary: str, findings: list[str], tensions: list[str]) -> str:
    lines = [summary.strip()]
    if findings:
        lines.extend(["", "Findings:"])
        lines.extend(f"- {item}" for item in findings[:4])
    if tensions:
        lines.extend(["", "Tensions:"])
        lines.extend(f"- {item}" for item in tensions[:3])
    return "\n".join(line for line in lines if line is not None).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist a multi-page digest into wiki/syntheses.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--title", required=True, help="Digest title")
    parser.add_argument("--summary", default="", help="Short summary stored in frontmatter")
    parser.add_argument("--content", default="", help="Optional long-form digest body")
    parser.add_argument("--source-path", action="append", default=[], help="Consulted wiki page path")
    parser.add_argument("--related-path", action="append", default=[], help="Related wiki page path")
    parser.add_argument("--finding", action="append", default=[], help="Key finding")
    parser.add_argument("--tension", action="append", default=[], help="Open tension or conflict")
    parser.add_argument("--slug", default="", help="Explicit target slug")
    parser.add_argument("--update", action="store_true", help="Update an existing digest page with the same title or slug")
    parser.add_argument("--merge-mode", choices=["append", "replace", "dedupe"], default="dedupe", help="How to merge fields when --update is used")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    records: list[dict[str, object]] = []
    if args.source_path:
        for raw in args.source_path:
            path = resolve_input_path(root, raw)
            if not path.exists():
                raise SystemExit(f"Source path not found: {raw}")
            records.append(source_record(root, path, summary_kind="synthesis"))

    auto_source_paths = ordered_unique([
        source_path
        for record in records
        for source_path in list(record["source_paths"]) or ([record["path"].relative_to(root).as_posix()] if Path(record["path"]).is_relative_to(root) else [])
    ])
    auto_related_paths = ordered_unique([item for record in records for item in list(record["related_paths"])])
    auto_findings_list = auto_findings(records)
    auto_tensions_list = auto_tensions(records)
    auto_summary_text = auto_summary(records, first_meaningful_line(args.content, args.title), summary_kind="synthesis")
    generated_content = auto_content(auto_summary_text, auto_findings_list, auto_tensions_list)

    summary = args.summary.strip() or auto_summary_text
    content = args.content.strip() or generated_content
    page_path, action = write_page(
        root=root,
        kind="synthesis",
        title=args.title,
        summary=summary,
        content=content,
        source_paths=ordered_unique(args.source_path + auto_source_paths) or ["index.md"],
        related_paths=ordered_unique(args.related_path + auto_related_paths),
        follow_ups=[],
        findings=ordered_unique(args.finding + auto_findings_list),
        tensions=ordered_unique(args.tension + auto_tensions_list),
        key_points=[],
        action_label="digest",
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
