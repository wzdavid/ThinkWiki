from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT_MARKER = ".wiki-schema.md"
WIKI_DIRS = ["concepts", "topics", "sources", "syntheses", "queries", "decisions"]
PAGE_TYPE_TO_DIR = {
    "concept": "concepts",
    "topic": "topics",
    "source": "sources",
    "synthesis": "syntheses",
    "query": "queries",
    "decision": "decisions",
}
SECTION_ORDER = [
    ("Topics", "topic"),
    ("Concepts", "concept"),
    ("Sources", "source"),
    ("Syntheses", "synthesis"),
    ("Queries", "query"),
    ("Decisions", "decision"),
]
REQUIRED_FIELDS = ["title", "type", "created", "updated", "sources", "tags", "confidence", "status"]


def today_str() -> str:
    return date.today().isoformat()


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def slugify(text: str, fallback_prefix: str = "item") -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or f"{fallback_prefix}-{now_slug()}"


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    results: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        results.append(path.expanduser())
    return results


def candidate_dependency_paths(
    *,
    env_name: str,
    skill_name: str,
    relative_path: str,
    command_names: Iterable[str] = (),
    script_file: str | Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        candidates.append(Path(env_value))

    script_root = repo_root_from_script()
    if script_file is not None:
        script_root = Path(script_file).resolve().parents[1]
    cwd = Path.cwd().resolve()
    relative = Path(relative_path)

    # 1) Installed as sibling skills under the same `.trae/skills` directory.
    skill_containers = [script_root.parent, cwd.parent]

    # 2) Running from a project root that contains `.trae/skills`.
    for base in unique_paths([cwd, *cwd.parents, script_root, *script_root.parents]):
        skill_containers.append(base / ".trae" / "skills")

    # 3) Common "project directory next to this repo" layout used in local workspaces.
    sibling_roots = unique_paths([script_root.parent, cwd.parent])
    for parent in sibling_roots:
        try:
            for child in parent.iterdir():
                if child.is_dir():
                    skill_containers.append(child / ".trae" / "skills")
        except OSError:
            continue

    for container in unique_paths(skill_containers):
        candidates.append(container / skill_name / relative)

    for command_name in command_names:
        resolved = shutil.which(command_name)
        if resolved:
            candidates.append(Path(resolved))

    return unique_paths(candidates)


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ROOT_MARKER).exists():
            return candidate
    raise FileNotFoundError(f"Cannot find {ROOT_MARKER} from {current}")


