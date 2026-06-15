#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import html as html_lib
import os
import re
import shutil
import zlib
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

import rebuild_index
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from runtime_capabilities import missing_dependency_message, missing_modules_for_source
from utils import (
    append_log,
    classify_raw_dir,
    find_repo_root,
    load_template,
    parse_frontmatter,
    read_text,
    render_template,
    slugify,
    today_str,
    unique_path,
    write_text,
)

MARKDOWN_EXTENSIONS = {".md", ".txt", ".markdown"}
META_PREFIXES = ("- 来源：", "- 作者：", "- 发布日期：", "- 原文链接：")
NOISE_MARKERS = (
    "<ama-doc>",
    "文件编号",
    "文档版本",
    "最后修改日期",
    "修订页",
    "编 写 人",
    "编写时间",
    "目录",
    "page ",
)
SUMMARY_SECTION_HINTS = {"摘要", "summary", "abstract", "概述", "方案结论"}
CONTINUATION_ENDINGS = tuple("的了和与及并而按把将向在于为是小会度案等其")
DECISION_SUMMARY_HINTS = ("不适合", "应按", "应采用", "建议采用", "推荐采用", "换句话说", "核心判断")
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)
REMOVE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "input",
    "button",
    "svg",
    "canvas",
    "footer",
    "nav",
    ".comment",
    ".comments",
    "#comments",
    ".sidebar",
    ".share",
    ".advertisement",
    ".ads",
    ".related",
)
CONTENT_SELECTORS = (
    "article",
    "main",
    '[role="main"]',
    ".post-content",
    ".entry-content",
    ".article-content",
    ".content",
    "#content",
    ".rich_media_content",
    "body",
)
SUPPORTED_INGEST_EXTENSIONS = MARKDOWN_EXTENSIONS | {".pdf", ".docx", ".xlsx", ".xls", ".pptx"}


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())


def plain_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`~#>]+", " ", text)
    return normalize_text(text).strip(" -|,;:*")


def body_lines(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    start_index = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                start_index = index + 1
                break
    return lines[start_index:]


def clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank_count = 0
        else:
            blank_count += 1
            if blank_count <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip() + ("\n" if cleaned else "")


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


def is_page_marker(text: str) -> bool:
    compact = plain_text(text).lower()
    return bool(re.fullmatch(r"page\s+\d+", compact))


def is_noise_line(text: str) -> bool:
    compact = plain_text(text)
    if not compact:
        return True
    lowered = compact.lower()
    if lowered.startswith(NOISE_MARKERS):
        return True
    if compact in {"---", "***"}:
        return True
    if is_page_marker(compact):
        return True
    if is_table_like_text(text):
        return True
    if is_toc_like_text(compact):
        return True
    return False


def looks_like_list_item(text: str) -> bool:
    compact = plain_text(text)
    return bool(re.match(r"^(?:\d+[\.\)、]|[一二三四五六七八九十]+[、\.])", compact))


def is_cover_like_text(text: str) -> bool:
    compact = plain_text(text)
    if not compact:
        return True
    if compact.startswith(("日期：", "日期:")) and len(compact) <= 24:
        return True
    if re.match(r"^[一二三四五六七八九十]+、", compact) and len(compact) <= 20:
        return True
    if len(compact) <= 24 and not any(punct in compact for punct in ("。", "！", "？", "；", ":", "：")):
        return True
    return False


def cleaned_content_blocks(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    block_lines: list[str] = []
    current_section = ""

    def flush_block() -> None:
        nonlocal block_lines
        if not block_lines:
            return
        joined = " ".join(block_lines).strip()
        block_lines = []
        if not joined:
            return
        blocks.append({
            "section": current_section,
            "text": joined,
            "index": len(blocks),
        })

    for raw in body_lines(text):
        stripped = raw.strip()
        if not stripped or stripped == "---":
            flush_block()
            continue
        if stripped.startswith("#"):
            flush_block()
            current_section = plain_text(stripped.lstrip("#").strip())
            continue
        if stripped.startswith("![]("):
            continue
        if stripped.startswith(META_PREFIXES):
            continue
        if stripped.startswith(("```", "<!--")):
            continue
        if stripped.startswith(("更新时间", "更新于", "Published:", "Updated:")):
            continue
        if stripped.startswith(("http://", "https://")) and len(stripped) > 80:
            continue
        cleaned = plain_text(stripped.lstrip("-* ").strip())
        if not cleaned or is_noise_line(cleaned):
            flush_block()
            continue
        block_lines.append(cleaned)
    flush_block()
    return blocks


