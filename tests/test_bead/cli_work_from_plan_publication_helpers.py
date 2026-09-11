"""Shared helpers for plan-file publication tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def linked_bead_id(plan_path: Path) -> str:
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan_path.read_text(encoding="utf-8")
    )
    return str(frontmatter["bead_id"])
