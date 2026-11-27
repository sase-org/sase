"""Direct coverage locking the ``preview_waves`` / ``sase bead work`` contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan_helpers import (
    linked_epic_belongs_to_other_plan,
    preview_waves,
)
from sase.bead.cli_work_from_plan_types import PlanFileWorkError
from sase.bead.model import BeadTier, Issue, IssueType


@dataclass(frozen=True, slots=True)
class _Phase:
    id: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    phases: tuple[_Phase, ...]


def test_preview_waves_layers_a_valid_dag() -> None:
    plan = _Plan(
        phases=(
            _Phase("core", ()),
            _Phase("cli", ("core",)),
            _Phase("verify", ("core", "cli")),
        )
    )

    assert preview_waves(plan) == (("core",), ("cli",), ("verify",))


def test_preview_waves_raises_plan_file_work_error_on_cycle() -> None:
    plan = _Plan(phases=(_Phase("a", ("b",)), _Phase("b", ("a",))))

    with pytest.raises(
        PlanFileWorkError,
        match="validated epic plan contains a dependency cycle",
    ):
        preview_waves(plan)


def test_linked_epic_without_design_is_not_foreign(tmp_path: Path) -> None:
    from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore

    plan = tmp_path / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    store = SddStore(
        storage=SDD_STORAGE_IN_TREE,
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path,
    )
    issue = Issue(
        id="sase-1",
        title="Own epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="",
    )

    assert (
        linked_epic_belongs_to_other_plan(
            issue,
            archived_path=plan,
            store=store,
            workspace_dir=tmp_path,
        )
        is False
    )


def test_linked_epic_with_other_plan_design_is_foreign(tmp_path: Path) -> None:
    from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore

    plan = tmp_path / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    store = SddStore(
        storage=SDD_STORAGE_IN_TREE,
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path,
    )
    issue = Issue(
        id="sase-1",
        title="Other epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plan:202608/other.md",
    )

    assert (
        linked_epic_belongs_to_other_plan(
            issue,
            archived_path=plan,
            store=store,
            workspace_dir=tmp_path,
        )
        is True
    )
