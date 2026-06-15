#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils import append_log, collect_wiki_pages, find_repo_root, is_external_link, markdown_links, parse_frontmatter, read_text, today_str, write_text


def normalize_sources(meta: dict[str, object]) -> list[str]:
    raw = meta.get("sources", [])
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if raw:
        return [str(raw)]
    return []


def add_node(nodes: dict[str, dict[str, str]], node_id: str, label: str, node_type: str) -> None:
    existing = nodes.get(node_id)
    if existing is None:
        nodes[node_id] = {"id": node_id, "label": label, "type": node_type}
        return
    # Upgrade placeholder/raw classifications when we later discover a wiki-backed node type.
    if existing["type"] in {"raw", "file", "page"} and node_type not in {existing["type"], "raw"}:
        existing["type"] = node_type
    if (existing["label"] == Path(node_id).stem or existing["type"] == "raw") and label:
        existing["label"] = label


def add_edge(
    edges: list[dict[str, str]],
    seen_edges: set[tuple[str, str, str]],
    source: str,
    target: str,
    edge_type: str,
) -> None:
    edge_key = (source, target, edge_type)
    if edge_key not in seen_edges:
        seen_edges.add(edge_key)
        edges.append({"source": source, "target": target, "type": edge_type})


def node_type_for_path(node_id: str) -> str:
    if node_id.startswith("raw/"):
        return "raw"
    if node_id.startswith("wiki/"):
        parent_name = Path(node_id).parent.name
        if parent_name.endswith("s"):
            return parent_name[:-1]
        return "page"
    return "file"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build graph data from wiki pages.")
    parser.add_argument("--root", default=".", help="Wiki root path")
    args = parser.parse_args()

    root = find_repo_root(Path(args.root))
    pages = collect_wiki_pages(root)
    page_ids = {page.resolve(): page.relative_to(root).as_posix() for page in pages}
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for page in pages:
        meta, body = parse_frontmatter(read_text(page))
        node_id = page.relative_to(root).as_posix()
        page_type = str(meta.get("type") or page.parent.name[:-1])
        add_node(nodes, node_id, str(meta.get("title") or page.stem), page_type)

        for source in normalize_sources(meta):
            source_path = (root / source).resolve()
            source_id = source_path.relative_to(root).as_posix() if source_path.is_relative_to(root) else source
            source_type = node_type_for_path(source_id)
            add_node(nodes, source_id, Path(source_id).stem, source_type)
            edge_type = "cites" if source_type == "raw" else "includes" if page_type == "topic" else "references"
            add_edge(edges, seen_edges, node_id, source_id, edge_type)

        for link in markdown_links(body):
            if is_external_link(link):
                continue
            target = (page.parent / link).resolve()
            target_id = page_ids.get(target)
            if target_id:
                add_edge(edges, seen_edges, node_id, target_id, "links_to")

    graph_nodes = sorted(nodes.values(), key=lambda node: node["id"])
    graph_edges = sorted(edges, key=lambda edge: (edge["source"], edge["type"], edge["target"]))
    graph = {"generated_at": today_str(), "nodes": graph_nodes, "edges": graph_edges}
    graph_dir = root / "output" / "graph"
    write_text(graph_dir / "graph.json", json.dumps(graph, ensure_ascii=False, indent=2))

    lines = ["# Knowledge Graph", "", f"- Nodes: {len(graph_nodes)}", f"- Edges: {len(graph_edges)}", "", "## Nodes"]
    lines.extend(f"- {node['type']}: {node['label']} ({node['id']})" for node in graph_nodes)
    lines.extend(["", "## Edges"])
    lines.extend(f"- {edge['source']} --{edge['type']}--> {edge['target']}" for edge in graph_edges)
    write_text(graph_dir / "graph.md", "\n".join(lines))

    append_log(root, f"[{today_str()}] graph | {len(graph_nodes)} nodes, {len(graph_edges)} edges", [
        "- output: output/graph/graph.json"
    ])
    print(f"Built graph with {len(graph_nodes)} nodes and {len(graph_edges)} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
