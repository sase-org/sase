"""Tests for config edit planning, previews, diffs, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.config.edit import ConfigEditError, ConfigEditOp, plan_config_edit
from tests._config_edit_helpers import (
    config_inventory,
    config_layer,
    user_file_inventory,
)


def test_plan_set_builds_write_plan_preview_and_diff(tmp_path: Path) -> None:
    """A set edit produces the write plan, candidate, preview, and text diff."""
    inventory, user_file = user_file_inventory(
        tmp_path, "", {"axe": {"max_hook_runners": 3}}
    )
    plan = plan_config_edit(
        inventory,
        "axe.max_hook_runners",
        "user",
        ConfigEditOp.set_value(9),
        use_chezmoi=False,
    )
    assert plan.write_plan.file == str(user_file)
    assert plan.write_plan.key_path == ("axe", "max_hook_runners")
    assert plan.write_plan.op == "set"
    assert plan.write_plan.new_value == 9
    assert plan.candidate_config == {"axe": {"max_hook_runners": 9}}
    assert plan.effective_preview.before == 3
    assert plan.effective_preview.after == 9
    assert plan.effective_preview.changed is True
    assert plan.is_valid is True
    assert plan.diagnostics == ()
    assert plan.target_path == str(user_file)
    assert "max_hook_runners: 9" in plan.new_text
    assert "+  max_hook_runners: 9" in plan.text_diff


def test_plan_unset_resets_to_default(tmp_path: Path) -> None:
    """Unsetting a user override makes the lower-layer default effective again."""
    inventory, _ = user_file_inventory(
        tmp_path,
        "timezone: US/Pacific\n",
        {"timezone": "America/New_York"},
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.unset(),
        use_chezmoi=False,
    )
    assert plan.write_plan.op == "unset"
    assert plan.effective_preview.before == "US/Pacific"
    assert plan.effective_preview.after == "America/New_York"
    assert plan.candidate_config == {"timezone": "America/New_York"}
    assert "timezone" not in plan.new_text


def test_plan_list_replace_vs_concatenate_consequence(tmp_path: Path) -> None:
    """Setting a list at a replace layer vs a concat layer differs in effect."""
    user_file = tmp_path / "sase.yml"
    overlay_file = tmp_path / "sase_extra.yml"
    user_file.write_text("", encoding="utf-8")
    overlay_file.write_text("", encoding="utf-8")
    layers = [
        config_layer("default", data={"linked_repos": [{"name": "core"}]}),
        config_layer("user", path=str(user_file), strategy="replace", data={}),
        config_layer(
            "overlay:sase_extra.yml",
            path=str(overlay_file),
            strategy="concatenate",
            data={},
        ),
    ]
    inventory = config_inventory(layers)
    new_list = [{"name": "x"}]

    to_user = plan_config_edit(
        inventory,
        "linked_repos",
        "user",
        ConfigEditOp.set_value(new_list),
        use_chezmoi=False,
    )
    to_overlay = plan_config_edit(
        inventory,
        "linked_repos",
        "overlay:sase_extra.yml",
        ConfigEditOp.set_value(new_list),
        use_chezmoi=False,
    )

    # User layer replaces the lower list; overlay concatenates onto it.
    assert to_user.effective_preview.after == [{"name": "x"}]
    assert to_overlay.effective_preview.after == [
        {"name": "core"},
        {"name": "x"},
    ]
    assert to_user.effective_preview.after != to_overlay.effective_preview.after


def test_plan_validation_flags_bad_value(tmp_path: Path) -> None:
    """A type-mismatched candidate surfaces validation diagnostics."""
    inventory, _ = user_file_inventory(tmp_path, "", {"timezone": "America/New_York"})
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value(123),
        use_chezmoi=False,
    )
    assert plan.is_valid is False
    assert any(d.code == "type_mismatch" for d in plan.validation)


def test_plan_unknown_target_raises(tmp_path: Path) -> None:
    """Targeting an unknown layer raises ConfigEditError."""
    inventory, _ = user_file_inventory(tmp_path, "", {"timezone": "America/New_York"})
    with pytest.raises(ConfigEditError):
        plan_config_edit(
            inventory,
            "timezone",
            "does-not-exist",
            ConfigEditOp.set_value("UTC"),
            use_chezmoi=False,
        )


def test_plan_readonly_target_emits_diagnostic() -> None:
    """Editing a non-writable target surfaces a plan-level diagnostic."""
    # The default layer has no path, so it is not writable.
    layers = [config_layer("default", data={"timezone": "America/New_York"})]
    inventory = config_inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "default",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    assert any(d.code == "target_not_writable" for d in plan.diagnostics)


def test_plan_exact_key_path_does_not_split_dotted_mapping_key(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sase.yml"
    target.write_text("", encoding="utf-8")
    inventory = config_inventory(
        [config_layer("user", path=str(target), strategy="replace", data={})],
        schema={"type": "object"},
    )
    plan = plan_config_edit(
        inventory,
        None,
        "user",
        ConfigEditOp.set_value(5),
        key_path=("axe", "lumberjacks", "checks.main", "interval"),
        use_chezmoi=False,
    )
    assert plan.write_plan.key_path == (
        "axe",
        "lumberjacks",
        "checks.main",
        "interval",
    )
    assert yaml.safe_load(plan.new_text)["axe"]["lumberjacks"]["checks.main"] == {
        "interval": 5
    }
