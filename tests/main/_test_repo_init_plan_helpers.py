"""Shared helpers for ``sase repo init`` planner tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def make_plan_args(path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "path": str(path),
        "check": False,
        "diff": False,
        "no_commit": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def mark_plan_project(path: Path, *, managed: bool = True) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if managed:
        config = path / "sase" / "sase.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("is_sase_managed: true\n", encoding="utf-8")
