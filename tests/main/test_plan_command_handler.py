"""Tests for ``sase.main.plan_command_handler``."""

from __future__ import annotations

import json
from pathlib import Path

from sase.main.plan_command_handler import handle_plan_command


def _setup_agent_env(monkeypatch, artifacts_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    artifacts_dir.mkdir(parents=True, exist_ok=True)


def test_handle_plan_command_deletes_transient_root_plan(
    tmp_path: Path, monkeypatch
) -> None:
    """Root ``sase_plan_*.md`` files are removed after marker write."""
    monkeypatch.chdir(tmp_path)
    artifacts_dir = tmp_path / "artifacts"
    _setup_agent_env(monkeypatch, artifacts_dir)

    plan_path = tmp_path / "sase_plan_demo.md"
    plan_path.write_text("# Demo plan\n", encoding="utf-8")
    archived = tmp_path / "archived_demo.md"

    monkeypatch.setattr(
        "sase.llm_provider._plan_utils.save_plan_to_sase",
        lambda _p: archived,
    )
    monkeypatch.setattr(
        "sase.main.plan_command_handler.kill_agent_runner_group",
        lambda _d: None,
    )

    handle_plan_command(str(plan_path))

    marker = artifacts_dir / ".sase_plan_pending"
    assert marker.exists()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["plan_file"] == str(archived)
    assert data["original_file"] == str(plan_path.resolve())
    assert not plan_path.exists()


def test_handle_plan_command_keeps_non_transient_plan_name(
    tmp_path: Path, monkeypatch
) -> None:
    """Non ``sase_plan_*.md`` filenames are preserved."""
    monkeypatch.chdir(tmp_path)
    artifacts_dir = tmp_path / "artifacts"
    _setup_agent_env(monkeypatch, artifacts_dir)

    plan_path = tmp_path / "implementation_plan.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    archived = tmp_path / "archived_plan.md"

    monkeypatch.setattr(
        "sase.llm_provider._plan_utils.save_plan_to_sase",
        lambda _p: archived,
    )
    monkeypatch.setattr(
        "sase.main.plan_command_handler.kill_agent_runner_group",
        lambda _d: None,
    )

    handle_plan_command(str(plan_path))

    assert plan_path.exists()
