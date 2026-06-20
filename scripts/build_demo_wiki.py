#!/usr/bin/env python3
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


ROOT_FILES = {
    ".wiki-schema.md": "# marker\n",
    "index.md": "# Demo Wiki\n",
    "overview.md": "# Overview\n\nThis demo wiki powers the README screenshots.\n",
    "purpose.md": "# Purpose\n\nShow real viewer and graph outputs for ThinkWiki.\n",
    "log.md": "# Log\n",
}

RAW_FILES = {
    "platform-spec": "# Platform Spec\n\nExecution specs coordinate people, tools, and context.\n",
    "eval-loops": "# Eval Loops\n\nEvaluation loops connect product metrics, prompts, and review workflows.\n",
    "review-checklist": "# Review Checklist\n\nHuman review keeps model behavior aligned with policy and delivery goals.\n",
}

WIKI_FILES = {
    "wiki/sources/platform-spec.md": """
    ---
    title: Platform Spec
    type: source
    created: 2026-06-19
    updated: 2026-06-19
    summary: A source page describing why execution specs and context must be treated as one delivery system.
    sources:
      - raw/articles/platform-spec.md
    tags:
      - source
      - platform
    confidence: extracted
    status: active
    ---

    # Platform Spec

    ## Summary

    Execution specs coordinate people, tools, and context into one delivery system instead of isolated prompts.

    ## Connections

    - [AI Native Team](../concepts/ai-native-team.md)
    - [Model Platform](../topics/model-platform.md)
    - [Execution Spec](../concepts/execution-spec.md)
    """,
    "wiki/sources/eval-loops.md": """
    ---
    title: Eval Loop Notes
    type: source
    created: 2026-06-19
    updated: 2026-06-19
    summary: Notes from an internal workshop on evaluation loops, review lanes, and release confidence.
    sources:
      - raw/articles/eval-loops.md
    tags:
      - source
      - eval
    confidence: extracted
    status: active
    ---

    # Eval Loop Notes

    ## Summary

    Evaluation loops turn prompts into an observable delivery system by connecting tests, feedback, and release gates.

    ## Connections

    - [Eval Loops](../topics/eval-loops.md)
    - [Context Budget](../decisions/context-budget.md)
    """,
    "wiki/sources/review-checklist.md": """
    ---
    title: Review Checklist
    type: source
    created: 2026-06-19
    updated: 2026-06-19
    summary: A source page explaining how human review, acceptance criteria, and escalation paths fit together.
    sources:
      - raw/articles/review-checklist.md
    tags:
      - source
      - review
    confidence: extracted
    status: active
    ---

    # Review Checklist

    ## Summary

    Human review closes the loop between generated output, execution policy, and customer-facing quality.

    ## Connections

    - [AI Native Team](../concepts/ai-native-team.md)
    - [Execution Policy](../decisions/execution-policy.md)
    """,
    "wiki/topics/model-platform.md": """
    ---
    title: Model Platform
    type: topic
    created: 2026-06-19
    updated: 2026-06-19
    summary: Topic page for reusable context, evaluation workflows, and internal tooling.
    sources:
      - wiki/sources/platform-spec.md
      - wiki/sources/eval-loops.md
    tags:
      - topic
      - platform
    confidence: mixed
    status: active
    ---

    # Model Platform

    ## Summary

    A model platform combines reusable prompts, context policies, evaluation loops, and internal tooling.

    ## Included Sources

    - [Platform Spec](../sources/platform-spec.md)
    - [Eval Loop Notes](../sources/eval-loops.md)
    - [Execution Spec](../concepts/execution-spec.md)
    """,
    "wiki/topics/eval-loops.md": """
    ---
    title: Eval Loops
    type: topic
    created: 2026-06-19
    updated: 2026-06-19
    summary: Topic page about review lanes, regression checks, and feedback loops for model releases.
    sources:
      - wiki/sources/eval-loops.md
      - wiki/sources/review-checklist.md
    tags:
      - topic
      - eval
    confidence: mixed
    status: active
    ---

    # Eval Loops

    ## Summary

    Eval loops connect prompts, acceptance criteria, automated checks, and human review before release.

    ## Included Sources

    - [Eval Loop Notes](../sources/eval-loops.md)
    - [Review Checklist](../sources/review-checklist.md)
    - [Context Budget](../decisions/context-budget.md)
    """,
    "wiki/concepts/ai-native-team.md": """
    ---
    title: AI Native Team
    type: concept
    created: 2026-06-19
    updated: 2026-06-19
    summary: A team model that treats models, context, and workflow as one operating system for delivery.
    sources:
      - wiki/sources/platform-spec.md
      - wiki/topics/model-platform.md
      - wiki/topics/eval-loops.md
    tags:
      - concept
      - team
    confidence: verified
    status: active
    ---

    # AI Native Team

    ## Summary

    AI native teams are organized around executable specs, reusable context, and human review loops rather than isolated tools.

    ## Details

    The operating model depends on model platform capabilities, review lanes, and explicit execution policy.

    ## Connections

    - [Model Platform](../topics/model-platform.md)
    - [Eval Loops](../topics/eval-loops.md)
    - [Execution Policy](../decisions/execution-policy.md)
    - [Execution Spec](../concepts/execution-spec.md)
    """,
    "wiki/concepts/execution-spec.md": """
    ---
    title: Execution Spec
    type: concept
    created: 2026-06-19
    updated: 2026-06-19
    summary: A reusable specification that binds task framing, context, policy, and review expectations together.
    sources:
      - wiki/sources/platform-spec.md
      - wiki/sources/review-checklist.md
    tags:
      - concept
      - spec
    confidence: verified
    status: active
    ---

    # Execution Spec

    ## Summary

    Execution specs define what the model should do, which context it may use, and how review should validate the result.

    ## Connections

    - [AI Native Team](../concepts/ai-native-team.md)
    - [Execution Policy](../decisions/execution-policy.md)
    - [Context Budget](../decisions/context-budget.md)
    """,
    "wiki/decisions/execution-policy.md": """
    ---
    title: Execution Policy
    type: decision
    created: 2026-06-19
    updated: 2026-06-19
    summary: Decision page that recommends treating context and execution as first-class platform capabilities.
    sources:
      - wiki/concepts/ai-native-team.md
      - wiki/concepts/execution-spec.md
    tags:
      - decision
    confidence: verified
    status: active
    ---

    # Execution Policy

    ## Summary

    Teams should adopt execution specs and context review as platform capabilities instead of ad hoc prompt work.

    ## Reasoning

    The policy links delivery quality to reusable context, evaluation loops, and review checkpoints.
    """,
    "wiki/decisions/context-budget.md": """
    ---
    title: Context Budget
    type: decision
    created: 2026-06-19
    updated: 2026-06-19
    summary: Decision page that limits context sprawl and requires explicit budget ownership in prompts and tools.
    sources:
      - wiki/sources/eval-loops.md
      - wiki/concepts/execution-spec.md
    tags:
      - decision
      - context
    confidence: verified
    status: active
    ---

    # Context Budget

    ## Summary

    Each delivery flow should define a context budget so prompts, retrieval, and review steps stay observable and affordable.
    """,
    "wiki/syntheses/delivery-system.md": """
    ---
    title: Delivery System Synthesis
    type: synthesis
    created: 2026-06-19
    updated: 2026-06-19
    summary: Synthesis page summarizing how source, topic, concept, and decision pages reinforce one another.
    sources:
      - wiki/sources/platform-spec.md
      - wiki/sources/eval-loops.md
      - wiki/concepts/ai-native-team.md
      - wiki/decisions/execution-policy.md
    tags:
      - synthesis
    confidence: mixed
    status: active
    ---

    # Delivery System Synthesis

    ## Findings

    - Platform, concept, and decision pages align on treating context and execution as one delivery system.
    - Review loops and context budgets make the operating model observable enough to scale.
    """,
    "wiki/queries/what-makes-ai-native-team.md": """
    ---
    title: What Makes an AI Native Team
    type: query
    created: 2026-06-19
    updated: 2026-06-19
    summary: Saved query summarizing the defining traits of an AI native delivery team.
    sources:
      - wiki/concepts/ai-native-team.md
      - wiki/decisions/execution-policy.md
    tags:
      - query
    confidence: mixed
    status: active
    ---

    # What Makes an AI Native Team

    ## Answer

    AI native teams treat model behavior, execution specs, context policy, and review loops as one coordinated delivery system.

    ## Consulted Pages

    - [AI Native Team](../concepts/ai-native-team.md)
    - [Execution Policy](../decisions/execution-policy.md)
    """,
}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def build_demo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)

    for relative in [
        "wiki/sources",
        "wiki/topics",
        "wiki/concepts",
        "wiki/decisions",
        "wiki/syntheses",
        "wiki/queries",
        "raw/articles",
        "normalized/articles",
        "output/graph",
        "output/viewer",
    ]:
        (root / relative).mkdir(parents=True, exist_ok=True)

    for name, content in ROOT_FILES.items():
        (root / name).write_text(content, encoding="utf-8")

    for slug, content in RAW_FILES.items():
        write_text(root / "raw" / "articles" / f"{slug}.md", content)
        write_text(root / "normalized" / "articles" / f"{slug}.md", content)

    for relative, content in WIKI_FILES.items():
        write_text(root / relative, content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the demo wiki used for README screenshots.")
    parser.add_argument(
        "--root",
        default="/Users/david/Desktop/ThinkWiki/docs/demo-wiki",
        help="Target demo wiki root",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    build_demo(root)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
