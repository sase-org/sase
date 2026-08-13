"""Tests for :mod:`sase.plan_show.load`."""

from __future__ import annotations

from pathlib import Path

from sase.plan_show.load import load_ambiguity_candidate, load_plan_show_record
from sase.plan_show.model import PlanShowTarget
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN

_TARGET = PlanShowTarget(raw="x", kind="path", status="exact")


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo_plans"
    local_root = tmp_path / "local_plans"
    repo_root.mkdir()
    local_root.mkdir()
    return repo_root, local_root


def test_source_classified_repo_local_and_file(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    repo_plan = repo_root / "202608" / "a.md"
    repo_plan.parent.mkdir(parents=True)
    repo_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    local_plan = local_root / "202608" / "b.md"
    local_plan.parent.mkdir(parents=True)
    local_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    outside_plan = tmp_path / "elsewhere" / "c.md"
    outside_plan.parent.mkdir(parents=True)
    outside_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")

    roots = (repo_root, local_root)
    repo_record = load_plan_show_record(repo_plan, target=_TARGET, roots=roots)
    local_record = load_plan_show_record(local_plan, target=_TARGET, roots=roots)
    outside_record = load_plan_show_record(outside_plan, target=_TARGET, roots=roots)

    assert repo_record.plan.source == "repo"
    assert repo_record.plan.relpath == "202608/a.md"
    assert local_record.plan.source == "local"
    assert local_record.plan.relpath == "202608/b.md"
    assert outside_record.plan.source == "file"


def test_canonical_reference_present_in_root_and_none_outside(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    repo_plan = repo_root / "202608" / "a.md"
    repo_plan.parent.mkdir(parents=True)
    repo_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    outside_plan = tmp_path / "elsewhere" / "c.md"
    outside_plan.parent.mkdir(parents=True)
    outside_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")

    roots = (repo_root, local_root)
    repo_record = load_plan_show_record(repo_plan, target=_TARGET, roots=roots)
    outside_record = load_plan_show_record(outside_plan, target=_TARGET, roots=roots)

    assert repo_record.plan.reference == "plan:202608/a.md"
    assert outside_record.plan.reference is None


def test_frontmatter_status_created_and_body_extracted(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "a.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\ntier: tale\ntitle: T\ngoal: G\nstatus: wip\n"
        "create_time: 2026-08-06 15:48:40\n---\n# Heading\n\nBody text.\n",
        encoding="utf-8",
    )

    record = load_plan_show_record(
        plan_path, target=_TARGET, roots=(repo_root, local_root)
    )

    assert record.plan.status == "wip"
    assert record.plan.created_at is not None
    assert "2026-08-06" in record.plan.created_at
    assert record.plan.frontmatter["status"] == "wip"
    assert record.plan.body == "# Heading\n\nBody text.\n"
    assert record.plan.title == "T"
    assert record.plan.goal == "G"


def test_epic_phases_and_waves_populated(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "epic.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(VALID_EPIC_PLAN, encoding="utf-8")

    record = load_plan_show_record(
        plan_path, target=_TARGET, roots=(repo_root, local_root)
    )

    assert record.plan.tier == "epic"
    assert len(record.plan.phases) == 1
    assert record.plan.phases[0].id == "implementation"
    assert record.plan.phases[0].size == "small"
    assert record.plan.waves == (("implementation",),)
    assert record.plan.validation.ok is True
    assert record.plan.validation.diagnostics == ()


def test_plan_with_no_valid_tier_degrades_with_diagnostics(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "no_tier.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntitle: No tier here\n---\n# Body\n", encoding="utf-8")

    record = load_plan_show_record(
        plan_path, target=_TARGET, roots=(repo_root, local_root)
    )

    assert record.plan.tier is None
    assert record.plan.validation.ok is False
    assert record.plan.validation.diagnostics
    assert record.plan.exists is True


def test_broken_frontmatter_degrades_without_raising(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "broken.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntier: [unterminated\n# Body\n", encoding="utf-8")

    record = load_plan_show_record(
        plan_path, target=_TARGET, roots=(repo_root, local_root)
    )

    assert record.plan.exists is True
    assert record.plan.validation.ok is False
    assert record.plan.validation.diagnostics
    assert record.plan.frontmatter == {}


def test_unreadable_file_handled_via_unavailable_metadata(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "unreadable.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(VALID_TALE_PLAN, encoding="utf-8")
    plan_path.chmod(0o000)
    try:
        record = load_plan_show_record(
            plan_path, target=_TARGET, roots=(repo_root, local_root)
        )
    finally:
        plan_path.chmod(0o644)

    assert record.plan.exists is True
    assert record.plan.title is None
    assert record.plan.validation.ok is False
    assert record.plan.body == ""


def test_missing_file_reports_not_exists(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    missing = repo_root / "202608" / "missing.md"

    record = load_plan_show_record(
        missing, target=_TARGET, roots=(repo_root, local_root)
    )

    assert record.plan.exists is False
    assert record.plan.title is None


def test_load_ambiguity_candidate_builds_lightweight_row(tmp_path: Path) -> None:
    repo_root, local_root = _roots(tmp_path)
    plan_path = repo_root / "202608" / "a.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(VALID_TALE_PLAN, encoding="utf-8")

    candidate = load_ambiguity_candidate(plan_path, roots=(repo_root, local_root))

    assert candidate.reference == "plan:202608/a.md"
    assert candidate.tier == "tale"
    assert candidate.title == "Approved implementation"
