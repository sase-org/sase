"""Tests for config edit planning, the source-preserving writer, and targets.

Covers the Python-only half of the write path: the ``ruamel``-based round-trip
writer (comment/order preservation), the edit-planning wrapper (text diff +
effective preview + validation, including the list replace-vs-concatenate
consequence and reset-to-default), chezmoi source remapping, and the
write executor.
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from sase.config.core import ConfigLayer
from sase.config.edit import (
    AppliedResult,
    ConfigEditConflict,
    ConfigEditError,
    ConfigEditOp,
    apply_config_edit,
    plan_config_edit,
    set_key,
    unset_key,
)
from sase.config.inventory import build_config_inventory, inventory_with_new_overlay
from sase.config.targets import (
    CHEZMOI_HOME,
    apply_chezmoi,
    chezmoi_source_path,
    default_target_layer,
    overlay_config_path,
    resolve_write_path,
)


EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "definitions": {
        "repo": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
        }
    },
    "properties": {
        "timezone": {"type": "string", "default": "America/New_York"},
        "axe": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"max_hook_runners": {"type": "integer", "default": 3}},
        },
        "linked_repos": {
            "type": "array",
            "items": {"$ref": "#/definitions/repo"},
            "default": [],
        },
    },
}


def _layer(
    name: str,
    *,
    path: str | None = None,
    strategy: str = "concatenate",
    data: dict[str, Any] | None = None,
    exists: bool = True,
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=exists,
        list_strategy=strategy,
        data=data or {},
    )


def _inventory(layers: list[ConfigLayer], schema: dict[str, Any] | None = None) -> Any:
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        return build_config_inventory(schema=schema or EDIT_SCHEMA)


def _user_file_inventory(
    tmp_path: Path, user_text: str, default_data: dict[str, Any]
) -> tuple[Any, Path]:
    """Build a [default, user] inventory backed by a real user ``sase.yml``."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text(user_text, encoding="utf-8")
    user_data = yaml.safe_load(user_text) if user_text.strip() else {}
    layers = [
        _layer("default", data=default_data),
        _layer("user", path=str(user_file), strategy="replace", data=user_data or {}),
    ]
    return _inventory(layers), user_file


# --- Source-preserving writer ---------------------------------------------


def _diff_changed_lines(old: str, new: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="a/sase.yml",
            tofile="b/sase.yml",
        )
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def test_set_key_preserves_comments_and_order() -> None:
    """Setting a value keeps surrounding comments, key order, and quoting."""
    text = (
        "# top comment\n"
        'timezone: "US/Pacific"  # tz\n'
        "axe:\n"
        "  max_hook_runners: 3  # runners\n"
    )
    result = set_key(text, ("axe", "max_hook_runners"), 9)
    assert "# top comment" in result
    assert "# tz" in result
    assert "# runners" in result
    assert "max_hook_runners: 9" in result
    # Quoting style of the untouched scalar is preserved.
    assert '"US/Pacific"' in result


