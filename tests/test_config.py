"""Tests for the centralized config module."""

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config import (
    CONFIG_DIR,
    _deep_merge,
    _get_local_config_path,
    load_merged_config,
)


# --- _deep_merge tests ---


def test_deep_merge_list_concatenation() -> None:
    """Lists are concatenated by default (overlay appended to base)."""
    base = {"items": [1, 2]}
    override = {"items": [3, 4]}
    result = _deep_merge(base, override)
    assert result == {"items": [1, 2, 3, 4]}


def test_deep_merge_list_replace_nested() -> None:
    """list_strategy='replace' propagates through nested dicts."""
    base = {"a": {"chops": ["x", "y"]}}
    override = {"a": {"chops": ["z"]}}
    result = _deep_merge(base, override, list_strategy="replace")
    assert result == {"a": {"chops": ["z"]}}


# --- load_default_config tests ---


# --- load_merged_config tests ---


def test_load_merged_config_invalid_yaml_skipped(tmp_path: Path) -> None:
    """Invalid YAML overlay files are skipped."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    bad_overlay = tmp_path / "sase_bad.yml"
    bad_overlay.write_text("invalid: yaml: [not closed")

    good_overlay = tmp_path / "sase_good.yml"
    good_overlay.write_text(yaml.dump({"extra": "value"}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["key"] == "base"
    assert result["extra"] == "value"


def test_load_merged_config_non_dict_yaml_skipped(tmp_path: Path) -> None:
    """YAML files containing non-dict top-level values are skipped."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    list_overlay = tmp_path / "sase_list.yml"
    list_overlay.write_text(yaml.dump(["just", "a", "list"]))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["key"] == "base"


def test_config_dir_is_correct() -> None:
    """CONFIG_DIR points to ~/.config/sase."""
    assert CONFIG_DIR == Path.home() / ".config" / "sase"


# --- _get_local_config_path tests ---


def test_get_local_config_path_sase_yml(tmp_path: Path) -> None:
    """Returns sase.yml when it exists in the given directory."""
    (tmp_path / "sase.yml").write_text("key: val")
    assert _get_local_config_path(tmp_path) == tmp_path / "sase.yml"


def test_get_local_config_path_hidden_takes_priority(tmp_path: Path) -> None:
    """Hidden .sase.yml takes priority over sase.yml when both exist."""
    (tmp_path / ".sase.yml").write_text("key: hidden")
    (tmp_path / "sase.yml").write_text("key: visible")
    assert _get_local_config_path(tmp_path) == tmp_path / ".sase.yml"


def test_get_local_config_path_returns_none(tmp_path: Path) -> None:
    """Returns None when no local config exists."""
    assert _get_local_config_path(tmp_path) is None


# --- Local config merge tests ---


def test_local_config_merged_as_highest_priority(tmp_path: Path) -> None:
    """Local sase.yml is merged as the highest-priority layer."""
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    (global_cfg / "sase.yml").write_text(yaml.dump({"key": "global", "extra": "kept"}))

    local_dir = tmp_path / "project"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"key": "local"}))

    with patch("sase.config.CONFIG_DIR", global_cfg):
        result = load_merged_config(cwd=local_dir)

    assert result["key"] == "local"
    assert result["extra"] == "kept"


def test_local_config_uses_list_replace(tmp_path: Path) -> None:
    """Local config uses list 'replace' strategy."""
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    (global_cfg / "sase.yml").write_text(yaml.dump({"items": [1, 2, 3]}))

    local_dir = tmp_path / "project"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"items": [99]}))

    with patch("sase.config.CONFIG_DIR", global_cfg):
        result = load_merged_config(cwd=local_dir)

    assert result["items"] == [99]


def test_local_config_wins_over_overlays(tmp_path: Path) -> None:
    """Local config wins over global overlay files."""
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    (global_cfg / "sase.yml").write_text(yaml.dump({"key": "base"}))
    (global_cfg / "sase_overlay.yml").write_text(yaml.dump({"key": "overlay"}))

    local_dir = tmp_path / "project"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"key": "local"}))

    with patch("sase.config.CONFIG_DIR", global_cfg):
        result = load_merged_config(cwd=local_dir)

    assert result["key"] == "local"


def test_local_config_invalid_yaml_skipped(tmp_path: Path) -> None:
    """Invalid local YAML is skipped gracefully."""
    local_dir = tmp_path / "project"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text("invalid: yaml: [not closed")

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config(cwd=local_dir)

    # Should still return at least defaults without crashing
    assert isinstance(result, dict)
