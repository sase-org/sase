"""Section assignment and one-document-one-row coverage for Plans."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui._artifact_tab_model import PaneGroupingModeDecl
from sase.ace.tui.widgets.artifacts.plans_list import build_plan_options
from sase.ace.tui.widgets.artifacts.types import ARTIFACTS_ACCENTS
from tests.ace.tui._artifacts_plans_helpers import _snapshot

_BY_KIND = PaneGroupingModeDecl(id="by_kind", label="Kind", keys=("kind", "tier"))


def test_every_plan_document_appears_in_exactly_one_section(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    options, rows, _known_group_keys = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
        mode=_BY_KIND,
        fold_registry=None,
        accent=ARTIFACTS_ACCENTS["plans"],
    )

    assert [row.kind for row in rows.values()] == ["proposal", "active", "archive"]
    assert all(row.kind not in {"task", "epic", "phase"} for row in rows.values())
    labels = [option.prompt.plain for option in options if option.disabled]
    assert any("Proposals (1)" in label for label in labels)
    assert any("Active plans (1)" in label for label in labels)
    assert any("Archive (1)" in label for label in labels)


def test_active_path_cannot_be_rendered_again_in_archive(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    duplicate = replace(
        snapshot.archive[0],
        match=replace(
            snapshot.archive[0].match,
            plan=replace(
                snapshot.archive[0].match.plan,
                path=snapshot.active[0].document.path,
            ),
        ),
    )
    # The loader owns this invariant; this assertion protects the model seam
    # that later deep-archive reconciliation consumes.
    paths = {item.document.path for item in snapshot.active}
    archive = tuple(
        item
        for item in (*snapshot.archive, duplicate)
        if item.match.plan.path not in paths
    )

    assert [item.match.plan.title for item in archive] == ["Archived rollout"]
