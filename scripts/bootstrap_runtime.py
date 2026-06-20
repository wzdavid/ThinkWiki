#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import venv
from pathlib import Path

from runtime_capabilities import CAPABILITY_LABELS, CAPABILITY_ORDER

PYPI_SIMPLE_URL = "https://pypi.org/simple"
DEFAULT_PIP_TIMEOUT = os.environ.get("THINKWIKI_PIP_TIMEOUT", "300")
DEFAULT_PIP_RETRIES = os.environ.get("THINKWIKI_PIP_RETRIES", "2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the ThinkWiki runtime environment.")
    parser.add_argument("--repo-root", default="", help="Optional repository root. Defaults to the skill root.")
    parser.add_argument("--check", action="store_true", help="Only check whether the runtime is ready.")
    parser.add_argument("--quiet", action="store_true", help="Reduce bootstrap output.")
    return parser.parse_args()


def infer_repo_root(repo_root_arg: str) -> Path:
    if repo_root_arg:
        return Path(repo_root_arg).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def venv_python_candidates(repo_root: Path) -> list[Path]:
    windows_candidates = [
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root / ".venv" / "Scripts" / "python",
    ]
    unix_candidates = [
        repo_root / ".venv" / "bin" / "python3",
        repo_root / ".venv" / "bin" / "python",
    ]
    return windows_candidates + unix_candidates if os.name == "nt" else unix_candidates + windows_candidates


def venv_python(repo_root: Path) -> Path:
    for candidate in venv_python_candidates(repo_root):
        if candidate.exists():
            return candidate
    return venv_python_candidates(repo_root)[0]


def requirements_path(repo_root: Path) -> Path:
    return repo_root / "requirements.txt"


def runtime_probe_script(repo_root: Path) -> str:
    scripts_dir = (repo_root / "scripts").resolve()
    return "\n".join([
        "import json",
        "import sys",
        f"sys.path.insert(0, {str(scripts_dir)!r})",
        "from runtime_capabilities import runtime_report",
        "report = runtime_report()",
        "print(json.dumps(report))",
        "sys.exit(0 if all(not report[name] for name in report) else 1)",
    ])


def runtime_report_with_python(repo_root: Path, python_bin: Path) -> tuple[bool, dict[str, list[dict[str, str]]]]:
    if not python_bin.exists():
        return False, {}
    result = subprocess.run(
        [str(python_bin), "-c", runtime_probe_script(repo_root)],
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        report = {}
    return result.returncode == 0, report


def runtime_ready_with_python(repo_root: Path, python_bin: Path) -> bool:
    ready, _report = runtime_report_with_python(repo_root, python_bin)
    return ready


def format_missing_report(report: dict[str, list[dict[str, str]]]) -> str:
    lines: list[str] = []
    for capability in CAPABILITY_ORDER:
        missing = report.get(capability, [])
        if not missing:
            continue
        modules = ", ".join(item["module"] for item in missing)
        lines.append(f"{CAPABILITY_LABELS[capability]} missing: {modules}")
    return "; ".join(lines) if lines else "runtime dependencies are incomplete"


def create_venv(repo_root: Path, quiet: bool) -> Path:
    venv_dir = repo_root / ".venv"
    if not venv_dir.exists():
        if not quiet:
            print(f"[ThinkWiki] Creating runtime venv at {venv_dir}")
        builder = venv.EnvBuilder(with_pip=True, clear=False, upgrade=False)
        builder.create(venv_dir)
    python_bin = venv_python(repo_root)
    if not python_bin.exists():
        raise SystemExit(f"Failed to create runtime python: {python_bin}")
    return python_bin


def configured_index_urls() -> list[str]:
    urls: list[str] = []
    configured = os.environ.get("THINKWIKI_PIP_INDEX_URL", "").strip()
    if configured:
        urls.append(configured)
    if PYPI_SIMPLE_URL not in urls:
        urls.append(PYPI_SIMPLE_URL)
    return urls


def install_requirements(repo_root: Path, python_bin: Path, quiet: bool) -> None:
    req_path = requirements_path(repo_root)
    if not req_path.exists():
        raise SystemExit(f"requirements.txt not found: {req_path}")
    if not quiet:
        print(f"[ThinkWiki] Installing runtime dependencies from {req_path}")
    base_cmd = [
        str(python_bin),
        "-m",
        "pip",
        "install",
        "-r",
        str(req_path),
        "--timeout",
        DEFAULT_PIP_TIMEOUT,
        "--retries",
        DEFAULT_PIP_RETRIES,
    ]
    if quiet:
        base_cmd.extend(["--disable-pip-version-check", "--quiet"])
    commands: list[tuple[str, list[str]]] = [("default package index", base_cmd)]
    for index_url in configured_index_urls():
        commands.append((f"fallback index {index_url}", [*base_cmd, "--index-url", index_url]))
    last_error = "pip install failed"
    for index, (label, install_cmd) in enumerate(commands):
        if not quiet and index > 0:
            print(f"[ThinkWiki] Default package index failed, retrying via {label.split()[-1]}")
        result = subprocess.run(install_cmd, capture_output=quiet, text=True)
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout or "pip install failed").strip()
    raise SystemExit(f"Failed to install ThinkWiki runtime dependencies: {last_error}")


def ensure_runtime(repo_root: Path, quiet: bool) -> Path:
    python_bin = create_venv(repo_root, quiet)
    if runtime_ready_with_python(repo_root, python_bin):
        if not quiet:
            print(f"[ThinkWiki] Runtime ready: {python_bin}")
        return python_bin
    install_requirements(repo_root, python_bin, quiet)
    ready, report = runtime_report_with_python(repo_root, python_bin)
    if not ready:
        raise SystemExit(
            "ThinkWiki runtime bootstrap completed, but required modules are still unavailable: "
            f"{format_missing_report(report)}"
        )
    if not quiet:
        print(f"[ThinkWiki] Runtime ready: {python_bin}")
    return python_bin


def check_runtime(repo_root: Path) -> int:
    python_bin = venv_python(repo_root)
    ready, report = runtime_report_with_python(repo_root, python_bin)
    if ready:
        print(f"READY {python_bin}")
        return 0
    print(f"MISSING {python_bin} :: {format_missing_report(report)}")
    return 1


def main() -> int:
    args = parse_args()
    repo_root = infer_repo_root(args.repo_root)
    if args.check:
        return check_runtime(repo_root)
    ensure_runtime(repo_root, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
