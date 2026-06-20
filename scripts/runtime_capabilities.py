#!/usr/bin/env python3
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

Importer = Callable[[str], object]

CORE_RUNTIME_GROUPS: dict[str, dict[str, str]] = {
    "core": {
        "markitdown": "generic document conversion",
    },
    "web": {
        "bs4": "webpage parsing",
        "markdownify": "HTML to Markdown conversion",
    },
    "pdf": {
        "pdfminer": "PDF text extraction",
        "pdfplumber": "PDF layout and table extraction",
    },
    "docx": {
        "mammoth": "DOCX conversion",
    },
    "xlsx": {
        "pandas": "XLSX parsing",
        "openpyxl": "XLSX workbook engine",
    },
    "xls": {
        "pandas": "legacy XLS parsing",
        "xlrd": "legacy XLS workbook engine",
    },
    "pptx": {
        "pptx": "PPTX conversion",
    },
}

CAPABILITY_LABELS = {
    "core": "Core runtime",
    "web": "Web import",
    "pdf": "PDF import",
    "docx": "DOCX import",
    "xlsx": "XLSX import",
    "xls": "XLS import",
    "pptx": "PPTX import",
}

CAPABILITY_ORDER = ("core", "web", "pdf", "docx", "xlsx", "xls", "pptx")

SOURCE_SUFFIX_TO_CAPABILITY = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".pptx": "pptx",
}


def default_importer(module_name: str) -> object:
    return importlib.import_module(module_name)


def missing_modules_for_group(group_name: str, importer: Importer | None = None) -> list[dict[str, str]]:
    importer = importer or default_importer
    missing: list[dict[str, str]] = []
    for module_name, purpose in CORE_RUNTIME_GROUPS[group_name].items():
        try:
            importer(module_name)
        except Exception as exc:  # pragma: no cover - exercised via subprocess/import state
            missing.append({
                "module": module_name,
                "purpose": purpose,
                "reason": str(exc),
            })
    return missing


def runtime_report(importer: Importer | None = None) -> dict[str, list[dict[str, str]]]:
    return {
        group_name: missing_modules_for_group(group_name, importer)
        for group_name in CAPABILITY_ORDER
    }


def office_runtime_ready(importer: Importer | None = None) -> bool:
    report = runtime_report(importer)
    return all(not report[group_name] for group_name in CAPABILITY_ORDER)


def capability_for_suffix(suffix: str) -> str | None:
    return SOURCE_SUFFIX_TO_CAPABILITY.get(suffix.lower())


def missing_modules_for_source(source_path: Path, importer: Importer | None = None) -> list[dict[str, str]]:
    capability = capability_for_suffix(source_path.suffix)
    if not capability:
        return []
    report = runtime_report(importer)
    return [*report["core"], *report[capability]]


def summarize_missing_modules(items: list[dict[str, str]]) -> str:
    return ", ".join(item["module"] for item in items)


def missing_dependency_message(source_path: Path, items: list[dict[str, str]]) -> str:
    capability = capability_for_suffix(source_path.suffix)
    label = CAPABILITY_LABELS.get(capability or "core", "Document conversion")
    modules = summarize_missing_modules(items)
    return (
        f"{label} dependencies are not ready for `{source_path.name}`. "
        f"Missing Python modules: {modules}. "
        "Run `python scripts/thinkwiki bootstrap` again after fixing package index or network access, "
        "or install the runtime packages declared in `requirements.txt`."
    )
