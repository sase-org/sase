"""Tests for doctor initialization planner checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.doctor.checks_config_init import check_config_init
from sase.doctor.runner import DoctorContext
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec
from sase.core.paths import machine_name_path


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


def test_config_init_doctor_reports_missing_then_current_owner_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sase.config import core as config_core
    from sase.main.config_init_handler import plan_config_init, run_config_init

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    spec = InitCommandSpec("config", "Config", plan_config_init, run_config_init)
    monkeypatch.setattr(
        "sase.doctor.checks_config_init.iter_init_command_specs",
        lambda: (spec,),
    )

    missing = check_config_init(_context())
    assert missing.status == "WARN"
    assert missing.data["planners"][0]["name"] == "config"
    assert missing.data["action_count"] == 1

    (config_dir / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")
    config_core.clear_config_cache()
    current = check_config_init(_context())
    assert current.status == "OK"
    assert current.data["action_count"] == 0
