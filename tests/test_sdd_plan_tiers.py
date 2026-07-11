"""Plan-file tier classification, aliases, validation, and migration tests."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.sdd._plan_migration import (
    migrate_legacy_plan_directories,
    plan_legacy_plan_migration,
)
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.links import list_sdd_files, validate_sdd_tree
from sase.sdd.plan_tiers import (
    classify_plan_file,
    _plan_path_alias_candidates,
    read_plan_tier,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_tier_classification_and_alias_candidates(tmp_path: Path) -> None:
    legacy = _write(
        tmp_path / "sdd" / "tales" / "202607" / "declared_epic.md",
        "---\ntier: ' EPIC '\n---\n# Plan\n",
    )

    assert read_plan_tier(legacy) == "epic"
    assert classify_plan_file(legacy) == "epic"
    assert _plan_path_alias_candidates(legacy) == (
        legacy,
        tmp_path / "sdd" / "plans" / "202607" / "declared_epic.md",
    )


def test_list_and_validate_canonical_and_legacy_plan_files(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    _write(
        root / "plans" / "202607" / "epic.md",
        "---\ntier: epic\n---\n# Epic\n",
    )
    _write(root / "plans" / "202607" / "missing.md", "# Missing tier\n")
    _write(
        root / "tales" / "202607" / "override.md",
        "---\ntier: epic\n---\n# Override\n",
    )

    assert [file.name for file in list_sdd_files(root, kind="epics")] == [
        "epic",
        "override",
    ]
    assert [file.name for file in list_sdd_files(root, kind="tales")] == ["missing"]
    assert len(list_sdd_files(root, kind="plans")) == 3

    validation = validate_sdd_tree(str(root))
    assert any(issue.code == "plan-tier" for issue in validation.errors)
    assert any(issue.code == "legacy-plan-directory" for issue in validation.warnings)


def test_migration_moves_backfills_rewrites_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sdd"
    tale = _write(root / "tales" / "202607" / "same.md", "# Tale\n")
    _write(
        root / "epics" / "202607" / "same.md",
        "---\ntier: epic\n---\n# Epic\n",
    )
    _write(
        root / "epics" / "202607" / "broken.md",
        "---\ntier: : bad\n---\n# Broken\n",
    )
    flat = _write(root / "tales" / "flat.md", "# Flat\n")
    epoch = 1_767_225_600  # 2026-01-01 UTC
    os.utime(tale, (epoch, epoch))
    os.utime(flat, (epoch, epoch))
    prompt = _write(
        root / "prompts" / "202607" / "same.md",
        "---\nplan: sdd/epics/202607/same.md\n---\n# Prompt\n",
    )
    _write(root / "tales" / "README.md", "generated\n")
    _write(root / "epics" / "README.md", "generated\n")

    with BeadProject.init(tmp_path, beads_dirname="sdd/beads") as project:
        bead = project.create(
            "Epic",
            IssueType.PLAN,
            design="sdd/epics/202607/same.md",
            tier=BeadTier.EPIC,
        )

    refresh_calls = 0
    original_refresh = BeadProject._refresh_db_from_jsonl

    def counted_refresh(project: BeadProject) -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        original_refresh(project)

    monkeypatch.setattr(BeadProject, "_refresh_db_from_jsonl", counted_refresh)

    planned = plan_legacy_plan_migration(root)
    assert (
        len([action for action in planned if action.source != action.destination]) == 4
    )

    result = migrate_legacy_plan_directories(root)

    tale_destination = root / "plans" / "202607" / "same.md"
    epic_destination = root / "plans" / "202607" / "same_1.md"
    assert tale_destination.exists()
    assert epic_destination.exists()
    assert (root / "plans" / "202607" / "broken.md").read_text(
        encoding="utf-8"
    ) == "---\ntier: : bad\n---\n# Broken\n"
    flat_shard = datetime.fromtimestamp(epoch).strftime("%Y%m")
    assert (root / "plans" / flat_shard / "flat.md").exists()
    tale_frontmatter, _, _ = parse_frontmatter(
        tale_destination.read_text(encoding="utf-8")
    )
    assert tale_frontmatter["tier"] == "tale"
    assert "create_time" in tale_frontmatter
    prompt_frontmatter, _, _ = parse_frontmatter(prompt.read_text(encoding="utf-8"))
    assert prompt_frontmatter["plan"] == "sdd/plans/202607/same_1.md"
    assert not (root / "tales").exists()
    assert not (root / "epics").exists()
    assert result.warnings

    with BeadProject(tmp_path, beads_dirname="sdd/beads") as project:
        assert project.show(bead.id).design == "sdd/plans/202607/same_1.md"
    assert refresh_calls == 1

    rerun = migrate_legacy_plan_directories(root)
    assert rerun.moved == ()
    assert rerun.changed == ()
    assert refresh_calls == 1
