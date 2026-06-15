#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from html import escape
import os
from pathlib import Path
import re

from utils import (
    append_log,
    collect_wiki_pages,
    extract_summary,
    find_repo_root,
    is_external_link,
    markdown_links,
    parse_frontmatter,
    read_text,
    today_str,
    write_text,
)


SECTION_TITLES = {
    "topic": "Topics",
    "concept": "Concepts",
    "source": "Sources",
    "synthesis": "Syntheses",
    "query": "Queries",
    "decision": "Decisions",
}


def normalize_list(meta: dict[str, object], key: str) -> list[str]:
    raw = meta.get(key, [])
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if raw:
        return [str(raw)]
    return []


def extract_excerpt(body: str) -> str:
    lines = [line.strip() for line in body.splitlines()]
    chunks: list[str] = []
    for line in lines:
        if not line or line.startswith("#") or line.startswith("- ") or line.startswith("```"):
            continue
        chunks.append(line)
        if len(" ".join(chunks)) >= 240:
            break
    excerpt = " ".join(chunks).strip()
    return excerpt[:280] if excerpt else "(no excerpt yet)"


def slugify_anchor(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "section"


def extract_ref_targets(text: str) -> list[str]:
    matches = re.findall(r"ref:\s*([^\s|]+)", text)
    return [match.strip() for match in matches if match.strip()]


def viewer_href(root: Path, target: Path) -> str:
    return Path(os.path.relpath(target, start=root / "output" / "viewer")).as_posix()


def link_record(root: Path, page: Path, raw_link: str) -> dict[str, str]:
    resolved = (page.parent / raw_link).resolve()
    label = Path(raw_link).name or raw_link
    if resolved.is_relative_to(root.resolve()):
        repo_path = resolved.relative_to(root).as_posix()
        if repo_path.startswith("wiki/") and resolved.exists():
            return {"label": label, "raw": raw_link, "targetId": repo_path, "href": ""}
        return {"label": label, "raw": raw_link, "targetId": "", "href": viewer_href(root, resolved)}
    return {"label": label, "raw": raw_link, "targetId": "", "href": raw_link}


def extract_section_records(root: Path, page: Path, body: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current_title = "Overview"
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_lines
        lines = [line.rstrip() for line in block_lines if line.strip()]
        block_lines = []
        if not lines:
            return
        content = "\n".join(lines).strip()
        if not content:
            return
        records.append({
            "title": current_title,
            "anchor": slugify_anchor(current_title),
            "content": content[:2400],
            "refs": extract_ref_targets(content),
            "links": [link_record(root, page, link) for link in markdown_links(content) if not is_external_link(link)],
        })

    for raw_line in body.replace("\r\n", "\n").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            flush_block()
            current_title = stripped[3:].strip() or "Overview"
            continue
        if stripped.startswith("### "):
            flush_block()
            current_title = stripped[4:].strip() or current_title
            continue
        if stripped.startswith("#"):
            continue
        if not stripped and not block_lines:
            continue
        block_lines.append(raw_line)

    flush_block()
    return records


def collect_page_record(root: Path, page: Path) -> dict[str, object]:
    meta, body = parse_frontmatter(read_text(page))
    page_type = str(meta.get("type") or page.parent.name[:-1])
    links = [link_record(root, page, link) for link in markdown_links(body) if not is_external_link(link)]
    return {
        "id": page.relative_to(root).as_posix(),
        "title": str(meta.get("title") or page.stem),
        "type": page_type,
        "section": SECTION_TITLES.get(page_type, page_type.title()),
        "summary": extract_summary(meta, body),
        "excerpt": extract_excerpt(body),
        "updated": str(meta.get("updated") or meta.get("created") or ""),
        "confidence": str(meta.get("confidence") or ""),
        "status": str(meta.get("status") or ""),
        "sources": normalize_list(meta, "sources"),
        "tags": normalize_list(meta, "tags"),
        "links": links,
        "sections": extract_section_records(root, page, body),
    }


def build_payload(root: Path) -> dict[str, object]:
    pages = [collect_page_record(root, page) for page in collect_wiki_pages(root)]
    counts: dict[str, int] = {}
    for page in pages:
        page_type = str(page["type"])
        counts[page_type] = counts.get(page_type, 0) + 1

    return {
        "generatedAt": today_str(),
        "rootName": root.name,
        "pageCount": len(pages),
        "counts": counts,
        "pages": sorted(pages, key=lambda item: (str(item["section"]), str(item["title"]).lower())),
    }


def json_for_script(payload: dict[str, object]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_stats(payload: dict[str, object]) -> str:
    counts = payload["counts"]
    assert isinstance(counts, dict)
    chips = [
        f"<div class='stat'><strong>{escape(str(count))}</strong><span>{escape(SECTION_TITLES.get(kind, kind.title()))}</span></div>"
        for kind, count in sorted(counts.items())
    ]
    return "\n".join(chips) if chips else "<div class='stat'><strong>0</strong><span>Pages</span></div>"


def render_html(payload: dict[str, object]) -> str:
    data_json = json_for_script(payload)
    generated_at = escape(str(payload["generatedAt"]))
    root_name = escape(str(payload["rootName"]))
    page_count = escape(str(payload["pageCount"]))
    stats_html = render_stats(payload)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LLM Wiki Viewer</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0b1020;
      --panel: #121935;
      --panel-soft: #182142;
      --text: #edf2ff;
      --muted: #a8b3cf;
      --accent: #8ab4ff;
      --border: rgba(255,255,255,0.1);
      --chip: rgba(138,180,255,0.14);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #0b1020 0%, #10172f 100%);
      color: var(--text);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .sidebar, .content {{
      padding: 24px;
    }}
    .sidebar {{
      border-right: 1px solid var(--border);
      background: rgba(9, 13, 28, 0.78);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    h1, h2, h3, p {{ margin-top: 0; }}
    .lead {{ color: var(--muted); line-height: 1.5; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 20px 0;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
    }}
    .stat strong {{
      display: block;
      font-size: 1.35rem;
    }}
    .stat span {{ color: var(--muted); font-size: 0.9rem; }}
    input, select {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
    }}
    input {{
      margin-bottom: 16px;
    }}
    .controls {{
      display: grid;
      gap: 10px;
      margin-bottom: 16px;
    }}
    .controls-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}
    .nav-group {{
      margin-top: 16px;
    }}
    .nav-group h3 {{
      color: var(--muted);
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 10px;
    }}
    .nav-button {{
      width: 100%;
      text-align: left;
      background: transparent;
      color: var(--text);
      border: 1px solid transparent;
      border-radius: 12px;
      padding: 10px 12px;
      margin-bottom: 6px;
      cursor: pointer;
    }}
    .nav-button:hover, .nav-button.active {{
      background: var(--panel-soft);
      border-color: var(--border);
    }}
    .nav-path {{
      display: block;
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 4px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
    }}
    .meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 14px 0 18px;
    }}
    .chip {{
      background: var(--chip);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.85rem;
    }}
    .card {{
      background: rgba(18, 25, 53, 0.9);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      margin-top: 18px;
    }}
    .card h2 {{
      font-size: 1rem;
      margin-bottom: 12px;
    }}
    .section-card {{
      scroll-margin-top: 24px;
    }}
    .section-card.active-section {{
      border-color: rgba(138,180,255,0.75);
      box-shadow: 0 0 0 1px rgba(138,180,255,0.25);
    }}
    .section-content {{
      white-space: pre-wrap;
      color: var(--muted);
      line-height: 1.65;
    }}
    .section-meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 12px;
    }}
    .ref-list {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .ref-button {{
      background: var(--panel-soft);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.82rem;
      cursor: pointer;
    }}
    .ref-button:hover {{
      border-color: rgba(138,180,255,0.45);
      color: var(--accent);
    }}
    .list {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .empty {{
      color: var(--muted);
      padding: 32px;
      border: 1px dashed var(--border);
      border-radius: 16px;
      text-align: center;
      margin-top: 18px;
    }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>LLM Wiki</h1>
      <p class="lead">Static viewer for <strong>{root_name}</strong>. Open this file locally to browse compiled wiki pages.</p>
      <div class="controls">
        <input id="search" type="search" placeholder="Search pages, tags, or summary">
        <div class="controls-row">
          <select id="confidence">
            <option value="">All confidence</option>
            <option value="verified">verified</option>
            <option value="extracted">extracted</option>
            <option value="mixed">mixed</option>
            <option value="inferred">inferred</option>
          </select>
          <select id="status">
            <option value="">All status</option>
            <option value="active">active</option>
            <option value="stale">stale</option>
            <option value="archived">archived</option>
            <option value="superseded">superseded</option>
          </select>
        </div>
        <select id="sort">
          <option value="relevance">Sort: relevance</option>
          <option value="updated-desc">Sort: updated desc</option>
          <option value="confidence-desc">Sort: confidence desc</option>
          <option value="title-asc">Sort: title asc</option>
        </select>
      </div>
      <div class="stats">
        <div class="stat"><strong>{page_count}</strong><span>Total Pages</span></div>
        <div class="stat"><strong>{generated_at}</strong><span>Generated</span></div>
        {stats_html}
      </div>
      <div id="nav"></div>
    </aside>
    <main class="content">
      <div class="hero">
        <div>
          <p class="lead">A lightweight, zero-dependency wiki browser. It gives you a searchable overview, page summaries, source paths, and links without running a server.</p>
        </div>
      </div>
      <section id="viewer"></section>
    </main>
  </div>
  <script>
    const payload = {data_json};
    const searchEl = document.getElementById("search");
    const confidenceEl = document.getElementById("confidence");
    const statusEl = document.getElementById("status");
    const sortEl = document.getElementById("sort");
    const navEl = document.getElementById("nav");
    const viewerEl = document.getElementById("viewer");
    let activeId = payload.pages.length ? payload.pages[0].id : null;
    let activeSectionAnchor = "";

    function confidenceRank(value) {{
      const order = {{ verified: 4, extracted: 3, mixed: 2, inferred: 1 }};
      return order[String(value || "").toLowerCase()] || 0;
    }}

    function statusRank(value) {{
      const order = {{ active: 4, stale: 3, archived: 2, superseded: 1 }};
      return order[String(value || "").toLowerCase()] || 0;
    }}

    function updatedRank(value) {{
      const parsed = Date.parse(value || "");
      return Number.isNaN(parsed) ? 0 : parsed;
    }}

    function groupPages(pages) {{
      const groups = new Map();
      pages.forEach((page) => {{
        if (!groups.has(page.section)) groups.set(page.section, []);
        groups.get(page.section).push(page);
      }});
      return Array.from(groups.entries());
    }}

    function matchesFilters(page, query) {{
      const needle = query.trim().toLowerCase();
      const confidenceNeedle = confidenceEl.value.trim().toLowerCase();
      const statusNeedle = statusEl.value.trim().toLowerCase();
      if (confidenceNeedle && String(page.confidence || "").toLowerCase() !== confidenceNeedle) {{
        return false;
      }}
      if (statusNeedle && String(page.status || "").toLowerCase() !== statusNeedle) {{
        return false;
      }}
      if (!needle) return true;
      return [
          page.title,
          page.type,
          page.summary,
          page.excerpt,
          page.id,
          ...(page.tags || []),
          ...(page.sources || []),
          ...((page.links || []).map((item) => item.raw || item.label || "")),
        ].join(" ").toLowerCase().includes(needle);
    }}

    function sortPages(pages, query) {{
      const needle = query.trim().toLowerCase();
      const mode = sortEl.value;
      const items = [...pages];
      if (mode === "updated-desc") {{
        items.sort((a, b) => updatedRank(b.updated) - updatedRank(a.updated) || a.title.localeCompare(b.title));
        return items;
      }}
      if (mode === "confidence-desc") {{
        items.sort((a, b) =>
          confidenceRank(b.confidence) - confidenceRank(a.confidence) ||
          statusRank(b.status) - statusRank(a.status) ||
          updatedRank(b.updated) - updatedRank(a.updated) ||
          a.title.localeCompare(b.title)
        );
        return items;
      }}
      if (mode === "title-asc") {{
        items.sort((a, b) => a.title.localeCompare(b.title));
        return items;
      }}
      items.sort((a, b) => {{
        const hayA = [a.title, a.summary, a.excerpt, ...(a.tags || []), ...(a.sources || []), ...((a.links || []).map((item) => item.raw || item.label || ""))].join(" ").toLowerCase();
        const hayB = [b.title, b.summary, b.excerpt, ...(b.tags || []), ...(b.sources || []), ...((b.links || []).map((item) => item.raw || item.label || ""))].join(" ").toLowerCase();
        const scoreA =
          (needle && hayA.includes(needle) ? 5 : 0) +
          confidenceRank(a.confidence) * 2 +
          statusRank(a.status) +
          Math.min(updatedRank(a.updated) / 1000000000000, 10);
        const scoreB =
          (needle && hayB.includes(needle) ? 5 : 0) +
          confidenceRank(b.confidence) * 2 +
          statusRank(b.status) +
          Math.min(updatedRank(b.updated) / 1000000000000, 10);
        return scoreB - scoreA || a.title.localeCompare(b.title);
      }});
      return items;
    }}

    function filterPages(query) {{
      return sortPages(payload.pages.filter((page) => matchesFilters(page, query)), query);
    }}

    function renderNav(pages) {{
      const groups = groupPages(pages);
      navEl.innerHTML = groups.map(([section, items]) => `
        <div class="nav-group">
          <h3>${{escapeHtml(section)}}</h3>
          ${{items.map((page) => `
            <button class="nav-button ${{page.id === activeId ? "active" : ""}}" data-id="${{escapeAttribute(page.id)}}">
              <span>${{escapeHtml(page.title)}}</span>
              <span class="nav-path">${{escapeHtml(page.id)}}</span>
            </button>
          `).join("")}}
        </div>
      `).join("");

      navEl.querySelectorAll(".nav-button").forEach((button) => {{
        button.addEventListener("click", () => {{
          activeId = button.dataset.id;
          renderNav(pages);
          renderPage(pages.find((item) => item.id === activeId) || null);
        }});
      }});
    }}

    function renderList(items) {{
      if (!items || !items.length) return `<p class="empty">Nothing here yet.</p>`;
      return `<ul class="list">${{items.map((item) => `<li>${{escapeHtml(item)}}</li>`).join("")}}</ul>`;
    }}

    function renderLinkActions(items) {{
      if (!items || !items.length) return `<p class="empty">Nothing here yet.</p>`;
      return `
        <div class="ref-list">
          ${{items.map((item) => {{
            if (item.targetId) {{
              return `<button class="ref-button" data-page-target="${{escapeAttribute(item.targetId)}}">${{escapeHtml(item.label || item.raw || item.targetId)}}</button>`;
            }}
            return `<a class="ref-button" href="${{escapeAttribute(item.href || item.raw || "#")}}" target="_blank" rel="noopener">${{escapeHtml(item.label || item.raw || item.href || "")}}</a>`;
          }}).join("")}}
        </div>
      `;
    }}

    function renderRefButtons(items, label) {{
      if (!items || !items.length) return "";
      return `
        <div class="ref-list">
          ${{items.map((item) => `<button class="ref-button" data-${{label}}="${{escapeAttribute(item)}}">${{escapeHtml(item)}}</button>`).join("")}}
        </div>
      `;
    }}

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function escapeAttribute(value) {{
      return escapeHtml(value);
    }}

    function parseRef(ref) {{
      const [pageId, sectionAnchor = ""] = String(ref || "").split("#");
      return {{
        pageId: pageId.trim(),
        sectionAnchor: sectionAnchor.trim(),
      }};
    }}

    function activateRef(ref) {{
      const parsed = parseRef(ref);
      const targetPage = payload.pages.find((page) => page.id === parsed.pageId);
      if (!targetPage) return;
      activeId = targetPage.id;
      activeSectionAnchor = parsed.sectionAnchor;
      refresh();
    }}

    function activateSection(anchor) {{
      if (!anchor) return;
      const target = viewerEl.querySelector(`[data-anchor="${{CSS.escape(anchor)}}"]`);
      if (!target) return;
      viewerEl.querySelectorAll(".active-section").forEach((node) => node.classList.remove("active-section"));
      target.classList.add("active-section");
      target.scrollIntoView({{ behavior: "smooth", block: "start" }});
    }}

    function renderSections(page) {{
      if (!page.sections || !page.sections.length) {{
        return `<div class="card"><h2>Sections</h2><p class="empty">No parsed sections available.</p></div>`;
      }}
      return page.sections.map((section) => `
        <div class="card section-card" data-anchor="${{escapeAttribute(section.anchor || "")}}">
          <h2>${{escapeHtml(section.title || "Section")}}</h2>
          <div class="section-meta">
            <span class="chip">${{escapeHtml(section.anchor || "section")}}</span>
          </div>
          <div class="section-content">${{escapeHtml(section.content || "")}}</div>
          ${{section.refs && section.refs.length ? ("<h3>Refs</h3>" + renderRefButtons(section.refs, "ref")) : ""}}
          ${{section.links && section.links.length ? ("<h3>Links</h3>" + renderLinkActions(section.links)) : ""}}
        </div>
      `).join("");
    }}

    function renderPage(page) {{
      if (!page) {{
        viewerEl.innerHTML = `<div class="empty">No matching pages.</div>`;
        return;
      }}
      viewerEl.innerHTML = `
        <div class="meta">
          <span class="chip">${{escapeHtml(page.section)}}</span>
          <span class="chip">${{escapeHtml(page.updated || "unknown date")}}</span>
          <span class="chip">${{escapeHtml(page.confidence || "confidence: n/a")}}</span>
          <span class="chip">${{escapeHtml(page.status || "status: n/a")}}</span>
        </div>
        <h1>${{escapeHtml(page.title)}}</h1>
        <p class="lead">${{escapeHtml(page.summary)}}</p>
        <div class="card">
          <h2>Path</h2>
          <p>${{escapeHtml(page.id)}}</p>
        </div>
        <div class="card">
          <h2>Excerpt</h2>
          <p>${{escapeHtml(page.excerpt)}}</p>
        </div>
        <div class="card">
          <h2>Sources</h2>
          ${{renderList(page.sources)}}
        </div>
        <div class="card">
          <h2>Tags</h2>
          ${{renderList(page.tags)}}
        </div>
        <div class="card">
          <h2>Links</h2>
          ${{renderLinkActions(page.links)}}
        </div>
        <div class="card">
          <h2>Sections</h2>
          <p class="lead">Section refs from ask results can jump directly to the matching block below.</p>
        </div>
        ${{renderSections(page)}}
      `;

      viewerEl.querySelectorAll("[data-ref]").forEach((button) => {{
        button.addEventListener("click", () => activateRef(button.dataset.ref));
      }});
      viewerEl.querySelectorAll("[data-page-target]").forEach((button) => {{
        button.addEventListener("click", () => activateRef(button.dataset.pageTarget));
      }});
      if (activeSectionAnchor) {{
        activateSection(activeSectionAnchor);
      }}
    }}

    function refresh() {{
      const pages = filterPages(searchEl.value);
      if (!pages.some((page) => page.id === activeId)) {{
        activeId = pages.length ? pages[0].id : null;
        activeSectionAnchor = "";
      }}
      renderNav(pages);
      renderPage(pages.find((page) => page.id === activeId) || null);
    }}

    searchEl.addEventListener("input", refresh);
    confidenceEl.addEventListener("change", refresh);
    statusEl.addEventListener("change", refresh);
    sortEl.addEventListener("change", refresh);
    refresh();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lightweight static HTML viewer for the current wiki.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    payload = build_payload(root)
    viewer_dir = root / "output" / "viewer"
    write_text(viewer_dir / "viewer.json", json.dumps(payload, ensure_ascii=False, indent=2))
    write_text(viewer_dir / "index.html", render_html(payload))

    append_log(
        root,
        f"[{today_str()}] viewer | {payload['pageCount']} pages",
        [
            "- output: output/viewer/index.html",
            "- metadata: output/viewer/viewer.json",
        ],
    )
    print(f"Built viewer for {payload['pageCount']} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
