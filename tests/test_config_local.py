"""Tests for local config discovery and local config overlays."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.content_layout import LayoutCollisionError
from sase.config.core import (
    get_local_config_path,
    load_merged_config,
    load_xprompts_by_source,
    set_include_local_config,
)


def test_get_local_config_path_returns_path_when_exists(tmp_path: Path) -> None:
    """Local sase.yml in CWD is found."""
    local_config = tmp_path / "sase.yml"
    local_config.write_text(yaml.dump({"key": "local"}))

    with patch("sase.config.core.Path.cwd", return_value=tmp_path):
        result = get_local_config_path()

    assert result == local_config


def test_get_local_config_path_prefers_canonical_from_nested_cwd(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("key: canonical\n", encoding="utf-8")

    with patch("sase.config.core.Path.cwd", return_value=nested):
        assert get_local_config_path() == config


def test_get_local_config_path_rejects_canonical_legacy_collision(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "sase" / "sase.yml"
    canonical.parent.mkdir()
    canonical.write_text("key: canonical\n", encoding="utf-8")
    (tmp_path / "sase.yml").write_text("key: legacy\n", encoding="utf-8")

    with (
        patch("sase.config.core.Path.cwd", return_value=tmp_path),
        pytest.raises(LayoutCollisionError, match="multiple canonical/legacy"),
    ):
        get_local_config_path()


def test_get_local_config_path_returns_none_when_missing(tmp_path: Path) -> None:
    """Returns None when no sase.yml in CWD."""
    with patch("sase.config.core.Path.cwd", return_value=tmp_path):
        result = get_local_config_path()

    assert result is None


def test_get_local_config_path_returns_none_when_cwd_missing() -> None:
    """Returns None (instead of raising) when Path.cwd() raises FileNotFoundError.

    Reproduces the axe-daemon failure mode where the workspace the daemon was
    launched in gets wiped, leaving a dangling kernel CWD.
    """
    with patch("sase.config.core.Path.cwd", side_effect=FileNotFoundError):
        result = get_local_config_path()

    assert result is None


def test_get_local_config_path_returns_none_when_disabled(tmp_path: Path) -> None:
    """Returns None when _include_local_config is False (e.g. sase tui)."""
    local_config = tmp_path / "sase.yml"
    local_config.write_text(yaml.dump({"key": "local"}))

    set_include_local_config(False)
    try:
        with patch("sase.config.core.Path.cwd", return_value=tmp_path):
            result = get_local_config_path()
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
