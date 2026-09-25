"""Tests for keymap mode defaults and fold/zoom source-of-truth consistency."""

from pathlib import Path

import yaml

from sase.ace.tui.keymaps import (
    BangModeKeymaps,
    BeadIssueModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    KeymapRegistry,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    cls_bindings,
)
from tests._keymaps_helpers import default_app_keymaps


def test_registry_default_modes_always_present() -> None:
    """KeymapRegistry always has all built-in modes."""
    reg = KeymapRegistry(app=default_app_keymaps())
    assert "fold_mode" in reg.modes
    assert "copy_mode" in reg.modes
    assert "leader_mode" in reg.modes
    assert "bang_mode" in reg.modes
    assert "bead_issue_mode" in reg.modes


def test_fold_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["fold_mode"]
    defaults = FoldModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_copy_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["copy_mode"]
    defaults = CopyModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_bang_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["bang_mode"]
    defaults = BangModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_bead_issue_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["bead_issue_mode"]
    defaults = BeadIssueModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_zoom_and_agents_fold_defaults_are_in_sync_with_help() -> None:
    reg = load_keymap_registry({})
    agent_fold = reg.fold_mode.keys["agents"]
    assert isinstance(agent_fold, dict)

    assert reg.app.start_fold_mode == "z"
    assert reg.app.zoom_panel == "Z"
    assert reg.app.isolate_panels == "="
    assert reg.app.collapse_panel_folds == "minus"
    assert reg.app.collapse_all_panel_folds == "underscore"
    assert agent_fold == {
        "cycle_level": "z",
        "toggle_all": "Z",
        "cycle_section": "a",
        "toggle_section": "A",
        "set_level_1": "1",
        "set_level_2": "2",
        "set_level_3": "3",
        "set_level_4": "4",
    }

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("Z", "Zoom deck panel in place") in agent_pairs
    assert ("=", "Only panel ⇄ restore panels") in agent_pairs
    assert ("_", "All-panel folds ⇄ restore ▿") in agent_pairs
    assert ("zz", "Cycle panel fold level forward") in agent_pairs
    assert ("zZ", "Toggle all metadata folds") in agent_pairs
    assert ("za", "Cycle foldable section/member") in agent_pairs
    assert ("zA", "Toggle foldable section/member") in agent_pairs
    assert ("z1 / z2", "Set session level 1-2") in agent_pairs
    assert ("z1 / z2 / z3", "Set clan/sase agent level 1-3") in agent_pairs
    assert (
        "z1 / z2 / z3 / z4",
        "Set selected tribe level 1-4",
    ) in agent_pairs
    assert ("0-9", "Jump numbered member/neighbor") in agent_pairs
    assert ("Esc", "Enter selected panel / cancel member jump") in agent_pairs


def test_fold_mode_direct_level_overrides_and_prefix_reach_help() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "prefix": "f",
                        "keys": {
                            "set_level_2": "w",
                            "agents": {"set_level_4": "x", "toggle_all": "v"},
                        },
                    }
                }
            }
        }
    )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert reg.app.start_fold_mode == "f"
    assert reg.fold_mode.keys["set_level_1"] == "1"
    assert reg.fold_mode.keys["set_level_2"] == "w"
    assert agent_keys["set_level_1"] == "1"
    assert agent_keys["set_level_4"] == "x"
    assert agent_keys["toggle_all"] == "v"

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    patch_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }
    assert ("f1 / f2 / f3 / fx", "Set selected tribe level 1-4") in agent_pairs
    assert ("fv", "Toggle all metadata folds") in agent_pairs
    assert ("f1 / fw / f3", "Set all folds to level 1-3") in patch_pairs
