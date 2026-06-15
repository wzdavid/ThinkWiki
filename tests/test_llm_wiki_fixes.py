from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path("/Users/david/Desktop/llm-wiki")


def run_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


class LlmWikiFixesTest(unittest.TestCase):
    def test_graph_keeps_wiki_source_node_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "wiki"
            write_text(root / ".wiki-schema.md", "# marker")
            (root / "raw" / "articles").mkdir(parents=True, exist_ok=True)
            (root / "output" / "graph").mkdir(parents=True, exist_ok=True)
            (root / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
            (root / "wiki" / "topics").mkdir(parents=True, exist_ok=True)
            (root / "raw" / "articles" / "platform.docx").write_text("raw", encoding="utf-8")
            write_text(
                root / "wiki" / "sources" / "platform-spec.md",
                """
                ---
                title: Platform Spec
                type: source
                created: 2026-06-15
                updated: 2026-06-15
                summary: Source summary.
                sources:
                  - raw/articles/platform.docx
                tags:
                  - source
                confidence: extracted
                status: active
                ---

                # Platform Spec

                ## Summary

                Source summary.
                """,
            )
            write_text(
                root / "wiki" / "topics" / "platform.md",
                """
                ---
                title: Platform
                type: topic
                created: 2026-06-15
                updated: 2026-06-15
                summary: Topic summary.
                sources:
                  - wiki/sources/platform-spec.md
                tags:
                  - topic
                confidence: mixed
                status: active
                ---

                # Platform

                ## Included Sources

                - [Platform Spec](../sources/platform-spec.md)
                """,
            )

            run_script("build_graph.py", "--root", str(root))
            graph = json.loads((root / "output" / "graph" / "graph.json").read_text(encoding="utf-8"))
            node_by_id = {node["id"]: node for node in graph["nodes"]}

            self.assertEqual(node_by_id["wiki/sources/platform-spec.md"]["type"], "source")
            self.assertIn(
                {
                    "source": "wiki/topics/platform.md",
                    "target": "wiki/sources/platform-spec.md",
                    "type": "includes",
                },
                graph["edges"],
            )

    def test_directory_ingest_updates_topic_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "wiki"
            source_dir = Path(tmp_dir) / "docs"
            write_text(source_dir / "platform" / "a.md", "# A\n\nAlpha summary.")
            write_text(source_dir / "platform" / "b.md", "# B\n\nBeta summary.")

            run_script("init_wiki.py", "--root", str(root), "--title", "Test Wiki")
            run_script("ingest.py", "--root", str(root), "--source", str(source_dir))

            topic_text = (root / "wiki" / "topics" / "platform.md").read_text(encoding="utf-8")
            self.assertIn("wiki/sources/a.md", topic_text)
            self.assertIn("wiki/sources/b.md", topic_text)
            self.assertIn("[a](../sources/a.md)", topic_text)
            self.assertIn("[b](../sources/b.md)", topic_text)

    def test_viewer_distinguishes_page_links_and_file_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "wiki"
            write_text(root / ".wiki-schema.md", "# marker")
            (root / "raw" / "articles").mkdir(parents=True, exist_ok=True)
            (root / "output" / "viewer").mkdir(parents=True, exist_ok=True)
            (root / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
            (root / "wiki" / "topics").mkdir(parents=True, exist_ok=True)
            (root / "raw" / "articles" / "platform.docx").write_text("raw", encoding="utf-8")

            write_text(
                root / "wiki" / "topics" / "platform.md",
                """
                ---
                title: Platform
                type: topic
                created: 2026-06-15
                updated: 2026-06-15
                summary: Topic summary.
                sources:
                  - wiki/sources/platform-spec.md
                tags:
                  - topic
                confidence: mixed
                status: active
                ---

                # Platform
                """,
            )
            write_text(
                root / "wiki" / "sources" / "platform-spec.md",
                """
                ---
                title: Platform Spec
                type: source
                created: 2026-06-15
                updated: 2026-06-15
                summary: Source summary.
                sources:
                  - raw/articles/platform.docx
                tags:
                  - source
                confidence: extracted
                status: active
                ---

                # Platform Spec

                ## Connections

                - [Platform Topic](../topics/platform.md)
                - [Raw Doc](../../raw/articles/platform.docx)
                """,
            )

            run_script("build_viewer.py", "--root", str(root))
            payload = json.loads((root / "output" / "viewer" / "viewer.json").read_text(encoding="utf-8"))
            page = next(item for item in payload["pages"] if item["id"] == "wiki/sources/platform-spec.md")
            section = next(item for item in page["sections"] if item["title"] == "Connections")

            self.assertIn(
                {
                    "label": "platform.md",
                    "raw": "../topics/platform.md",
                    "targetId": "wiki/topics/platform.md",
                    "href": "",
                },
                section["links"],
            )
            self.assertIn(
                {
                    "label": "platform.docx",
                    "raw": "../../raw/articles/platform.docx",
                    "targetId": "",
                    "href": "../../raw/articles/platform.docx",
                },
                section["links"],
            )


if __name__ == "__main__":
    unittest.main()