def test_set_key_changes_only_existing_scalar_line() -> None:
    """A scalar edit does not reflow unrelated YAML constructs."""
    text = (
        "github_orgs:\n"
        "  - sase-org\n"
        "linked_repos:\n"
        "  - name: core\n"
        "xprompts:\n"
        "  ship:\n"
        "    content: >-\n"
        "      one long folded line\n"
        "      that must stay folded\n"
        'flow: { type: line, default: "feature" }\n'
        "llm_provider:\n"
        "  model_aliases:\n"
        "    claude_coder: sonnet  # alias\n"
        "    phase_worker: codex/o3\n"
    )
    expected = text.replace(
        "    claude_coder: sonnet  # alias\n",
        "    claude_coder: opus  # alias\n",
    )

    result = set_key(text, ("llm_provider", "model_aliases", "claude_coder"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == [
        "-    claude_coder: sonnet  # alias",
        "+    claude_coder: opus  # alias",
    ]


def test_set_key_preserves_existing_quote_style_on_scalar_replace() -> None:
    result = set_key('timezone: "US/Pacific"  # tz\n', ("timezone",), "UTC")
    assert result == 'timezone: "UTC"  # tz\n'


def test_set_key_inserts_one_alias_line_under_existing_mapping() -> None:
    text = (
        "llm_provider:\n"
        "  model_aliases:\n"
        "    coder: sonnet\n"
        "    phase_worker: codex/o3\n"
    )
    expected = (
        "llm_provider:\n"
        "  model_aliases:\n"
        "    coder: sonnet\n"
        "    phase_worker: codex/o3\n"
        "    reviewer: opus\n"
    )

    result = set_key(text, ("llm_provider", "model_aliases", "reviewer"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == ["+    reviewer: opus"]


def test_set_key_creates_missing_alias_section_without_touching_existing_text() -> None:
    text = (
        "github_orgs:\n"
        "  - sase-org\n"
        "xprompts:\n"
        "  ship:\n"
        "    content: >-\n"
        "      keep\n"
        "      wrapped\n"
    )
    expected = text + "llm_provider:\n" + "  model_aliases:\n" + "    reviewer: opus\n"

    result = set_key(text, ("llm_provider", "model_aliases", "reviewer"), "opus")

    assert result == expected
    assert _diff_changed_lines(text, result) == [
        "+llm_provider:",
        "+  model_aliases:",
        "+    reviewer: opus",
    ]


def test_set_key_creates_intermediate_mappings() -> None:
    """Setting a nested key on an empty document builds the parent mapping."""
    result = set_key("", ("axe", "max_hook_runners"), 5)
    assert yaml.safe_load(result) == {"axe": {"max_hook_runners": 5}}


def test_unset_key_removes_only_the_target() -> None:
    """Unsetting removes the key and its inline comment, keeping the rest."""
    text = (
        "# top comment\n"
        "timezone: US/Pacific  # tz\n"
        "axe:\n"
        "  max_hook_runners: 3  # runners\n"
    )
    result = unset_key(text, ("timezone",))
    assert "timezone" not in result
    assert "# top comment" in result
    assert "max_hook_runners: 3" in result


def test_unset_key_removes_only_target_alias_line() -> None:
    text = (
        "llm_provider:\n"
        "  model_aliases:\n"
        "    coder: sonnet  # remove\n"
        "    phase_worker: codex/o3\n"
    )
    expected = "llm_provider:\n  model_aliases:\n    phase_worker: codex/o3\n"

    result = unset_key(text, ("llm_provider", "model_aliases", "coder"))

    assert result == expected
    assert _diff_changed_lines(text, result) == ["-    coder: sonnet  # remove"]


def test_unset_key_missing_path_is_noop() -> None:
    """Unsetting an absent key returns the original text unchanged."""
    text = "timezone: US/Pacific\n"
    assert unset_key(text, ("nope",)) == text
    assert unset_key(text, ("a", "b")) == text


def test_set_key_declined_value_shape_falls_back_to_round_trip() -> None:
    text = "llm_provider:\n  model_aliases:\n    coder: sonnet\n"
    result = set_key(
        text,
        ("llm_provider", "model_aliases"),
        {"coder": "opus", "reviewer": "sonnet"},
    )
    assert yaml.safe_load(result) == {
        "llm_provider": {"model_aliases": {"coder": "opus", "reviewer": "sonnet"}}
    }


def test_set_key_safety_rejection_uses_round_trip_fallback() -> None:
    text = "llm_provider:\n  model_aliases:\n    coder: sonnet\n"
    key_path = ("llm_provider", "model_aliases", "coder")
    with (
        patch(
            "sase.config._edit_yaml_surgical._parsed_edit_matches", return_value=False
        ),
        patch(
            "sase.config._edit_yaml._set_key_round_trip", return_value="fallback\n"
        ) as fallback,
    ):
        assert set_key(text, key_path, "opus") == "fallback\n"
    fallback.assert_called_once_with(text, key_path, "opus")


# --- Edit planning --------------------------------------------------------


def test_plan_set_builds_write_plan_preview_and_diff(tmp_path: Path) -> None:
    """A set edit produces the write plan, candidate, preview, and text diff."""
    inventory, user_file = _user_file_inventory(
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
    inventory, user_file = _user_file_inventory(
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
        _layer("default", data={"linked_repos": [{"name": "core"}]}),
        _layer("user", path=str(user_file), strategy="replace", data={}),
        _layer(
            "overlay:sase_extra.yml",
            path=str(overlay_file),
            strategy="concatenate",
            data={},
        ),
    ]
    inventory = _inventory(layers)
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
    inventory, _ = _user_file_inventory(tmp_path, "", {"timezone": "America/New_York"})
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
    inventory, _ = _user_file_inventory(tmp_path, "", {"timezone": "America/New_York"})
    with pytest.raises(ConfigEditError):
        plan_config_edit(
            inventory,
            "timezone",
            "does-not-exist",
            ConfigEditOp.set_value("UTC"),
            use_chezmoi=False,
        )


def test_plan_readonly_target_emits_diagnostic(tmp_path: Path) -> None:
    """Editing a non-writable target surfaces a plan-level diagnostic."""
    # The default layer has no path, so it is not writable.
    layers = [_layer("default", data={"timezone": "America/New_York"})]
    inventory = _inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "default",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    assert any(d.code == "target_not_writable" for d in plan.diagnostics)


# --- Write execution ------------------------------------------------------


def test_apply_config_edit_writes_previewed_text(tmp_path: Path) -> None:
    """apply writes exactly the previewed text, preserving comments."""
    inventory, user_file = _user_file_inventory(
        tmp_path,
        "# keep me\naxe:\n  max_hook_runners: 3  # runners\n",
        {"axe": {"max_hook_runners": 3}},
    )
    plan = plan_config_edit(
        inventory,
        "axe.max_hook_runners",
        "user",
        ConfigEditOp.set_value(9),
        use_chezmoi=False,
    )
    result = apply_config_edit(plan)
    assert isinstance(result, AppliedResult)
    assert result.path == str(user_file)
    assert result.created is False
    written = user_file.read_text(encoding="utf-8")
    assert written == plan.new_text
    assert "# keep me" in written
    assert "# runners" in written
    assert yaml.safe_load(written)["axe"]["max_hook_runners"] == 9


def test_apply_config_edit_creates_missing_file(tmp_path: Path) -> None:
    """apply creates a fresh target file (and parents) when absent."""
    target = tmp_path / "nested" / "sase.yml"
    layers = [
        _layer("default", data={"timezone": "America/New_York"}),
        _layer("user", path=str(target), strategy="replace", data={}, exists=False),
    ]
    inventory = _inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    result = apply_config_edit(plan)
    assert result.created is True
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"timezone": "UTC"}


def test_apply_config_edit_without_target_raises() -> None:
    """apply refuses a plan that has no writable target file."""
    layers = [_layer("default", data={"timezone": "America/New_York"})]
    inventory = _inventory(layers)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "default",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    # The default layer is package-backed (no file), so there is no target.
    assert plan.target_path is None
    with pytest.raises(ConfigEditError):
        apply_config_edit(plan)


def test_plan_exact_key_path_does_not_split_dotted_mapping_key(tmp_path: Path) -> None:
    target = tmp_path / "sase.yml"
    target.write_text("", encoding="utf-8")
    inventory = _inventory(
        [_layer("user", path=str(target), strategy="replace", data={})],
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


def test_apply_config_edit_rejects_stale_existing_target(tmp_path: Path) -> None:
    inventory, target = _user_file_inventory(
        tmp_path,
        "timezone: US/Pacific\n",
        {"timezone": "America/New_York"},
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    target.write_text("timezone: Europe/London\n", encoding="utf-8")
    with (
        patch("sase.config._edit_plan.clear_config_cache") as clear_cache,
        pytest.raises(ConfigEditConflict),
    ):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == "timezone: Europe/London\n"
    clear_cache.assert_not_called()


def test_apply_config_edit_rejects_stale_absent_target(tmp_path: Path) -> None:
    target = tmp_path / "new" / "sase.yml"
    inventory = _inventory(
        [
            _layer("default", data={"timezone": "America/New_York"}),
            _layer(
                "user",
                path=str(target),
                strategy="replace",
                data={},
                exists=False,
            ),
        ]
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    target.parent.mkdir(parents=True)
    target.write_text("timezone: Asia/Tokyo\n", encoding="utf-8")
    with pytest.raises(ConfigEditConflict):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == "timezone: Asia/Tokyo\n"


def test_apply_config_edit_preserves_mode_and_clears_cache_after_replace(
    tmp_path: Path,
) -> None:
    inventory, target = _user_file_inventory(
        tmp_path,
        "timezone: US/Pacific\n",
        {"timezone": "America/New_York"},
    )
    target.chmod(0o640)
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    with patch("sase.config._edit_plan.clear_config_cache") as clear_cache:
        apply_config_edit(plan)
        assert target.read_text(encoding="utf-8") == plan.new_text
        clear_cache.assert_called_once_with()
    assert target.stat().st_mode & 0o777 == 0o640


def test_apply_config_edit_replace_failure_keeps_original_and_cleans_temp(
    tmp_path: Path,
) -> None:
    original = "timezone: US/Pacific\n"
    inventory, target = _user_file_inventory(
        tmp_path,
        original,
        {"timezone": "America/New_York"},
    )
    plan = plan_config_edit(
        inventory,
        "timezone",
        "user",
        ConfigEditOp.set_value("UTC"),
        use_chezmoi=False,
    )
    with (
        patch("sase.config._edit_plan.os.replace", side_effect=OSError("boom")),
        patch("sase.config._edit_plan.clear_config_cache") as clear_cache,
        pytest.raises(OSError, match="boom"),
    ):
        apply_config_edit(plan)
    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []
    clear_cache.assert_not_called()


# --- Chezmoi remapping & targets ------------------------------------------


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
    with patch("sase.config.targets.subprocess.run", run_mock):
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
    with patch("sase.config.targets.subprocess.run", run_mock):
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
        _layer("default", data={"timezone": "America/New_York"}),
        _layer(
            "user",
            path=str(user_file),
            strategy="replace",
            data={"timezone": "US/Pacific"},
        ),
    ]
    inventory = _inventory(layers)
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
        _layer("default", data={"timezone": "America/New_York"}),
        _layer("user", path=str(user_file), strategy="replace", data={}),
    ]
    inventory = _inventory(layers)
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


# --- Create-overlay target ------------------------------------------------


def test_inventory_with_new_overlay_inserts_highest_priority_overlay(
    tmp_path: Path,
) -> None:
    """A new overlay is added as the highest-priority writable overlay."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text("timezone: US/Pacific\n", encoding="utf-8")
    layers = [
        _layer("default", data={"timezone": "America/New_York"}),
        _layer(
            "user",
            path=str(user_file),
            strategy="replace",
            data={"timezone": "US/Pacific"},
        ),
    ]
    inventory = _inventory(layers)
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
        _layer("default", data={"timezone": "America/New_York"}),
        _layer(
            "overlay:sase_extra.yml",
            path=str(overlay_file),
            strategy="concatenate",
            data={"timezone": "US/Eastern"},
        ),
    ]
    inventory = _inventory(layers)
    same, layer_name = inventory_with_new_overlay(inventory, "extra")
    assert layer_name == "overlay:sase_extra.yml"
    assert same is inventory  # unchanged: the overlay already exists