def merge_adjacent_blocks(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    if not blocks:
        return []
    merged: list[dict[str, object]] = []
    current = dict(blocks[0])
    for block in blocks[1:]:
        current_text = str(current["text"])
        next_text = str(block["text"])
        same_section = str(current["section"]) == str(block["section"])
        current_ends_incomplete = not current_text.endswith(("。", "！", "？", "；", ".", "!", "?", ";", ":", "："))
        current_ends_incomplete = current_ends_incomplete or current_text.endswith(CONTINUATION_ENDINGS)
        next_is_continuation = not looks_like_list_item(next_text)
        next_is_short = len(next_text) <= 36
        if same_section and not is_cover_like_text(current_text) and not is_cover_like_text(next_text) and next_is_continuation and (current_ends_incomplete or next_is_short):
            current["text"] = f"{current_text} {next_text}".strip()
            continue
        merged.append(current)
        current = dict(block)
    merged.append(current)
    for index, block in enumerate(merged):
        block["index"] = index
    return merged


def cleaned_content_lines(text: str) -> list[str]:
    return [str(block["text"]) for block in merge_adjacent_blocks(cleaned_content_blocks(text))]


def summary_block_score(block: dict[str, object]) -> int:
    text = str(block["text"])
    section = str(block["section"]).strip().lower()
    index = int(block["index"])
    score = 0
    if section in SUMMARY_SECTION_HINTS:
        score += 14
    score += max(0, 6 - min(index, 6))
    if len(text) >= 40:
        score += 8
    if len(text) >= 80:
        score += 5
    if len(text) >= 160:
        score += 3
    if len(text) < 20:
        score -= 12
    elif len(text) < 40:
        score -= 4
    if looks_like_list_item(text):
        score -= 10
    if text.endswith(("：", ":")):
        score -= 6
    if any(punct in text for punct in ("。", "；", ":", "：")):
        score += 3
    if any(hint in text for hint in DECISION_SUMMARY_HINTS):
        score += 8
    if section and section in text.lower():
        score -= 2
    if index <= 2 and section not in SUMMARY_SECTION_HINTS:
        score -= 3
    if is_noise_line(text):
        score -= 20
    return score


def trim_summary_tail(text: str) -> str:
    trimmed = text.strip()
    trimmed = re.sub(r"\s+(?:建议采用|建议如下|如下|其中|包括|可分为)[:：]\s*$", "", trimmed)
    if trimmed.endswith(("：", ":")):
        sentence_end = max(trimmed.rfind("。"), trimmed.rfind("！"), trimmed.rfind("？"), trimmed.rfind(";"), trimmed.rfind("；"))
        if sentence_end != -1:
            trimmed = trimmed[: sentence_end + 1]
    return trimmed.strip()


def summarize(text: str) -> tuple[str, list[str]]:
    blocks = merge_adjacent_blocks(cleaned_content_blocks(text))
    if not blocks:
        return "Imported source.", []
    scored_blocks = [(summary_block_score(block), block) for block in blocks]
    high_quality_blocks = [block for score, block in scored_blocks if score >= 8]
    best_block = high_quality_blocks[0] if high_quality_blocks else max(scored_blocks, key=lambda item: item[0])[1]
    ranked_blocks = [block for _score, block in sorted(scored_blocks, key=lambda item: (-item[0], int(item[1]["index"])))]
    summary = trim_summary_tail(str(best_block["text"]))[:140] if summary_block_score(best_block) > -10 else "Imported source."
    bullets: list[str] = []
    used: set[str] = set()
    for block in ranked_blocks:
        text_value = str(block["text"])
        if text_value == summary or text_value in used:
            continue
        if summary_block_score(block) < 0:
            continue
        if len(text_value) < 12:
            continue
        bullets.append(text_value[:120])
        used.add(text_value)
        if len(bullets) >= 4:
            break
    if not bullets and summary != "Imported source.":
        bullets.append(summary[:120])
    return summary, bullets[:4]


def excerpt_markdown(text: str, max_lines: int = 18, max_chars: int = 1600) -> str:
    excerpt_lines: list[str] = []
    current_chars = 0
    content_started = False
    for raw in body_lines(text):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "---":
            if content_started:
                break
            continue
        if stripped.startswith(META_PREFIXES):
            continue
        if stripped.startswith("![]("):
            continue
        if is_page_marker(stripped):
            continue
        if stripped.startswith(("http://", "https://")):
            continue
        if stripped and is_noise_line(stripped):
            continue
        if not stripped and not excerpt_lines:
            continue
        if stripped and not stripped.startswith("#"):
            content_started = True
        excerpt_lines.append(line)
        current_chars += len(line)
        if len(excerpt_lines) >= max_lines or current_chars >= max_chars:
            break
    excerpt = "\n".join(excerpt_lines).strip()
    return excerpt or "_No excerpt available._"


def extract_title_from_markdown(text: str, fallback: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            title = plain_text(line[2:].strip())
            if title:
                return title
    for block in cleaned_content_blocks(text):
        candidate = str(block["text"]).strip()
        if not candidate:
            continue
        if looks_like_list_item(candidate):
            continue
        if len(candidate) > 60:
            continue
        if candidate.endswith(("：", ":")):
            continue
        return candidate[:120]
    blocks = merge_adjacent_blocks(cleaned_content_blocks(text))
    if blocks:
        return str(blocks[0]["text"])[:60]
    return fallback


def humanize_name(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip().title()


def ensure_local_source_dependencies(source_path: Path) -> None:
    missing = missing_modules_for_source(source_path)
    if missing:
        raise SystemExit(missing_dependency_message(source_path, missing))


def convert_with_markitdown(source_path: Path) -> str:
    ensure_local_source_dependencies(source_path)
    try:
        from markitdown import MarkItDown
    except Exception as exc:
        raise SystemExit(
            "markitdown Python package is not available. "
            "Install llm-wiki runtime dependencies before converting office documents."
        ) from exc
    try:
        result = MarkItDown().convert(str(source_path))
    except Exception as exc:
        raise SystemExit(f"markitdown failed for {source_path.name}: {exc}") from exc
    content = getattr(result, "text_content", "") or getattr(result, "markdown", "")
    if not str(content).strip():
        raise SystemExit(f"markitdown failed for {source_path.name}: empty output")
    return clean_markdown(str(content))


def fetch_raw_html(url: str) -> str:
    request = urllib_request.Request(
        url,
        headers={
            "User-Agent": WEB_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            raw_bytes = response.read()
            content_encoding = (response.headers.get("Content-Encoding") or "").lower()
            if "gzip" in content_encoding:
                raw_bytes = gzip.decompress(raw_bytes)
            elif "deflate" in content_encoding:
                raw_bytes = zlib.decompress(raw_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return raw_bytes.decode(charset, errors="replace")
    except (urllib_error.URLError, ValueError, OSError, gzip.BadGzipFile, zlib.error):
        return ""


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def detect_wechat(url: str, soup: BeautifulSoup) -> bool:
    if "mp.weixin.qq.com" in url:
        return True
    return soup.select_one("#js_content") is not None


def find_meta_content(soup: BeautifulSoup, key: str, attr: str = "name") -> str:
    node = soup.find("meta", attrs={attr: key})
    if node and node.get("content"):
        return clean_text(html_lib.unescape(str(node["content"])))
    return ""


def parse_publish_date_from_timestamp(raw: str) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return raw


def extract_wechat_metadata(
    soup: BeautifulSoup, raw_html: str, url: str
) -> tuple[str, str, str, str, BeautifulSoup]:
    title_node = soup.select_one("#activity-name .js_title_inner") or soup.select_one("#activity-name")
    author_node = soup.select_one("#js_author_name_text") or soup.select_one("#js_author_name")
    account_node = soup.select_one("#js_name")
    content_node = soup.select_one("#js_content")

    title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
    author = clean_text(author_node.get_text(" ", strip=True)) if author_node else ""
    account = clean_text(account_node.get_text(" ", strip=True)) if account_node else ""

    ts_match = re.search(r'var\s+ct\s*=\s*"(\d+)"', raw_html)
    publish_date = parse_publish_date_from_timestamp(ts_match.group(1) if ts_match else "")
    if content_node is None:
        raise SystemExit(f"Unable to locate WeChat content node for {url}")
    return title, author, account, publish_date, content_node


def extract_generic_metadata(soup: BeautifulSoup, url: str) -> tuple[str, str, str, str, BeautifulSoup]:
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" ", strip=True))
    if not title:
        title = find_meta_content(soup, "og:title", attr="property")
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    author = (
        find_meta_content(soup, "author")
        or find_meta_content(soup, "article:author", attr="property")
        or find_meta_content(soup, "og:article:author", attr="property")
    )
    site_name = find_meta_content(soup, "og:site_name", attr="property") or urlparse(url).netloc
    publish_date = (
        find_meta_content(soup, "article:published_time", attr="property")
        or find_meta_content(soup, "publish_date")
        or find_meta_content(soup, "pubdate")
        or find_meta_content(soup, "date")
    )

    content_node = None
    for selector in CONTENT_SELECTORS:
        content_node = soup.select_one(selector)
        if content_node and clean_text(content_node.get_text(" ", strip=True)):
            break
    if content_node is None:
        raise SystemExit(f"Unable to locate main content node for {url}")
    return title or "webpage", author, site_name, publish_date, content_node


def normalize_images(content_node: BeautifulSoup) -> None:
    for img in content_node.select("img"):
        src = (
            img.get("data-src")
            or img.get("data-original")
            or img.get("data-url")
            or img.get("data-croporisrc")
            or img.get("src")
        )
        if src:
            img["src"] = html_lib.unescape(src)
        alt = img.get("alt")
        if alt:
            img["alt"] = clean_text(alt)


def remove_noise(content_node: BeautifulSoup) -> None:
    for selector in REMOVE_SELECTORS:
        for node in content_node.select(selector):
            node.decompose()


def html_to_markdown(content_node: BeautifulSoup) -> str:
    raw_markdown = md(str(content_node), heading_style="ATX", bullets="-", strip=["script", "style"])
    return clean_markdown(raw_markdown)


def build_web_header(title: str, site_name: str, author: str, publish_date: str, url: str) -> str:
    lines = [f"# {title}", ""]
    if site_name:
        lines.append(f"- 来源：{site_name}")
    if author:
        lines.append(f"- 作者：{author}")
    if publish_date:
        lines.append(f"- 发布日期：{publish_date}")
    lines.append(f"- 原文链接：{url}")
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def fetch_webpage_as_markdown(url: str, title_override: str = "") -> tuple[str, str]:
    raw_html = fetch_raw_html(url)
    if not raw_html.strip():
        raise SystemExit(f"Failed to fetch webpage HTML for {url}")
    soup = BeautifulSoup(raw_html, "html.parser")
    if detect_wechat(url, soup):
        title, author, site_name, publish_date, content_node = extract_wechat_metadata(soup, raw_html, url)
    else:
        title, author, site_name, publish_date, content_node = extract_generic_metadata(soup, url)
    if title_override.strip():
        title = title_override.strip()
    remove_noise(content_node)
    normalize_images(content_node)
    markdown = html_to_markdown(content_node)
    return build_web_header(title, site_name, author, publish_date, url) + markdown, raw_html


def normalize_local_source(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix in MARKDOWN_EXTENSIONS:
        return clean_markdown(read_text(source_path))
    return convert_with_markitdown(source_path)


def build_link(path: Path, root: Path) -> str:
    repo_path = path.relative_to(root).as_posix()
    return f"- [{path.name}](../../{repo_path})"


def ordered_unique(items: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        results.append(value)
    return results


def extract_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip()
            if capture:
                break
            capture = current == heading
            continue
        if capture:
            collected.append(line)
    return "\n".join(collected).strip()


def source_items_block(source_paths: list[str]) -> str:
    return "\n".join(f"  - {path}" for path in source_paths)


def source_links_block(topic_path: Path, root: Path, source_paths: list[str]) -> str:
    lines: list[str] = []
    for source_path in source_paths:
        target_path = root / source_path
        relative = Path(os.path.relpath(target_path, start=topic_path.parent)).as_posix()
        lines.append(f"- [{target_path.stem}]({relative})")
    return "\n".join(lines)


def find_existing_source_page(root: Path, title: str, slug: str) -> Path | None:
    page_dir = root / "wiki" / "sources"
    slug_candidate = page_dir / f"{slug}.md"
    if slug_candidate.exists():
        return slug_candidate
    for page in sorted(page_dir.glob("*.md")):
        meta, _body = parse_frontmatter(read_text(page))
        if str(meta.get("title") or "").strip() == title.strip():
            return page
    return None


def ensure_topic_page(root: Path, topic: str, source_page: Path, summary: str) -> Path:
    topic_slug = slugify(topic, "topic")
    topic_path = root / "wiki" / "topics" / f"{topic_slug}.md"
    source_repo_path = source_page.relative_to(root).as_posix()
    existing_meta: dict[str, object] = {}
    related_links = ""
    if topic_path.exists():
        existing_meta, body = parse_frontmatter(read_text(topic_path))
        related_links = extract_section(body, "Related Pages")

    raw_sources = existing_meta.get("sources", [])
    existing_sources = [str(item).strip() for item in raw_sources] if isinstance(raw_sources, list) else []
    merged_sources = ordered_unique(existing_sources + [source_repo_path])
    topic_title = str(existing_meta.get("title") or topic).strip() or topic
    topic_summary = str(existing_meta.get("summary") or "").strip() or summary
    created = str(existing_meta.get("created") or today_str()).strip() or today_str()
    content = render_template(load_template("pages/topic.md"), {
        "TITLE": topic_title,
        "DATE": created,
        "UPDATED": today_str(),
        "SUMMARY": topic_summary,
        "SOURCE_ITEMS": source_items_block(merged_sources),
        "SOURCE_LINKS": source_links_block(topic_path, root, merged_sources),
        "RELATED_LINKS": related_links,
    })
    write_text(topic_path, content)
    return topic_path


def ingest_local_source(
    root: Path,
    source_path: Path,
    title_override: str = "",
    topic: str = "",
    confidence: str = "",
    status: str = "",
) -> dict[str, object]:
    raw_dir = classify_raw_dir(source_path)
    normalized_text = normalize_local_source(source_path)
    fallback_title = humanize_name(source_path.stem)
    title = title_override.strip() or extract_title_from_markdown(normalized_text, fallback_title)
    slug = slugify(title, "source")
    raw_path = unique_path(root / "raw" / raw_dir / f"{today_str()}-{slug}{source_path.suffix.lower()}")
    normalized_path = unique_path(root / "normalized" / raw_dir / f"{today_str()}-{slug}.md")
    shutil.copy2(source_path, raw_path)
    write_text(normalized_path, normalized_text)

    summary, bullets = summarize(normalized_text)
    source_page = find_existing_source_page(root, title, slug) or (root / "wiki" / "sources" / f"{slug}.md")
    related_links = ""
    touched = [source_page.relative_to(root).as_posix()]
    if topic.strip():
        topic_page = ensure_topic_page(root, topic.strip(), source_page, summary)
        related_links = f"- [{topic.strip()}](../topics/{topic_page.name})"
        touched.append(topic_page.relative_to(root).as_posix())

    resolved_confidence = confidence.strip() or "extracted"
    resolved_status = status.strip() or "active"
    source_content = render_template(load_template("pages/source.md"), {
        "TITLE": title,
        "DATE": today_str(),
        "SUMMARY": summary,
        "RAW_PATH": raw_path.relative_to(root).as_posix(),
        "KEY_POINTS": "\n".join(f"- {item}" for item in bullets),
        "RAW_LINKS": build_link(raw_path, root),
        "NORMALIZED_LINKS": build_link(normalized_path, root),
        "EXTRACTED_EXCERPT": excerpt_markdown(normalized_text),
        "RELATED_LINKS": related_links,
        "OPEN_QUESTIONS": "",
        "CONFIDENCE": resolved_confidence,
        "STATUS": resolved_status,
    })
    write_text(source_page, source_content)
    return {
        "title": title,
        "raw_path": raw_path,
        "normalized_path": normalized_path,
        "source_page": source_page,
        "touched": touched,
    }


def collect_directory_sources(source_dir: Path) -> tuple[list[Path], list[Path]]:
    supported: list[Path] = []
    skipped: list[Path] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_INGEST_EXTENSIONS:
            supported.append(path)
        else:
            skipped.append(path)
    return supported, skipped


def infer_directory_topic(source_dir: Path, source_file: Path) -> str:
    relative = source_file.relative_to(source_dir)
    if len(relative.parts) > 1:
        return relative.parts[0]
    return source_dir.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a local file, webpage, or text source into the wiki.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    parser.add_argument("--source", help="Path to a local source file")
    parser.add_argument("--url", help="Webpage URL to ingest")
    parser.add_argument("--text", help="Inline text to ingest")
    parser.add_argument("--title", default="", help="Human readable title")
    parser.add_argument("--topic", default="", help="Optional topic page to create")
    parser.add_argument("--confidence", default="", help="Confidence label for the generated source page")
    parser.add_argument("--status", default="", help="Status label for the generated source page")
    args = parser.parse_args()

    provided = [bool(args.source), bool(args.url), bool(args.text)]
    if sum(provided) != 1:
        raise SystemExit("Provide exactly one of --source, --url, or --text")

    root = find_repo_root(Path(args.root))
    raw_path: Path
    normalized_path: Path
    if args.source:
        source_path = Path(args.source).resolve()
        if not source_path.exists():
            raise SystemExit(f"Source file not found: {source_path}")
        if source_path.is_dir():
            files, skipped = collect_directory_sources(source_path)
            if not files:
                raise SystemExit(f"No supported files found under: {source_path}")
            results = []
            for item in files:
                topic_name = args.topic.strip() or infer_directory_topic(source_path, item)
                results.append(ingest_local_source(root, item, topic=topic_name))
            write_text(root / "index.md", rebuild_index.build_index(root))
            log_lines = [
                f"- source_dir: {source_path}",
                f"- imported: {len(results)}",
                *[f"- created: {result['source_page'].relative_to(root).as_posix()}" for result in results],
            ]
            if skipped:
                log_lines.append(f"- skipped: {len(skipped)} unsupported files")
            append_log(root, f"[{today_str()}] ingest-dir | {source_path.name}", log_lines)
            print(f"Ingested {len(results)} files from {source_path}")
            return 0
        result = ingest_local_source(
            root,
            source_path,
            title_override=args.title,
            topic=args.topic,
            confidence=args.confidence,
            status=args.status,
        )
    elif args.url:
        normalized_text, raw_html = fetch_webpage_as_markdown(args.url, args.title)
        parsed = urlparse(args.url)
        fallback_title = humanize_name(Path(parsed.path).stem or parsed.netloc or "webpage")
        title = args.title.strip() or extract_title_from_markdown(normalized_text, fallback_title)
        slug = slugify(title, "source")
        raw_path = unique_path(root / "raw" / "web" / f"{today_str()}-{slug}.html")
        normalized_path = unique_path(root / "normalized" / "web" / f"{today_str()}-{slug}.md")
        write_text(raw_path, raw_html or f"URL: {args.url}")
        write_text(normalized_path, normalized_text)
        raw_text = normalized_text
    else:
        title = args.title.strip() or "Pasted Source"
        slug = slugify(title, "source")
        raw_path = unique_path(root / "raw" / "articles" / f"{today_str()}-{slug}.md")
        normalized_path = unique_path(root / "normalized" / "articles" / f"{today_str()}-{slug}.md")
        raw_text = clean_markdown(args.text or "")
        write_text(raw_path, raw_text)
        write_text(normalized_path, raw_text)

    if args.source:
        write_text(root / "index.md", rebuild_index.build_index(root))
        append_log(root, f"[{today_str()}] ingest | {result['title']}", [
            f"- raw: {result['raw_path'].relative_to(root).as_posix()}",
            f"- normalized: {result['normalized_path'].relative_to(root).as_posix()}",
            *[f"- created: {item}" for item in result["touched"]],
        ])
        print(f"Ingested {result['title']}")
        return 0

    summary, bullets = summarize(raw_text)
    confidence = args.confidence.strip() or ("mixed" if args.text else "extracted")
    status = args.status.strip() or "active"
    source_page = find_existing_source_page(root, title, slug) or (root / "wiki" / "sources" / f"{slug}.md")
    source_content = render_template(load_template("pages/source.md"), {
        "TITLE": title,
        "DATE": today_str(),
        "SUMMARY": summary,
        "RAW_PATH": raw_path.relative_to(root).as_posix(),
        "KEY_POINTS": "\n".join(f"- {item}" for item in bullets),
        "RAW_LINKS": build_link(raw_path, root),
        "NORMALIZED_LINKS": build_link(normalized_path, root),
        "EXTRACTED_EXCERPT": excerpt_markdown(raw_text),
        "RELATED_LINKS": "",
        "OPEN_QUESTIONS": "",
        "CONFIDENCE": confidence,
        "STATUS": status,
    })
    write_text(source_page, source_content)
    write_text(root / "index.md", rebuild_index.build_index(root))
    append_log(root, f"[{today_str()}] ingest | {title}", [
        f"- raw: {raw_path.relative_to(root).as_posix()}",
        f"- normalized: {normalized_path.relative_to(root).as_posix()}",
        f"- created: {source_page.relative_to(root).as_posix()}",
    ])
    print(f"Ingested {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
