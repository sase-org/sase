"""Tests for doctor initialization planner checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.doctor.checks_config_init import check_config_init
from sase.doctor.runner import DoctorContext
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec


def _context() -> DoctorContext:
    return DoctorContext(
        cwd=Path("/repo"),
        project=None,
        sase_home=Path("/home/user/.sase"),
        env={},
    )


def test_config_init_labels_prettier_missing_skill_drift(monkeypatch) -> None:
    def plan(_args: argparse.Namespace) -> InitPlan:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="1 generated skill file would be updated",
            actions=(
                InitAction(
                    path=Path("/home/user/.claude/skills/foo/SKILL.md"),
                    operation="overwrite",
                ),
            ),
            warnings=(
                "skill init: prettier not found on PATH; output may not match "
                "chezmoi CI formatting",
            ),
        )

    monkeypatch.setattr(
        "sase.doctor.checks_config_init.iter_init_command_specs",
        lambda: (
            InitCommandSpec(
                name="skills",
                label="Skills",
                plan=plan,
                run=lambda _args: 0,
            ),
        ),
    )

    check = check_config_init(_context())

    assert check.status == "WARN"
    assert (
        "stale counts may be inflated: prettier missing; generated skill files "
        "render without deployed formatting" in check.details
    )
    assert check.data["prettier_missing_skill_drift_note"] is True
    assert check.data["warning_count"] == 1
