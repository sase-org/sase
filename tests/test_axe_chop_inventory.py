"""Tests for AXE chop inventory collection."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from sase.axe.chop_inventory import chop_inventory_to_dict, collect_chop_inventory
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_chop_inventory_resolves_missing_agent_and_available_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_executable(scripts_dir / "resolved")

    python_bin = tmp_path / "venv" / "bin"
    python_bin.mkdir(parents=True)
    python_executable = python_bin / "python"
    python_executable.write_text("", encoding="utf-8")
    _make_executable(python_bin / "sase_chop_available")

    monkeypatch.setattr(
        "sase.axe.chop_inventory.sys.executable", str(python_executable)
    )
    monkeypatch.setenv("PATH", "")

    config = AxeConfig(
        chop_script_dirs=[str(scripts_dir)],
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[
                    ChopConfig(name="resolved", description=""),
                    ChopConfig(name="missing", description=""),
                    ChopConfig(
                        name="agented",
                        description="",
                        agent="do-work",
                        env={"SECRET_ENV": "hidden"},
                    ),
                ],
            )
        },
    )

    inventory = collect_chop_inventory(config)

    configured = {(chop.name, chop.status) for chop in inventory.configured_chops}
    assert configured == {
        ("resolved", "configured"),
        ("missing", "missing"),
        ("agented", "agent-backed"),
    }
    resolved = next(
        chop for chop in inventory.configured_chops if chop.name == "resolved"
    )
    assert resolved.resolved_path == str(scripts_dir / "resolved")
    agented = next(
        chop for chop in inventory.configured_chops if chop.name == "agented"
    )
    assert agented.env == {"SECRET_ENV": "hidden"}

    available = inventory.available_unconfigured
    assert len(available) == 1
    assert available[0].name == "available"
    assert available[0].source == "python_bin"
    assert available[0].executable == str(python_bin / "sase_chop_available")


def test_chop_inventory_to_dict_is_json_safe() -> None:
    config = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[ChopConfig(name="agented", description="d", agent="do")],
            )
        }
    )

    payload = chop_inventory_to_dict(collect_chop_inventory(config))

    assert set(payload) >= {
        "configured",
        "available",
        "available_unconfigured",
        "chop_script_dirs",
        "python_bin_dir",
        "path_dirs",
    }
    agented = next(c for c in payload["configured"] if c["name"] == "agented")
    assert agented["status"] == "agent-backed"
    assert agented["script"] is False
    assert agented["agent"] == "do"
    assert "env" not in agented
