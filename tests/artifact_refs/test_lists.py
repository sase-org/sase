from __future__ import annotations

from pathlib import Path

import pytest

from sase import artifact_ref_lists
from sase.artifact_refs import (
    artifact_ref_list_display_lines,
    normalize_artifact_ref_list,
    resolve_artifact_ref_list,
)

from .helpers import context as make_context


def test_normalize_deduplicates_in_first_occurrence_order() -> None:
    assert normalize_artifact_ref_list(
        [
            "plans:first.md",
            "bead:sase-bb",
            "plans:first.md",
            "plans:second.md",
        ]
    ) == (
        "plans:first.md",
        "bead:sase-bb",
        "plans:second.md",
    )


def test_resolve_and_display_reference_list(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    plan = context.document_roots[1].root / "resolved.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Resolved\n", encoding="utf-8")

    entries = resolve_artifact_ref_list(
        ["plans:resolved.md", "plans:missing.md"],
        context=context,
    )

    assert [entry.rendered for entry in entries] == [
        "plans:resolved.md",
        "plans:missing.md",
    ]
    assert [entry.resolution.status for entry in entries] == ["exact", "missing"]
    assert artifact_ref_list_display_lines(entries) == (
        "plans:resolved.md",
        f"→ {plan}",
        "plans:missing.md",
        "→ (unresolved: no plan file found)",
    )
    assert entries[0].to_wire()["resolution"] == {
        "schema_version": 4,
        "status": "exact",
        "rendered": "plans:resolved.md",
        "locator": None,
        "resolved_path": str(plan),
        "candidates": [str(plan)],
    }


def test_list_schema_mismatch_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        artifact_ref_lists,
        "require_rust_binding",
        lambda _name: lambda: 99,
    )

    with pytest.raises(RuntimeError, match="expected 2, got 99"):
        normalize_artifact_ref_list(["plans:one.md"])
