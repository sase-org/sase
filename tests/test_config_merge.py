"""Tests for the centralized config module."""

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.config.core import (
    CONFIG_DIR,
    _deep_merge,
    load_merged_config,
    load_public_merged_config,
)
from sase.feature_flags import override_flags


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


def test_deep_merge_commit_hook_phases_independently() -> None:
    """Global and project-local commit hook phases compose as nested config."""
    base = {"commit_hooks": {"before": "global fix", "after": ""}}
    override = {"commit_hooks": {"after": "project apply"}}

    result = _deep_merge(base, override)

    assert result["commit_hooks"] == {
        "before": "global fix",
        "after": "project apply",
    }


# --- load_merged_config tests ---


def test_load_merged_config_default_workspace_root_is_xdg_state(
    tmp_path: Path,
) -> None:
    """Bundled defaults expose the managed state-root policy."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        result = load_merged_config()

    assert result["workspace"]["root"] == "xdg-state"


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
    assert CONFIG_DIR.is_absolute()
    assert CONFIG_DIR.parts[-2:] == (".config", "sase")


def test_load_merged_config_normalizes_axe_aliases_through_rust(
    tmp_path: Path,
) -> None:
    """Generic runtime loading sees one internal AXE tree, not alias twins."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(
        yaml.dump({"axe": {"routines": {"checks": {"interval": 19}}}}),
        encoding="utf-8",
    )
    default = {
        "axe": {
            "lumberjacks": {
                "checks": {
                    "description": "Run checks",
                    "interval": 5,
                    "chops": {},
                }
            }
        }
    }

    with (
        patch("sase.config.core.CONFIG_DIR", global_config),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", return_value=default),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        merged = load_merged_config()

    assert merged["axe"]["lumberjacks"]["checks"]["interval"] == 19
    assert "routines" not in merged["axe"]


def test_load_public_merged_config_projects_axe_by_rollout_state(
    tmp_path: Path,
) -> None:
    """Public config views use canonical AXE keys only while the flag is on."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(
        yaml.dump({"axe": {"routines": {"checks": {"interval": 19}}}}),
        encoding="utf-8",
    )
    default = {
        "axe": {
            "lumberjacks": {
                "checks": {
                    "description": "Run checks",
                    "interval": 5,
                    "chops": {},
                }
            }
        }
    }

    with (
        patch("sase.config.core.CONFIG_DIR", global_config),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", return_value=default),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        with override_flags(axe_routine_job_contract=True):
            canonical = load_public_merged_config()
        with override_flags(axe_routine_job_contract=False):
            legacy = load_public_merged_config()

    assert canonical["axe"]["routines"]["checks"]["interval"] == 19
    assert "lumberjacks" not in canonical["axe"]
    assert legacy["axe"]["lumberjacks"]["checks"]["interval"] == 19
    assert "routines" not in legacy["axe"]


def test_config_show_projects_public_axe_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``sase config show`` prints the public AXE contract, not raw aliases."""
    global_config = tmp_path / "global"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(
        yaml.dump({"axe": {"routines": {"checks": {"interval": 19}}}}),
        encoding="utf-8",
    )
    default = {
        "axe": {
            "lumberjacks": {
                "checks": {
                    "description": "Run checks",
                    "interval": 5,
                    "chops": {},
                }
            }
        }
    }

    from sase.main.config_handler import handle_config_command

    with (
        patch("sase.config.core.CONFIG_DIR", global_config),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", return_value=default),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
        override_flags(axe_routine_job_contract=True),
        pytest.raises(SystemExit) as exit_info,
    ):
        handle_config_command(argparse.Namespace(config_subcommand="show", key="axe"))

    assert exit_info.value.code == 0
    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["axe"]["routines"]["checks"]["interval"] == 19
    assert "lumberjacks" not in shown["axe"]
