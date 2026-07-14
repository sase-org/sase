"""Tests for cutover-aware committed-plan validation."""

from pathlib import Path

import pytest

from sase.scripts.validate_committed_plans import (
    _sweep_committed_plans,
    main,
)


def _write_plan(root: Path, yyyymm: str, name: str, content: str) -> Path:
    path = root / yyyymm / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_sweep_applies_full_schema_at_cutover_only(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        "202607",
        "legacy.md",
        "---\ntier: tale\n---\n# Legacy plan\n",
    )
    _write_plan(
        tmp_path,
        "202608",
        "strict.md",
        "---\ntier: tale\ngoal: Ship the validated plan sweep\n---\n# Plan\n",
    )
    prompt = tmp_path / "202608" / "prompts" / "prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("not a plan", encoding="utf-8")
    (tmp_path / "scratch.md").write_text("not a committed monthly plan")

    sweep = _sweep_committed_plans(tmp_path)

    assert sweep.ok is True
    assert sweep.checked_files == 2
    assert sweep.strict_files == 1
    assert sweep.legacy_files == 1
    assert sweep.issues == ()


def test_sweep_reports_all_strict_plan_failures(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        "202608",
        "missing_goal.md",
        "---\ntier: tale\n---\n# Plan\n",
    )
    _write_plan(
        tmp_path,
        "202609",
        "bad_epic.md",
        "---\ntier: epic\ngoal: Exercise aggregate diagnostics\n---\n# Plan\n",
    )

    sweep = _sweep_committed_plans(tmp_path)

    assert sweep.ok is False
    assert sweep.checked_files == 2
    assert {issue.path for issue in sweep.issues if issue.is_error} == {
        "202608/missing_goal.md",
        "202609/bad_epic.md",
    }
    assert {issue.code for issue in sweep.issues if issue.is_error} == {
        "required-missing"
    }


def test_sweep_retains_legacy_tier_check(tmp_path: Path) -> None:
    _write_plan(tmp_path, "202607", "missing_tier.md", "# Legacy plan\n")

    sweep = _sweep_committed_plans(tmp_path)

    assert sweep.ok is False
    assert [(issue.path, issue.code) for issue in sweep.issues] == [
        ("202607/missing_tier.md", "plan-tier")
    ]


def test_main_prints_aggregate_diagnostics_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_plan(
        tmp_path,
        "202608",
        "invalid.md",
        "---\ntier: tale\n---\n# Plan\n",
    )
    monkeypatch.setattr(
        "sase.scripts.validate_committed_plans._resolve_committed_plans_root",
        lambda: tmp_path,
    )

    assert main() == 1
    output = capsys.readouterr().out
    assert "202608/invalid.md" in output
    assert "[required-missing]" in output
    assert "Committed plan validation failed: 1 files" in output


def test_main_returns_zero_for_valid_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_plan(
        tmp_path,
        "202608",
        "valid.md",
        "---\ntier: tale\ngoal: Keep committed plans valid\n---\n# Plan\n",
    )
    monkeypatch.setattr(
        "sase.scripts.validate_committed_plans._resolve_committed_plans_root",
        lambda: tmp_path,
    )

    assert main() == 0
    assert "Committed plan validation passed: 1 files" in capsys.readouterr().out
