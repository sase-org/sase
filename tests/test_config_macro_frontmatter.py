"""Config-frontmatter macro cutover (sase-1eq.4.1.2).

Each authored layer normalizes to canonical macro spellings before merging;
local-helper frontmatter accepts ``macros``, gates ``xprompts`` through the
sunset flag, and rejects both spellings in both flag states. Writers emit
canonical keys and never leave two section keys behind.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.agent.multi_prompt import parse_multi_prompt
from sase.config._edit_plan import (
    _retired_counterpart_key_path,
    _without_retired_counterpart,
)
from sase.config.core import load_merged_config
from sase.feature_flags import override_flags
from sase.legacy_xprompt_syntax import normalize_frontmatter_macros
from sase.macro.config_yaml import insert_macro_into_config
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import load_config_macro_markdown
from sase.macro.workflow_loader_definition import load_workflow_from_mapping


def _merged_with_user(tmp_path: Path, user: dict) -> dict:
    (tmp_path / "sase.yml").write_text(yaml.dump(user))
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        return load_merged_config()


# --- layer normalization before merging ------------------------------------


def test_legacy_user_layer_normalizes_with_flag_enabled(tmp_path: Path) -> None:
    with override_flags(legacy_xprompt_syntax=True):
        result = _merged_with_user(
            tmp_path,
            {
                "xprompts": {"mine": "hello"},
                "xprompt_aliases": {"#m": "#mine"},
                "ace": {"prompt_completion": {"auto_xprompt_menu": False}},
            },
        )
    assert result["macros"]["mine"] == "hello"
    assert result["macro_aliases"]["#m"] == "#mine"
    assert result["ace"]["prompt_completion"]["auto_macro_menu"] is False
    assert "xprompts" not in result
    assert "xprompt_aliases" not in result


def test_legacy_user_layer_rejects_with_flag_disabled(tmp_path: Path) -> None:
    with (
        override_flags(legacy_xprompt_syntax=False),
        pytest.raises(ValueError, match=r"xprompts is retired; use macros"),
    ):
        _merged_with_user(tmp_path, {"xprompts": {"mine": "hello"}})


@pytest.mark.parametrize("enabled", [False, True])
def test_same_layer_collision_rejects_in_both_states(
    tmp_path: Path, enabled: bool
) -> None:
    with (
        override_flags(legacy_xprompt_syntax=enabled),
        pytest.raises(ValueError, match=r"cannot be combined"),
    ):
        _merged_with_user(tmp_path, {"xprompts": {"a": "x"}, "macros": {"b": "y"}})


@pytest.mark.parametrize("value", [None, {}, False, ""])
def test_legacy_presence_counts_even_for_empty_values(
    tmp_path: Path, value: object
) -> None:
    with override_flags(legacy_xprompt_syntax=True):
        result = _merged_with_user(tmp_path, {"xprompts": value})
        assert "macros" in result
        assert "xprompts" not in result
    with (
        override_flags(legacy_xprompt_syntax=False),
        pytest.raises(ValueError, match=r"xprompts is retired"),
    ):
        _merged_with_user(tmp_path, {"xprompts": value})


def test_canonical_default_and_legacy_user_override_share_precedence(
    tmp_path: Path,
) -> None:
    """Independent layers keep precedence instead of colliding after merging."""
    with override_flags(legacy_xprompt_syntax=True):
        result = _merged_with_user(tmp_path, {"xprompts": {"mine": "hello"}})
    # Bundled canonical defaults survive alongside the old user override.
    assert result["macros"]["mine"] == "hello"
    assert "bd/land_epic" in result["macros"]
    assert "xprompts" not in result


def test_nested_mentor_and_placeholder_keys_normalize(tmp_path: Path) -> None:
    with override_flags(legacy_xprompt_syntax=True):
        result = _merged_with_user(
            tmp_path,
            {
                "ace": {
                    "prompt_inputs": {"xprompt_placeholder_args": False},
                },
                "mentor_profiles": [
                    {
                        "profile_name": "p",
                        "mentors": [
                            {
                                "mentor_name": "m",
                                "role": "r",
                                "focus_areas": [],
                                "xprompt": "#mentor/a",
                            }
                        ],
                        "file_globs": ["*.py"],
                    }
                ],
            },
        )
    assert result["ace"]["prompt_inputs"]["macro_placeholder_args"] is False
    mentor = result["mentor_profiles"][0]["mentors"][0]
    assert mentor["macro"] == "#mentor/a"
    assert "xprompt" not in mentor


def test_malformed_user_layer_still_skipped(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text("macros: [not closed")
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
        override_flags(legacy_xprompt_syntax=True),
    ):
        result = load_merged_config()
    assert "bd/land_epic" in result["macros"]


def test_flag_change_recomputes_instead_of_reusing_stale_merge(
    tmp_path: Path,
) -> None:
    (tmp_path / "sase.yml").write_text(yaml.dump({"xprompts": {"mine": "hello"}}))
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        with override_flags(legacy_xprompt_syntax=True):
            assert load_merged_config()["macros"]["mine"] == "hello"
        with (
            override_flags(legacy_xprompt_syntax=False),
            pytest.raises(ValueError, match=r"xprompts is retired"),
        ):
            load_merged_config()


# --- local-helper frontmatter -----------------------------------------------


def test_frontmatter_accepts_canonical_in_both_states() -> None:
    raw = '---\nmacros:\n  _a: "hi"\n---'
    for enabled in (False, True):
        with override_flags(legacy_xprompt_syntax=enabled):
            assert PromptFrontmatter.parse(raw).macros["_a"].content == "hi"


def test_frontmatter_gates_retired_key_by_flag() -> None:
    raw = '---\nxprompts:\n  _a: "hi"\n---'
    with override_flags(legacy_xprompt_syntax=True):
        model = PromptFrontmatter.parse(raw)
        assert model.macros["_a"].content == "hi"
        # Canonical serialization never emits the retired spelling.
        assert "\nmacros:\n" in model.serialize()
        assert "xprompts" not in model.serialize()
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired; use macros"):
            PromptFrontmatter.parse(raw)


@pytest.mark.parametrize("enabled", [False, True])
def test_frontmatter_rejects_both_spellings_in_both_states(enabled: bool) -> None:
    raw = '---\nmacros:\n  _a: "hi"\nxprompts:\n  _b: "yo"\n---'
    with override_flags(legacy_xprompt_syntax=enabled):
        with pytest.raises(ValueError, match=r"cannot be combined"):
            PromptFrontmatter.parse(raw)


def test_user_prompt_helpers_follow_frontmatter_policy() -> None:
    text = '---\nmacros:\n  _a: "hi"\n---\n\nbody #_a'
    with override_flags(legacy_xprompt_syntax=True):
        assert parse_multi_prompt(text).local_macros["_a"].content == "hi"
    legacy = '---\nxprompts:\n  _a: "hi"\n---\n\nbody #_a'
    with override_flags(legacy_xprompt_syntax=True):
        assert parse_multi_prompt(legacy).local_macros["_a"].content == "hi"
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired"):
            parse_multi_prompt(legacy)
    both = '---\nmacros:\n  _a: "x"\nxprompts:\n  _b: "y"\n---\n\nbody'
    with override_flags(legacy_xprompt_syntax=True):
        with pytest.raises(ValueError, match=r"cannot be combined"):
            parse_multi_prompt(both)


def test_workflow_local_helpers_follow_frontmatter_policy() -> None:
    base = {
        "steps": [{"name": "main", "prompt_part": "hi"}],
    }
    with override_flags(legacy_xprompt_syntax=True):
        workflow = load_workflow_from_mapping(
            "w", {**base, "macros": {"_a": "hi"}}, "test"
        )
        assert workflow is not None and "_a" in workflow.macros
        legacy = load_workflow_from_mapping(
            "w", {**base, "xprompts": {"_a": "hi"}}, "test"
        )
        assert legacy is not None and "_a" in legacy.macros
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired"):
            load_workflow_from_mapping("w", {**base, "xprompts": {"_a": "hi"}}, "test")
    with override_flags(legacy_xprompt_syntax=True):
        with pytest.raises(ValueError, match=r"cannot be combined"):
            load_workflow_from_mapping(
                "w",
                {**base, "macros": {"_a": "x"}, "xprompts": {"_b": "y"}},
                "test",
            )


def test_nested_config_entry_helpers_follow_policy() -> None:
    from sase.macro.loader_parsing import parse_macro_entries

    with override_flags(legacy_xprompt_syntax=True):
        parsed = parse_macro_entries(
            {"a": {"content": "x", "macros": {"_h": "help"}}}, "test"
        )
        assert "_h" in parsed["a"].local_macros
        retired = parse_macro_entries(
            {"a": {"content": "x", "xprompts": {"_h": "help"}}}, "test"
        )
        assert "_h" in retired["a"].local_macros
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired"):
            parse_macro_entries(
                {"a": {"content": "x", "xprompts": {"_h": "help"}}}, "test"
            )


def test_normalize_frontmatter_mapping_shapes() -> None:
    assert normalize_frontmatter_macros(None) == {}
    assert normalize_frontmatter_macros({}, accept_legacy=True) == {}
    assert normalize_frontmatter_macros({"macros": None}, accept_legacy=True) == {}
    with pytest.raises(ValueError, match=r"cannot be combined"):
        normalize_frontmatter_macros(
            {"macros": {}, "xprompts": None},
            source="s",
            accept_legacy=True,
        )


# --- canonical writers --------------------------------------------------------


def test_config_insert_migrates_legacy_header(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("xprompts:\n  alpha: |\n    Alpha\n", encoding="utf-8")
    with override_flags(legacy_xprompt_syntax=True):
        assert insert_macro_into_config(str(config), "bravo", [], "Bravo") is True
    text = config.read_text(encoding="utf-8")
    assert "\nmacros:" in text or text.startswith("macros:")
    assert "xprompts:" not in text
    assert "bravo:" in text and "alpha:" in text


def test_config_insert_rejects_both_section_keys(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("macros:\n  a: A\nxprompts:\n  b: B\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"cannot be combined"):
        insert_macro_into_config(str(config), "c", [], "C")


def test_config_insert_appends_canonical_section(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("key: value\n", encoding="utf-8")
    assert insert_macro_into_config(str(config), "a", [], "A") is True
    text = config.read_text(encoding="utf-8")
    assert "\nmacros:\n" in text
    assert "xprompts:" not in text


def test_config_macro_reader_supports_legacy_while_enabled(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("xprompts:\n  a: hello\n", encoding="utf-8")
    with override_flags(legacy_xprompt_syntax=True):
        assert load_config_macro_markdown(config, "a") == "hello"
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired"):
            load_config_macro_markdown(config, "a")


def test_retired_counterpart_key_paths() -> None:
    assert _retired_counterpart_key_path(("macros", "a")) == ("xprompts", "a")
    assert _retired_counterpart_key_path(("macro_aliases",)) == ("xprompt_aliases",)
    assert _retired_counterpart_key_path(
        ("ace", "prompt_completion", "auto_macro_menu")
    ) == ("ace", "prompt_completion", "auto_xprompt_menu")
    assert _retired_counterpart_key_path(
        ("ace", "prompt_inputs", "macro_placeholder_args")
    ) == ("ace", "prompt_inputs", "xprompt_placeholder_args")
    assert _retired_counterpart_key_path(
        ("mentor_profiles", "0", "mentors", "1", "macro")
    ) == ("mentor_profiles", "0", "mentors", "1", "xprompt")
    assert _retired_counterpart_key_path(("workspace", "root")) is None
    assert _retired_counterpart_key_path(()) is None


def test_canonical_edit_removes_legacy_counterpart() -> None:
    text = "xprompts:\n  a: old\n"
    updated = _without_retired_counterpart(text, ("macros", "a"))
    assert "xprompts" not in updated
    # A surviving legacy entry stays; only its edited counterpart goes.
    kept = "xprompts:\n  a: old\n  b: keep\n"
    updated_kept = _without_retired_counterpart(kept, ("macros", "a"))
    assert "b: keep" in updated_kept
    assert "a: old" not in updated_kept
    # Missing counterparts are a no-op.
    canonical = "macros:\n  a: old\n"
    assert _without_retired_counterpart(canonical, ("macros", "a")) == canonical
    assert _without_retired_counterpart(text, ("workspace", "root")) == text


# --- TUI glue keeps explicit false working -------------------------------------


def test_prompt_completion_prefers_canonical_menu_key() -> None:
    from sase.ace.tui.widgets.prompt_completion import (
        parse_prompt_completion_settings,
    )

    assert (
        parse_prompt_completion_settings({"auto_macro_menu": False}).auto_xprompt_menu
        is False
    )
    assert (
        parse_prompt_completion_settings({"auto_macro_menu": True}).auto_xprompt_menu
        is True
    )
    assert (
        parse_prompt_completion_settings({"auto_xprompt_menu": False}).auto_xprompt_menu
        is False
    )


def test_placeholder_toggle_prefers_canonical_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.widgets import _local_macro_conversion as conversion

    (tmp_path / "sase.yml").write_text(
        yaml.dump({"ace": {"prompt_inputs": {"macro_placeholder_args": False}}})
    )
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
        override_flags(legacy_xprompt_syntax=True),
    ):
        assert conversion._xprompt_placeholder_args_enabled() is False
    monkeypatch.setattr(conversion, "_config_section", lambda data, key: {})
    assert conversion._xprompt_placeholder_args_enabled() is True
