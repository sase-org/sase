from __future__ import annotations

from typing import Any

import pytest

from sase.task_types._models import TaskTypeDiagnostic, TaskTypeProvenance
from sase.task_types._validation import (
    TASK_TYPE_ACCENT_PALETTE,
    resolve_task_type_presentation,
    validate_task_type_candidates,
    validate_task_type_spec,
)


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "task_type": "flake",
        "label": "Flaky test",
        "summary": "A test that fails and then passes on an unchanged tree.",
        "when_to_use": "File one when a test failed and a rerun on the same tree passed.",
    }
    spec.update(overrides)
    return spec


def _provenance(
    source: str = "plugin", name: str = "sase-github", *, builtin: bool = False
) -> TaskTypeProvenance:
    return TaskTypeProvenance(
        source=source,  # type: ignore[arg-type]
        name=name,
        package=name,
        version="1.0.0",
        builtin=builtin,
    )


def test_validate_task_type_spec_returns_stable_digest() -> None:
    spec = _spec()
    first = validate_task_type_spec(spec)
    second = validate_task_type_spec(spec)
    assert first == second
    assert len(first) == 64


def test_omitted_create_refusal_does_not_change_digest() -> None:
    without = _spec()
    with_none = _spec(create_refusal=None)
    assert validate_task_type_spec(without) == validate_task_type_spec(
        {key: value for key, value in with_none.items() if key != "create_refusal"}
    )


def test_explicit_create_refusal_changes_digest() -> None:
    without = validate_task_type_spec(_spec())
    with_refusal = validate_task_type_spec(
        _spec(create_refusal="Agents never create this type.")
    )
    assert without != with_refusal


def test_validate_task_type_spec_rejects_reserved_slug() -> None:
    with pytest.raises(Exception, match="reserved"):
        validate_task_type_spec(_spec(task_type="task"))


def test_validate_task_type_spec_accepts_flag_slug() -> None:
    digest = validate_task_type_spec(_spec(task_type="flag"))
    assert len(digest) == 64


def test_candidates_accepts_valid_spec_with_provenance() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    provenance = _provenance()
    records = validate_task_type_candidates([(_spec(), provenance)], diagnostics)
    assert diagnostics == []
    assert len(records) == 1
    assert records[0].task_type == "flake"
    assert records[0].provenance is provenance
    assert len(records[0].digest) == 64


def test_candidates_reports_invalid_spec() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    records = validate_task_type_candidates(
        [(_spec(label=""), _provenance())], diagnostics
    )
    assert records == ()
    assert [d.code for d in diagnostics] == ["invalid_task_type"]
    assert diagnostics[0].severity == "error"


def test_candidates_first_plugin_wins_duplicate() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    first = _provenance(name="a-first")
    second = _provenance(name="z-second")
    records = validate_task_type_candidates(
        [(_spec(), first), (_spec(), second)], diagnostics
    )
    assert len(records) == 1
    assert records[0].provenance is first
    assert [d.code for d in diagnostics] == ["duplicate_task_type"]


def test_candidates_reject_plugin_shadowing_builtin() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    builtin = _provenance(source="builtin", name="sase", builtin=True)
    plugin = _provenance(source="plugin", name="sase-github")
    records = validate_task_type_candidates(
        [(_spec(), builtin), (_spec(), plugin)], diagnostics
    )
    assert len(records) == 1
    assert records[0].provenance is builtin
    assert [d.code for d in diagnostics] == ["builtin_task_type_shadowed"]
    assert diagnostics[0].severity == "error"


def test_presentation_keeps_declared_glyph_and_accent() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    records = validate_task_type_candidates(
        [(_spec(glyph="≈", accent_color="#00D7D7"), _provenance())], diagnostics
    )
    resolved = resolve_task_type_presentation(records, diagnostics)
    assert resolved[0].resolved_glyph == "≈"
    assert resolved[0].resolved_accent_color == "#00D7D7"
    assert diagnostics == []


def test_presentation_hashes_missing_accent_into_curated_palette() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    records = validate_task_type_candidates([(_spec(), _provenance())], diagnostics)
    resolved = resolve_task_type_presentation(records, diagnostics)
    assert resolved[0].resolved_accent_color in TASK_TYPE_ACCENT_PALETTE
    assert resolved[0].resolved_glyph  # a default glyph is always assigned


def test_presentation_hash_is_stable_across_calls() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    records = validate_task_type_candidates([(_spec(), _provenance())], diagnostics)
    resolved_a = resolve_task_type_presentation(records, [])
    resolved_b = resolve_task_type_presentation(records, [])
    assert resolved_a[0].resolved_accent_color == resolved_b[0].resolved_accent_color


def test_presentation_warns_on_duplicate_resolved_color() -> None:
    diagnostics: list[TaskTypeDiagnostic] = []
    first = validate_task_type_candidates(
        [(_spec(task_type="bug", accent_color="#5FAFFF"), _provenance(name="a"))],
        diagnostics,
    )
    second = validate_task_type_candidates(
        [(_spec(task_type="ci", accent_color="#5FAFFF"), _provenance(name="b"))],
        diagnostics,
    )
    resolved = resolve_task_type_presentation([*first, *second], diagnostics)
    assert resolved[0].resolved_accent_color == resolved[1].resolved_accent_color
    assert [d.code for d in diagnostics] == ["duplicate_task_type_color"]
    assert diagnostics[0].severity == "warning"
