"""Shared helpers for ``sase plan links`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest


@pytest.fixture
def mark_tmp_path_as_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir(exist_ok=True)


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "plan_links_subcommand": "validate",
        "path": None,
        "json": False,
        "quiet": False,
        "strict": False,
        "show_warnings": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def write_pair(root: Path, name: str = "linked") -> tuple[Path, Path]:
    prompt = root / "plans" / "202605" / "prompts" / f"{name}.md"
    plan = root / "plans" / "202605" / f"{name}.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        f"---\nplan: sdd/plans/202605/{name}.md\n---\n# Prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        f"---\nprompt: sdd/plans/202605/prompts/{name}.md\ntier: tale\n---\n# Plan\n",
        encoding="utf-8",
    )
    return prompt, plan
