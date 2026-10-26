#!/usr/bin/env python
"""Deterministic documentation check.

Run from the repository root (CI runs it in the ``test`` job):

    python scripts/check_docs.py

It fails on things a person would otherwise have to remember:

- a required entry or contract document is missing;
- a Markdown relative link does not resolve;
- a documented ``lces <command>`` is not a real CLI command;
- a historical plan under ``docs/design/`` lacks the archive banner.

Warnings never turn into passes: they are printed and counted separately.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "var", "projects", "build", "release"}
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
COMMAND = re.compile(r"\blces\s+([a-z][a-z0-9-]+)")
FENCE = re.compile(r"```.*?```", re.DOTALL)

# The single authoritative entry: product, architecture, quality, plus the two
# contract documents those files depend on. Status/history documents are gone;
# gaps live in QUALITY.md §6 and the ADRs.
REQUIRED = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/PRODUCT.md",
    "docs/ARCHITECTURE.md",
    "docs/QUALITY.md",
    "docs/CONTENT_CONTRACTS.md",
    "docs/EVIDENCE_GOVERNANCE.md",
    "schemas/README.md",
)
HISTORICAL_BANNER = "历史计划（已归档）"


def _markdown_files(root: Path = ROOT) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        files.append(path)
    return files


def _cli_commands() -> set[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from content_studio.cli import app  # noqa: PLC0415 - import after sys.path

    names = (command.name or command.callback.__name__ for command in app.registered_commands)
    return {name.replace("_", "-") for name in names}


def _strip_fences(text: str) -> str:
    return FENCE.sub("", text)


def _historical_plans(root: Path = ROOT) -> list[Path]:
    plans = []
    design = root / "docs" / "design"
    if not design.is_dir():
        return plans
    for path in sorted(design.rglob("*.md")):
        name = path.name
        if "acceptance" in name:
            continue
        if name.startswith("course-production-") or "plan" in name:
            plans.append(path)
    return plans


def check(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``; both lists are human-readable lines."""

    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"missing required document: {relative}")

    try:
        commands = _cli_commands()
    except Exception as exc:  # noqa: BLE001 - report, never crash the checker
        errors.append(f"cannot load CLI commands: {exc}")
        commands = set()

    for path in _markdown_files(root):
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"skip non-UTF-8 markdown: {relative.as_posix()}")
            continue
        scan = _strip_fences(text)
        for link in LINK.findall(scan):
            if link.startswith(("http", "#", "mailto", "@")):
                continue
            target = (path.parent / link.split("#")[0]).resolve()
            if not target.exists():
                errors.append(f"broken link in {relative.as_posix()}: {link}")
        if commands:
            for command in COMMAND.findall(scan):
                if command not in commands:
                    errors.append(f"unknown lces command in {relative.as_posix()}: lces {command}")

    for path in _historical_plans(root):
        text = path.read_text(encoding="utf-8")
        if HISTORICAL_BANNER not in text:
            errors.append(
                f"historical plan without archive banner: {path.relative_to(root).as_posix()}"
            )

    return errors, warnings


def main() -> int:
    errors, warnings = check()
    for line in errors:
        print(f"ERROR {line}")
    for line in warnings:
        print(f"WARN  {line}")
    files = len(_markdown_files())
    print(f"docs: {files} markdown files, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
