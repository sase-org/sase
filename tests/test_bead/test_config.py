"""Tests for merged bead workflow configuration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from sase.bead import config as bead_config
from sase.bead.config import (
    _detect_prefix,
    get_default_config,
    load_config,
    save_config,
)


def test_get_default_config(tmp_path):
    config = get_default_config(tmp_path)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1
    assert isinstance(config["owner"], str)


def test_save_and_load_config(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = {"issue_prefix": "test", "next_counter": 5, "owner": "user@example.com"}
    save_config(beads_dir, config)

    loaded = load_config(beads_dir)
    assert loaded == config


def test_load_config_missing_returns_defaults(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = load_config(beads_dir)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1


def test_save_config_creates_json(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = {"issue_prefix": "proj", "next_counter": 1, "owner": ""}
    save_config(beads_dir, config)

    raw = (beads_dir / "config.json").read_text()
    parsed = json.loads(raw)
    assert parsed["issue_prefix"] == "proj"


def test_detect_prefix_uses_project_name_from_cwd(tmp_path, monkeypatch):
    root = tmp_path / ".sase" / "sdd"
    root.mkdir(parents=True)

    monkeypatch.setattr(
        "sase.bead.config.infer_project_name_from_cwd", lambda: "yserve"
    )
    assert _detect_prefix(root) == "yserve"


def test_detect_prefix_with_trailing_vcs_component(tmp_path, monkeypatch):
    """Prefix should be project name, not the workspace root dir name (e.g. google3)."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Register project
    project_dir = tmp_path / ".sase" / "projects" / "yserve"
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "yserve" / "google3"
    (project_dir / "yserve.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    # CWD is under a variant (primary need not exist on disk)
    variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    variant.mkdir(parents=True)
    monkeypatch.chdir(variant)

    # root_dir is the workspace root dir (e.g. google3) — should NOT be the prefix
    assert _detect_prefix(variant) == "yserve"


def test_big_epic_phase_threshold_reads_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {"bead": {"big_epic_phase_threshold": 8}},
    )

    assert bead_config.get_big_epic_phase_threshold() == 8


@pytest.mark.parametrize(
    "merged",
    [
        {},
        {"bead": None},
        {"bead": {"big_epic_phase_threshold": None}},
        {"bead": {"big_epic_phase_threshold": True}},
        {"bead": {"big_epic_phase_threshold": False}},
        {"bead": {"big_epic_phase_threshold": 0}},
        {"bead": {"big_epic_phase_threshold": -1}},
        {"bead": {"big_epic_phase_threshold": 5.0}},
        {"bead": {"big_epic_phase_threshold": "5"}},
    ],
)
def test_big_epic_phase_threshold_falls_back_for_missing_or_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
    merged: object,
) -> None:
    monkeypatch.setattr(bead_config, "load_merged_config", lambda: merged)

    assert bead_config.get_big_epic_phase_threshold() == 5


def test_big_epic_phase_threshold_falls_back_when_config_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = MagicMock(side_effect=RuntimeError("bad config"))
    monkeypatch.setattr(bead_config, "load_merged_config", load)

    assert bead_config.get_big_epic_phase_threshold() == 5