def ensure_runtime_dirs(root: Path) -> None:
    for relative in [
        "raw/articles",
        "raw/papers",
        "raw/books",
        "raw/conversations",
        "raw/web",
        "raw/assets",
        "normalized/articles",
        "normalized/papers",
        "normalized/books",
        "normalized/conversations",
        "normalized/web",
        "normalized/assets",
        "wiki/concepts",
        "wiki/topics",
        "wiki/sources",
        "wiki/syntheses",
        "wiki/queries",
        "wiki/decisions",
        "output/graph",
        "output/viewer",
        "output/exports",
    ]:
        (root / relative).mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _first_markdown_heading(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return ""
    return ""


def _page_sort_key(page: dict) -> tuple[str, str]:
    return (str(page.get("updated", "") or ""), str(page.get("title", "") or ""))


def _render_page_list(items: list[dict], empty_text: str) -> str:
    if not items:
        return "<div class='empty small'>{}</div>".format(escape(empty_text))
    cards: list[str] = []
    for item in items:
        page_id = str(item.get("id", ""))
        title = str(item.get("title", page_id or "Untitled"))
        summary = str(item.get("summary", "") or "(no summary yet)")
        page_type = str(item.get("type", "page") or "page")
        updated = str(item.get("updated", "") or "n/a")
        href = "viewer/index.html#page={}".format(escape(page_id, quote=True))
        cards.append(
            "<a class='mini-card' href='{href}' target='_blank' rel='noopener'>"
            "<div class='mini-meta'><span class='mini-type'>{page_type}</span><span>{updated}</span></div>"
            "<strong>{title}</strong>"
            "<span>{summary}</span>"
            "</a>".format(
                href=href,
                page_type=escape(page_type),
                updated=escape(updated),
                title=escape(title),
                summary=escape(summary),
            )
        )
    return "\n".join(cards)


def write_output_home(root: Path) -> Path:
    output_dir = root / "output"
    viewer_path = output_dir / "viewer" / "index.html"
    graph_path = output_dir / "graph" / "index.html"
    viewer_data = _load_json(output_dir / "viewer" / "viewer.json")
    graph_data = _load_json(output_dir / "graph" / "graph.json")
    wiki_title = _first_markdown_heading(root / "index.md") or root.name
    generated_at = str(viewer_data.get("generatedAt") or graph_data.get("generated_at") or today_str())
    page_count = int(viewer_data.get("pageCount", 0) or 0)
    node_count = len(graph_data.get("nodes", [])) if isinstance(graph_data.get("nodes"), list) else 0
    edge_count = len(graph_data.get("edges", [])) if isinstance(graph_data.get("edges"), list) else 0
    ready_outputs = int(viewer_path.exists()) + int(graph_path.exists())
    pages = viewer_data.get("pages", []) if isinstance(viewer_data.get("pages"), list) else []
    recent_pages = sorted(pages, key=_page_sort_key, reverse=True)[:3]
    featured_pages = [
        page
        for page in pages
        if str(page.get("type", "")) in {"concept", "decision"}
    ]
    featured_pages = sorted(featured_pages, key=_page_sort_key, reverse=True)[:3]
    items: list[str] = []
    for title, path, summary in [
        ("本地浏览页", viewer_path, "按页面类型、置信度和状态浏览整个 wiki"),
        ("知识图谱", graph_path, "查看页面之间的引用、包含和链接关系"),
    ]:
        if not path.exists():
            continue
        relative = path.relative_to(output_dir).as_posix()
        items.append(
            "<a class='card' href='{href}' target='_blank' rel='noopener'>"
            "<strong>{title}</strong>"
            "<span>{summary}</span>"
            "<code>{path}</code>"
            "</a>".format(
                href=escape(relative),
                title=escape(title),
                summary=escape(summary),
                path=escape(relative),
            )
        )
    if not items:
        items.append("<div class='empty'>还没有可浏览的成果页。先运行 viewer 或 graph 命令。</div>")

    stats: list[str] = []
    for label, value in [
        ("成果页", ready_outputs),
        ("页面数", page_count),
        ("图节点", node_count),
        ("图关系", edge_count),
    ]:
        stats.append(
            "<div class='stat'><strong>{value}</strong><span>{label}</span></div>".format(
                value=escape(str(value)),
                label=escape(label),
            )
        )
    recent_pages_html = _render_page_list(recent_pages, "还没有可推荐的最近页面。先运行 viewer 生成浏览成果页。")
    featured_pages_html = _render_page_list(featured_pages, "还没有代表性概念或决策页面。")

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ThinkWiki Outputs</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #121935;
      --text: #edf2ff;
      --muted: #a8b3cf;
      --border: rgba(255,255,255,0.1);
      --accent: #8ab4ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #0b1020 0%, #10172f 100%);
      color: var(--text);
      display: grid;
      place-items: center;
      padding: 24px;
    }}
    .shell {{
      width: min(880px, 100%);
      background: rgba(9, 13, 28, 0.86);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 28px;
    }}
    h1, p {{ margin-top: 0; }}
    .lead {{
      color: var(--muted);
      line-height: 1.6;
      margin-bottom: 20px;
    }}
    .hero {{
      display: grid;
      gap: 18px;
      margin-bottom: 24px;
    }}
    .eyebrow {{
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.82rem;
      margin-bottom: 10px;
    }}
    .hero-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .hero-title h1 {{
      margin-bottom: 0;
    }}
    .meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .badge {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 12px;
      color: var(--muted);
      font-size: 0.92rem;
      background: rgba(255,255,255,0.03);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .stat {{
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: 18px;
      padding: 16px;
    }}
    .stat strong {{
      display: block;
      font-size: 1.45rem;
      margin-bottom: 6px;
    }}
    .stat span {{
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      gap: 14px;
    }}
    .section-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}
    .panel {{
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.02);
      border-radius: 18px;
      padding: 18px;
    }}
    .panel h2 {{
      margin: 0 0 8px;
      font-size: 1rem;
    }}
    .panel p {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .card {{
      display: block;
      text-decoration: none;
      color: inherit;
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: 18px;
      padding: 18px;
    }}
    .card:hover {{
      border-color: rgba(138,180,255,0.55);
      box-shadow: 0 0 0 1px rgba(138,180,255,0.18);
    }}
    .card strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 1.05rem;
    }}
    .card span {{
      display: block;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    code {{
      color: var(--accent);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-word;
    }}
    .empty {{
      border: 1px dashed var(--border);
      border-radius: 18px;
      padding: 18px;
      color: var(--muted);
    }}
    .small {{
      padding: 14px;
      font-size: 0.95rem;
    }}
    .mini-card {{
      display: block;
      text-decoration: none;
      color: inherit;
      border: 1px solid var(--border);
      background: rgba(18, 25, 53, 0.85);
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 10px;
    }}
    .mini-card:last-child {{
      margin-bottom: 0;
    }}
    .mini-card:hover {{
      border-color: rgba(138,180,255,0.55);
    }}
    .mini-card strong {{
      display: block;
      margin-bottom: 6px;
    }}
    .mini-card span {{
      display: block;
      color: var(--muted);
      line-height: 1.45;
    }}
    .mini-meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .mini-type {{
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--accent);
    }}
    .guide {{
      margin-top: 18px;
      border: 1px solid rgba(138,180,255,0.22);
      background: rgba(138,180,255,0.08);
      border-radius: 18px;
      padding: 16px 18px;
    }}
    .guide strong {{
      display: block;
      margin-bottom: 8px;
    }}
    .guide span {{
      color: var(--muted);
      line-height: 1.55;
    }}
    @media (max-width: 720px) {{
      .stats {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .section-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="eyebrow">Output Hub</div>
      <div class="hero-title">
        <h1>{wiki_title}</h1>
        <div class="meta">
          <span class="badge">成果入口页</span>
          <span class="badge">生成日期 {generated_at}</span>
        </div>
      </div>
      <p class="lead">这里汇总当前知识库最容易直接打开的成果页。你可以从这里进入本地浏览页或知识图谱，也能快速确认当前 wiki 的页面规模和图谱状态。</p>
      <div class="stats">
        {stats}
      </div>
    </section>
    <div class="grid">
      {items}
    </div>
    <div class="section-grid">
      <section class="panel">
        <h2>最近更新</h2>
        <p>优先从这些页面继续浏览，通常最能代表当前 wiki 的最新整理结果。</p>
        {recent_pages}
      </section>
      <section class="panel">
        <h2>代表页面</h2>
        <p>优先展示概念页和决策页，帮助你快速理解这个知识库沉淀出的关键结论。</p>
        {featured_pages}
      </section>
    </div>
    <div class="guide">
      <strong>从这里开始</strong>
      <span>先打开本地浏览页阅读页面，再进入知识图谱查看关系。如果你刚导入了新资料，建议重新运行 viewer 和 graph 以刷新成果页。</span>
    </div>
  </main>
</body>
</html>
""".format(
        wiki_title=escape(wiki_title),
        generated_at=escape(generated_at),
        stats="\n".join(stats),
        items="\n".join(items),
        recent_pages=recent_pages_html,
        featured_pages=featured_pages_html,
    )
    target = output_dir / "index.html"
    write_text(target, html)
    return target


def refresh_output_home_if_present(root: Path) -> Path | None:
    output_dir = root / "output"
    viewer_exists = (output_dir / "viewer" / "index.html").exists()
    graph_exists = (output_dir / "graph" / "index.html").exists()
    if not (viewer_exists or graph_exists):
        return None
    return write_output_home(root)


def output_access_lines(root: Path) -> list[str]:
    output_dir = root / "output"
    viewer_exists = (output_dir / "viewer" / "index.html").exists()
    graph_exists = (output_dir / "graph" / "index.html").exists()
    output_home = refresh_output_home_if_present(root)

    lines: list[str] = []
    if output_home is not None:
        lines.append("Output hub: output/index.html")
        lines.append(f"Output hub URI: {file_uri(output_home)}")
        if viewer_exists and not graph_exists:
            lines.append(f"Next: run `python scripts/thinkwiki graph --root {root}` to generate the graph page.")
        elif graph_exists and not viewer_exists:
            lines.append(f"Next: run `python scripts/thinkwiki viewer --root {root}` to generate the viewer page.")
        return lines

    lines.append(f"Next: run `python scripts/thinkwiki viewer --root {root}` to generate the local viewer page.")
    lines.append(f"Next: run `python scripts/thinkwiki graph --root {root}` to generate the knowledge graph page.")
    return lines


def render_template(template: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def load_template(name: str) -> str:
    return read_text(repo_root_from_script() / "templates" / name)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def classify_raw_dir(source_path: Path | None, is_text: bool = False) -> str:
    if is_text or source_path is None:
        return "articles"
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return "papers"
    if suffix in {".epub", ".mobi"}:
        return "books"
    if suffix in {".json", ".jsonl"}:
        return "conversations"
    return "articles"


def parse_frontmatter(text: str) -> Tuple[Dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    frontmatter, body = parts
    lines = frontmatter.splitlines()[1:]
    meta: Dict[str, object] = {}
    current_list_key = None
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list_key:
            meta.setdefault(current_list_key, []).append(line[4:].strip())
            continue
        if ": " in line:
            key, value = line.split(": ", 1)
            meta[key.strip()] = value.strip()
            current_list_key = None
        elif line.endswith(":"):
            key = line[:-1].strip()
            meta[key] = []
            current_list_key = key
    return meta, body


def extract_summary(meta: Dict[str, object], body: str) -> str:
    if meta.get("summary"):
        return str(meta["summary"])
    lines = [line.strip() for line in body.splitlines()]
    for line in lines:
        if not line or line.startswith("#") or line.startswith("- ") or line.startswith("```"):
            continue
        return line[:120]
    return "(no summary)"


def markdown_links(text: str) -> List[str]:
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def is_external_link(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def collect_wiki_pages(root: Path) -> List[Path]:
    pages: List[Path] = []
    for subdir in WIKI_DIRS:
        pages.extend(sorted((root / "wiki" / subdir).glob("*.md")))
    return pages


def normalize_repo_path(root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
        try:
            path = resolved.relative_to(root.resolve())
        except ValueError:
            return resolved.as_posix()
    return path.as_posix().lstrip("./")


def relative_link(from_page: Path, root: Path, target: str) -> str:
    target_path = root / normalize_repo_path(root, target)
    return Path(os.path.relpath(target_path, start=from_page.parent)).as_posix()


def markdown_link_list(from_page: Path, root: Path, targets: Iterable[str]) -> str:
    items = []
    for target in targets:
        normalized = normalize_repo_path(root, target)
        label = Path(normalized).stem.replace("-", " ").replace("_", " ").strip() or normalized
        items.append(f"- [{label}]({relative_link(from_page, root, normalized)})")
    return "\n".join(items)


def frontmatter_list(items: Iterable[str], fallback: str) -> str:
    values = [item for item in items if item]
    if not values:
        values = [fallback]
    return "\n".join(f"  - {item}" for item in values)


def append_log(root: Path, heading: str, lines: Iterable[str]) -> None:
    log_path = root / "log.md"
    current = read_text(log_path).rstrip()
    block = "## " + heading + "\n" + "\n".join(lines)
    if current:
        current += "\n\n" + block
    else:
        current = "# Wiki Log\n\n" + block
    write_text(log_path, current)
