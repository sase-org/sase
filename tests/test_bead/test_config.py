"""Tests for sase.bead.config."""

from __future__ import annotations

import json

from sase.bead.config import get_default_config, load_config, save_config


def test_get_default_config(tmp_path):
    config = get_default_config(tmp_path)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1
    assert isinstance(config["owner"], str)


def test_save_and_load_config(tmp_path):
    beads_dir = tmp_path / ".sase_beads"
    beads_dir.mkdir()
    config = {"issue_prefix": "test", "next_counter": 5, "owner": "user@example.com"}
    save_config(beads_dir, config)

    loaded = load_config(beads_dir)
    assert loaded == config


def test_load_config_missing_returns_defaults(tmp_path):
    beads_dir = tmp_path / ".sase_beads"
    beads_dir.mkdir()
    config = load_config(beads_dir)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1


def test_save_config_creates_json(tmp_path):
    beads_dir = tmp_path / ".sase_beads"
    beads_dir.mkdir()
    config = {"issue_prefix": "proj", "next_counter": 1, "owner": ""}
    save_config(beads_dir, config)

    raw = (beads_dir / "config.json").read_text()
    parsed = json.loads(raw)
    assert parsed["issue_prefix"] == "proj"
