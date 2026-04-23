"""Tests for the centralized config module."""

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config.core import (
    CONFIG_DIR,
    _deep_merge,
    _get_local_config_path,
    load_config_layers,
    load_merged_config,
    load_xprompts_by_source,
    set_include_local_config,
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

    with patch("sase.config.core.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["key"] == "base"
    assert result["extra"] == "value"


def test_load_merged_config_non_dict_yaml_skipped(tmp_path: Path) -> None:
    """YAML files containing non-dict top-level values are skipped."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    list_overlay = tmp_path / "sase_list.yml"
    list_overlay.write_text(yaml.dump(["just", "a", "list"]))

    with patch("sase.config.core.CONFIG_DIR", tmp_path):
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

    with patch("sase.config.core.Path.cwd", return_value=tmp_path):
        result = _get_local_config_path()

    assert result == local_config


def test_get_local_config_path_returns_none_when_missing(tmp_path: Path) -> None:
    """Returns None when no sase.yml in CWD."""
    with patch("sase.config.core.Path.cwd", return_value=tmp_path):
        result = _get_local_config_path()

    assert result is None


def test_get_local_config_path_returns_none_when_cwd_missing() -> None:
    """Returns None (instead of raising) when Path.cwd() raises FileNotFoundError.

    Reproduces the axe-daemon failure mode where the workspace the daemon was
    launched in gets wiped, leaving a dangling kernel CWD.
    """
    with patch("sase.config.core.Path.cwd", side_effect=FileNotFoundError):
        result = _get_local_config_path()

    assert result is None


def test_get_local_config_path_returns_none_when_disabled(tmp_path: Path) -> None:
    """Returns None when _include_local_config is False (e.g. sase ace)."""
    local_config = tmp_path / "sase.yml"
    local_config.write_text(yaml.dump({"key": "local"}))

    set_include_local_config(False)
    try:
        with patch("sase.config.core.Path.cwd", return_value=tmp_path):
            result = _get_local_config_path()
        assert result is None
    finally:
        set_include_local_config(True)


def test_load_merged_config_local_overrides_global(tmp_path: Path) -> None:
    """Local sase.yml overrides global config values."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(yaml.dump({"key": "global", "other": "g"}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"key": "local"}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_config),
        patch("sase.config.core.Path.cwd", return_value=local_dir),
    ):
        result = load_merged_config()

    assert result["key"] == "local"
    assert result["other"] == "g"


def test_load_merged_config_local_concatenates_lists(tmp_path: Path) -> None:
    """Local sase.yml concatenates lists (project profiles extend plugin profiles)."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(yaml.dump({"items": [1, 2]}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"items": [3]}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_config),
        patch("sase.config.core.Path.cwd", return_value=local_dir),
    ):
        result = load_merged_config()

    assert result["items"] == [1, 2, 3]


def test_load_xprompts_by_source_includes_local_config(tmp_path: Path) -> None:
    """Local sase.yml xprompts appear in load_xprompts_by_source output."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(
        yaml.dump({"xprompts": {"my_prompt": "local prompt content"}})
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=local_dir),
    ):
        results = load_xprompts_by_source()

    local_sources = [
        (label, data) for label, data in results if label == "local_config"
    ]
    assert len(local_sources) == 1
    assert local_sources[0][1]["my_prompt"] == "local prompt content"


# --- load_config_layers tests ---


def test_load_config_layers_returns_default_layer(tmp_path: Path) -> None:
    """Default layer is always present and loaded."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path),
    ):
        layers = load_config_layers()

    default_layers = [ly for ly in layers if ly.name == "default"]
    assert len(default_layers) == 1
    assert default_layers[0].exists is True
    assert default_layers[0].path is None


def test_load_config_layers_includes_user_and_local(tmp_path: Path) -> None:
    """User and local layers appear with correct metadata."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase.yml").write_text(yaml.dump({"key": "user"}))

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"extra": "local"}))

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=local_dir),
    ):
        layers = load_config_layers()

    user_layer = next(ly for ly in layers if ly.name == "user")
    assert user_layer.exists is True
    assert user_layer.list_strategy == "replace"
    assert "key" in user_layer.keys

    local_layer = next(ly for ly in layers if ly.name == "local")
    assert local_layer.exists is True
    assert local_layer.list_strategy == "concatenate"
    assert "extra" in local_layer.keys


def test_load_config_layers_overlay_detected(tmp_path: Path) -> None:
    """Overlay files are detected as separate layers."""
    (tmp_path / "sase.yml").write_text(yaml.dump({"base": True}))
    (tmp_path / "sase_extra.yml").write_text(yaml.dump({"overlay_key": True}))

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "none"),
    ):
        layers = load_config_layers()

    overlay_layers = [ly for ly in layers if ly.name.startswith("overlay:")]
    assert len(overlay_layers) == 1
    assert overlay_layers[0].name == "overlay:sase_extra.yml"
    assert "overlay_key" in overlay_layers[0].keys


def test_load_config_layers_missing_local_marked_not_found(tmp_path: Path) -> None:
    """When no local sase.yml exists, local layer is marked exists=False."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path),
    ):
        layers = load_config_layers()

    local_layer = next(ly for ly in layers if ly.name == "local")
    assert local_layer.exists is False
    assert local_layer.keys == []
