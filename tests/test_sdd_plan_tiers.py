"""Canonical plan-file tier classification and validation tests."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.links import _list_sdd_files, validate_sdd_tree
from sase.sdd.plan_tiers import (
    classify_plan_file,
    read_plan_tier,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_tier_classification_uses_frontmatter(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "sdd" / "plans" / "202607" / "declared_epic.md",
        "---\ntier: ' EPIC '\n---\n# Plan\n",
    )

    assert read_plan_tier(plan) == "epic"
    assert classify_plan_file(plan) == "epic"


def test_list_and_validate_canonical_plan_files(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    _write(
        root / "plans" / "202607" / "epic.md",
        "---\ntier: epic\n---\n# Epic\n",
    )
    _write(root / "plans" / "202607" / "missing.md", "# Missing tier\n")

    assert [file.name for file in _list_sdd_files(root, kind="epics")] == ["epic"]
    assert [file.name for file in _list_sdd_files(root, kind="tales")] == ["missing"]
    assert len(_list_sdd_files(root, kind="plans")) == 2

    validation = validate_sdd_tree(str(root))
    assert any(issue.code == "plan-tier" for issue in validation.errors)
