"""The shared plan-reference presentation used by every display surface."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.plan_ref_display import (
    PLAN_REFERENCE_AMBIGUOUS_LABEL,
    PLAN_REFERENCE_INVALID_LABEL,
    PLAN_REFERENCE_MISSING_LABEL,
    describe_design_reference,
)


def _plans_root(tmp_path: Path, month: str, name: str) -> Path:
    root = tmp_path / "plans"
    (root / month).mkdir(parents=True, exist_ok=True)
    (root / month / name).write_text("# Plan\n", encoding="utf-8")
    return root


def test_exact_resolution_reports_the_reference_and_the_path(
    tmp_path: Path,
) -> None:
    root = _plans_root(tmp_path, "202607", "durable.md")

    display = describe_design_reference(
        "plan:202607/durable.md",
        roots=(root,),
        cwd=tmp_path,
    )

    assert display.resolved
    assert display.status == "exact"
    assert display.lines == (
        "plan:202607/durable.md",
        f"→ {root / '202607/durable.md'}",
    )


def test_month_drift_is_marked_rather_than_hidden(tmp_path: Path) -> None:
    root = _plans_root(tmp_path, "202607", "drifted.md")

    display = describe_design_reference(
        "plan:202606/drifted.md",
        roots=(root,),
        cwd=tmp_path,
    )

    assert display.status == "drifted"
    assert display.lines[1].endswith(" (month drift)")


def test_missing_and_ambiguous_references_say_so(tmp_path: Path) -> None:
    root = _plans_root(tmp_path, "202607", "twin.md")
    _plans_root(tmp_path, "202606", "twin.md")

    missing = describe_design_reference(
        "plan:202607/gone.md",
        roots=(root,),
        cwd=tmp_path,
    )
    ambiguous = describe_design_reference(
        "plan:202605/twin.md",
        roots=(root,),
        cwd=tmp_path,
    )

    assert not missing.resolved
    assert missing.lines == (
        "plan:202607/gone.md",
        f"→ {PLAN_REFERENCE_MISSING_LABEL}",
    )
    assert ambiguous.lines == (
        "plan:202605/twin.md",
        f"→ {PLAN_REFERENCE_AMBIGUOUS_LABEL}",
    )


def test_a_malformed_reference_is_reported_not_treated_as_legacy(
    tmp_path: Path,
) -> None:
    display = describe_design_reference(
        "plan:../escape.md",
        roots=(),
        cwd=tmp_path,
    )

    assert display.status == "invalid"
    assert display.lines[1] == f"→ {PLAN_REFERENCE_INVALID_LABEL}"


def test_a_legacy_path_that_resolves_to_itself_renders_once(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans/legacy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    display = describe_design_reference(
        "plans/legacy.md",
        roots=(),
        cwd=tmp_path,
        relativize=True,
    )

    assert display.resolved
    assert display.lines == ("plans/legacy.md",)


def test_a_legacy_path_below_the_cwd_still_resolves(tmp_path: Path) -> None:
    plan = tmp_path / "plans/legacy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    display = describe_design_reference(
        "plans/legacy.md",
        roots=(),
        cwd=tmp_path,
    )

    assert display.lines == ("plans/legacy.md", f"→ {plan}")
