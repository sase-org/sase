"""Tests for config edit targets, chezmoi remapping, and overlays."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.config.edit import ConfigEditOp, plan_config_edit
from sase.config.inventory import inventory_with_new_overlay
from sase.config.targets import (
    CHEZMOI_HOME,
    apply_chezmoi,
    chezmoi_source_path,
    default_target_layer,
    overlay_config_path,
    resolve_write_path,
)
from tests._config_edit_helpers import config_inventory, config_layer


def test_chezmoi_source_path_maps_home_dotfiles() -> None:
    """A home-managed config path maps to its chezmoi source path."""
    target = Path.home() / ".config" / "sase" / "sase.yml"
    assert chezmoi_source_path(target) == (
        CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    )


def test_chezmoi_source_path_passthrough_outside_home() -> None:
    """A path outside $HOME is not chezmoi-managed and is unchanged."""
    target = Path("/repo/sase.yml")
    assert chezmoi_source_path(target) == target


def test_resolve_write_path_honors_chezmoi_flag() -> None:
    """resolve_write_path remaps only when chezmoi is enabled."""
    target = Path.home() / ".config" / "sase" / "sase.yml"
    assert resolve_write_path(str(target), use_chezmoi=False) == target
    assert resolve_write_path(str(target), use_chezmoi=True) == (
        CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    )
    assert resolve_write_path(None, use_chezmoi=True) is None


def test_apply_chezmoi_forces_and_expands_target_path() -> None:
    """apply_chezmoi always passes --force and expands ~ in the target path."""
    run_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )
    with patch("sase.config.targets.run_noninteractive", run_mock):
        apply_chezmoi("~/.config/sase/sase.yml")

    cmd = run_mock.call_args.args[0]
    assert cmd[:3] == ["chezmoi", "apply", "--force"]
    assert cmd[3] == str(Path("~/.config/sase/sase.yml").expanduser())
    assert "~" not in cmd[3]


def test_apply_chezmoi_without_path_is_full_forced_apply() -> None:
    """apply_chezmoi() with no path forces a whole-tree apply."""
    run_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )
    with patch("sase.config.targets.run_noninteractive", run_mock):
        apply_chezmoi()

    assert run_mock.call_args.args[0] == ["chezmoi", "apply", "--force"]


def test_plan_remaps_target_to_chezmoi_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planning with chezmoi enabled resolves the write to the source tree."""
    home = tmp_path / "home"
    chezmoi = tmp_path / "chezmoi" / "home"
    config_dir = home / ".config" / "sase"
    config_dir.mkdir(parents=True)
    user_file = config_dir / "sase.yml"
    user_file.write_text("timezone: US/Pacific\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("sase.config.targets.CHEZMOI_HOME", chezmoi)

    layers = [
        config_layer("default", data={"timezone": "America/New_York"}),
        config_layer(
            "user",
            path=str(user_file),
            strategy="replace",
            data={"timezone": "US/Pacific"},
        ),
    ]
    inventory = config_inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=True,
    )
    assert plan.used_chezmoi is True
    assert plan.target_path == str(chezmoi / "dot_config" / "sase" / "sase.yml")


def test_default_target_layer_rules(tmp_path: Path) -> None:
    """A single existing mutable source is the default; lists force a choice."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text("", encoding="utf-8")
    layers = [
        config_layer("default", data={"timezone": "America/New_York"}),
        config_layer("user", path=str(user_file), strategy="replace", data={}),
    ]
    inventory = config_inventory(layers)
    assert default_target_layer(inventory) == "user"
    assert default_target_layer(inventory, force_explicit=True) is None


def test_overlay_config_path_normalizes_name() -> None:
    """overlay_config_path normalizes to the sase_<name>.yml convention."""
    from sase.config.core import CONFIG_DIR

    assert overlay_config_path("extra") == CONFIG_DIR / "sase_extra.yml"
    assert overlay_config_path(" extra ") == CONFIG_DIR / "sase_extra.yml"
    assert overlay_config_path("sase_foo.yml") == CONFIG_DIR / "sase_foo.yml"


def test_overlay_config_path_rejects_path_like_names() -> None:
    """Overlay names must not escape the user config directory."""
    for name in ("", "../evil", "nested/evil", r"nested\evil", ".", ".."):
        with pytest.raises(ValueError, match="single filename stem"):
            overlay_config_path(name)


def test_inventory_with_new_overlay_inserts_highest_priority_overlay(
    tmp_path: Path,
) -> None:
    """A new overlay is added as the highest-priority writable overlay."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text("timezone: US/Pacific\n", encoding="utf-8")
    layers = [
        config_layer("default", data={"timezone": "America/New_York"}),
        config_layer(
            "user",
            path=str(user_file),
            strategy="replace",
            data={"timezone": "US/Pacific"},
        ),
    ]
    inventory = config_inventory(layers)
    new_inventory, layer_name = inventory_with_new_overlay(inventory, "work")
    assert layer_name == "overlay:sase_work.yml"
    source = new_inventory.source(layer_name)
    assert source is not None
    assert source.writable and not source.exists
    assert source.list_strategy == "concatenate"
    # The new overlay can be targeted and wins over the user base.
    plan = plan_config_edit(
        new_inventory,
        "timezone",
        layer_name,
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    assert plan.effective_preview.after == "UTC"


def test_inventory_with_new_overlay_is_idempotent_for_existing_name(
    tmp_path: Path,
) -> None:
    overlay_file = tmp_path / "sase_extra.yml"
    overlay_file.write_text("timezone: US/Eastern\n", encoding="utf-8")
    layers = [
        config_layer("default", data={"timezone": "America/New_York"}),
        config_layer(
            "overlay:sase_extra.yml",
            path=str(overlay_file),
            strategy="concatenate",
            data={"timezone": "US/Eastern"},
        ),
    ]
    inventory = config_inventory(layers)
    same, layer_name = inventory_with_new_overlay(inventory, "extra")
    assert layer_name == "overlay:sase_extra.yml"
    assert same is inventory  # unchanged: the overlay already exists
