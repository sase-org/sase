"""Tests for the centralized config module."""

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config import (
    CONFIG_DIR,
    _deep_merge,
    _get_local_config_path,
    load_merged_config,
    load_xprompts_by_source,
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


# --- local config tests ---


def test_get_local_config_path_returns_path_when_exists(tmp_path: Path) -> None:
    """Local sase.yml in CWD is found."""
    local_config = tmp_path / "sase.yml"
    local_config.write_text(yaml.dump({"key": "local"}))

    with patch("sase.config.Path.cwd", return_value=tmp_path):
        result = _get_local_config_path()

    assert result == local_config


def test_get_local_config_path_returns_none_when_missing(tmp_path: Path) -> None:
    """Returns None when no sase.yml in CWD."""
    with patch("sase.config.Path.cwd", return_value=tmp_path):
        result = _get_local_config_path()

    assert result is None


def test_load_merged_config_local_overrides_global(tmp_path: Path) -> None:
    """Local sase.yml overrides global config values."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(yaml.dump({"key": "global", "other": "g"}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"key": "local"}))

    with (
        patch("sase.config.CONFIG_DIR", global_config),
        patch("sase.config.Path.cwd", return_value=local_dir),
    ):
        result = load_merged_config()

    assert result["key"] == "local"
    assert result["other"] == "g"


def test_load_merged_config_local_replaces_lists(tmp_path: Path) -> None:
    """Local sase.yml uses replace strategy for lists."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(yaml.dump({"items": [1, 2]}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"items": [3]}))

    with (
        patch("sase.config.CONFIG_DIR", global_config),
        patch("sase.config.Path.cwd", return_value=local_dir),
    ):
        result = load_merged_config()

    assert result["items"] == [3]


def test_load_xprompts_by_source_includes_local_config(tmp_path: Path) -> None:
    """Local sase.yml xprompts appear in load_xprompts_by_source output."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(
        yaml.dump({"xprompts": {"my_prompt": "local prompt content"}})
    )

    with (
        patch("sase.config.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.Path.cwd", return_value=local_dir),
    ):
        results = load_xprompts_by_source()

    local_sources = [
        (label, data) for label, data in results if label == "local_config"
    ]
    assert len(local_sources) == 1
    assert local_sources[0][1]["my_prompt"] == "local prompt content"
