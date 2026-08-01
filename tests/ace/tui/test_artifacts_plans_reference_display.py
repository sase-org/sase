"""Stable reference coverage for plan document rows."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase import artifact_ref_entries
from sase.ace.tui.widgets.artifacts.plans_list import build_plan_options
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def test_active_row_preserves_owning_bead_design_reference(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _options, rows = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
    )
    active = next(row for row in rows.values() if row.kind == "active")
    archived = next(row for row in rows.values() if row.kind == "archive")

    assert (
        artifact_ref_entries.design_reference_for_plan_row(active)
        == "plans:202607/active.md"
    )
    assert (
        artifact_ref_entries.design_reference_for_plan_row(archived)
        == "plans:202607/archive.md"
    )


def test_active_row_reference_is_canonicalized_from_document_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    _options, rows = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
    )
    active = next(row for row in rows.values() if row.kind == "active")
    monkeypatch.setattr(
        artifact_ref_entries,
        "canonicalize_artifact_ref",
        lambda path, *, context: "plans:202607/active.md",
    )

    reference = artifact_ref_entries.reference_for_entry_target(
        "plans",
        ("plan", "alpha", "active", active.active.document.path),  # type: ignore[union-attr]
        context=SimpleNamespace(),
        row=active,
    )

    assert reference == "plans:202607/active.md"
