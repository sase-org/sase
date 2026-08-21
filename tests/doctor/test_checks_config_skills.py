"""Tests for doctor generated-skill deployment checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_config_skills import check_config_skills_applied
from sase.skills.inventory import AppliedSkillsInventory, AppliedSkillTargetEntry


def _target(
    tmp_path: Path,
    status: str,
    *,
    source_status: str = "current",
) -> AppliedSkillTargetEntry:
    return AppliedSkillTargetEntry(
        source_path=tmp_path / "chezmoi" / "dot_claude" / "skills" / "foo" / "SKILL.md",
        home_path=tmp_path / "home" / ".claude" / "skills" / "foo" / "SKILL.md",
        provider="claude",
        skill_name="foo",
        status=status,  # type: ignore[arg-type]
        source_status=source_status,  # type: ignore[arg-type]
    )


def test_config_skills_applied_skips_when_chezmoi_disabled(tmp_path: Path) -> None:
    check = check_config_skills_applied(
        use_chezmoi=False,
        inventory=AppliedSkillsInventory(targets=(_target(tmp_path, "missing"),)),
    )

    assert check.id == "config.skills.applied"
    assert check.group == "config"
    assert check.status == "SKIP"
    assert check.summary == "chezmoi skill deployment is disabled"


def test_config_skills_applied_ok_when_home_matches_source(tmp_path: Path) -> None:
    check = check_config_skills_applied(
        use_chezmoi=True,
        inventory=AppliedSkillsInventory(targets=(_target(tmp_path, "current"),)),
    )

    assert check.status == "OK"
    assert "match the chezmoi source" in check.summary
    assert check.data["current_count"] == 1


def test_config_skills_applied_warns_when_home_target_diverges(
    tmp_path: Path,
) -> None:
    check = check_config_skills_applied(
        use_chezmoi=True,
        inventory=AppliedSkillsInventory(targets=(_target(tmp_path, "stale"),)),
    )

    assert check.status == "WARN"
    assert "diverge from the chezmoi source" in check.summary
    assert "claude/foo: stale" in check.details[0]
    assert any("chezmoi apply" in step for step in check.next_steps)
    assert check.data["stale_count"] == 1


def test_config_skills_applied_advises_skill_init_when_source_missing(
    tmp_path: Path,
) -> None:
    check = check_config_skills_applied(
        use_chezmoi=True,
        inventory=AppliedSkillsInventory(
            targets=(_target(tmp_path, "source_missing", source_status="missing"),)
        ),
    )

    assert check.status == "WARN"
    assert check.data["source_missing_count"] == 1
    assert any("sase skill init --force" in step for step in check.next_steps)


def test_config_skills_applied_warns_for_retired_targets(tmp_path: Path) -> None:
    check = check_config_skills_applied(
        use_chezmoi=True,
        inventory=AppliedSkillsInventory(targets=(_target(tmp_path, "retired"),)),
    )

    assert check.status == "WARN"
    assert check.data["retired_count"] == 1
    assert any("remove retired generated skills" in step for step in check.next_steps)
