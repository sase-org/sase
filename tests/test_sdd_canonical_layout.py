"""Regression audit for the canonical repository plan layout."""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_PLAN_PATH = re.compile(r"(?:@?sdd|\.sase/sdd)/(?:tales|epics)/")


def _matches(paths: list[Path]) -> list[str]:
    matches: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if _LEGACY_PLAN_PATH.search(text):
            matches.append(path.relative_to(_ROOT).as_posix())
    return matches


def test_active_sources_and_docs_use_only_canonical_plan_paths() -> None:
    operational_sources = [
        _ROOT / ".gitignore",
        _ROOT / "Justfile",
        _ROOT / ".github" / "workflows" / "ci.yml",
        _ROOT / "README.md",
        _ROOT / "src" / "sase" / "default_config.yml",
        *(_ROOT / "src" / "sase" / "sdd").glob("*.py"),
        _ROOT / "src" / "sase" / "main" / "parser_sdd.py",
        _ROOT / "src" / "sase" / "main" / "sdd_handler.py",
        _ROOT / "src" / "sase" / "axe" / "run_agent_exec_plan_sdd.py",
        _ROOT / "src" / "sase" / "axe" / "run_agent_exec_plan_accept.py",
        _ROOT / "src" / "sase" / "llm_provider" / "commit_finalizer_git.py",
        _ROOT / "src" / "sase" / "ace" / "tui" / "models" / "_diff_badge.py",
    ]
    current_docs = [
        path
        for path in (_ROOT / "docs").rglob("*.md")
        if "images" not in path.relative_to(_ROOT / "docs").parts
        and path.name != "perf_runbook.md"
    ]

    assert _matches([*operational_sources, *current_docs]) == []


def test_operational_tests_keep_only_the_explicit_stale_link_rejection() -> None:
    matches = _matches(list((_ROOT / "tests").rglob("*.py")))

    assert matches == ["tests/main/test_sdd_validate_handler.py"]
