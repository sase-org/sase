"""Tests for the Config Center Config-tab pure logic (Phase 4 read-only).

These exercise the pane's data view and the pure rendering / filtering helpers
without standing up a Textual app: the join between the field model and the
inventory provenance, modified detection, filter + modified-only narrowing,
ancestor reveal, row / source-rail / detail rendering, jump matching, and the
stat-token inventory cache. The widget wiring (worker load + tree population +
key handling) is covered by ``tests/ace/tui/test_config_pane_widget.py`` and the
Config Center PNG snapshots.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.modals import config_pane as cp
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model


def _fixture_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timezone": {
                "type": "string",
                "default": "America/New_York",
                "description": "IANA timezone name.",
            },
            "use_chezmoi": {"type": "boolean", "default": False},
            "axe": {
                "type": "object",
                "additionalProperties": False,
                "description": "AXE settings.",
                "properties": {
                    "max_hook_runners": {"type": "integer", "default": 3},
                    "chop_script_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                },
            },
            "ace": {
                "type": "object",
                "additionalProperties": False,
                "description": "ACE TUI settings.",
                "properties": {
                    "lumberjack": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "default": {
                            "builtin": {
                                "description": "Builtin check runner.",
                                "interval": "300s",
                            }
                        },
                        "description": "Named background lumberjack jobs.",
                    },
                },
            },
            "linked_repos": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
                "default": [],
            },
            "sibling_repos": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        },
    }


def _fixture_layers() -> list[ConfigLayer]:
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "axe": {"max_hook_runners": 3, "chop_script_dirs": ["a"]},
                "ace": {
                    "lumberjack": {
                        "builtin": {
                            "description": "Builtin check runner.",
                            "interval": "300s",
                        },
                    },
                },
                "linked_repos": [{"name": "core"}],
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/u/.config/sase/sase.yml",
            exists=True,
            list_strategy="replace",
            data={
                "timezone": "US/Pacific",
                "axe": {"max_hook_runners": 5},
                "ace": {
                    "lumberjack": {
                        "recent_audit": {
                            "description": "Audit recent saves.",
                            "interval": "900s",
                        },
                    },
                },
                "sibling_repos": [{"name": "dep"}],
            },
        ),
        ConfigLayer(
            name="overlay:sase_extra.yml",
            path="/home/u/.config/sase/sase_extra.yml",
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["c"]}},
        ),
        ConfigLayer(
            name="overlay:missing.yml",
            path="/home/u/.config/sase/missing.yml",
            exists=False,
            list_strategy="concatenate",
            data={},
        ),
    ]


@pytest.fixture
def view() -> cp.ConfigPaneView:
    schema = _fixture_schema()
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema=schema)
    return cp.ConfigPaneView.build(field_model, inventory)


# --- View join / derivations ----------------------------------------------


def test_view_joins_model_and_inventory_by_path(view: cp.ConfigPaneView) -> None:
    assert "axe.max_hook_runners" in view.fields_by_path
    assert "axe.max_hook_runners" in view.state_by_path
    assert view.kind_by_layer["user"] == "user"
    assert view.kind_by_layer["default"] == "builtin"


def test_winning_layer_is_highest_priority_contributor(
    view: cp.ConfigPaneView,
) -> None:
    assert view.winning_layer("timezone") == "user"
    assert view.winning_layer("axe.max_hook_runners") == "user"


def test_is_modified_only_for_writable_layer_contributions(
    view: cp.ConfigPaneView,
) -> None:
    # Set by the user layer -> modified.
    assert view.is_modified("timezone") is True
    assert view.is_modified("axe.max_hook_runners") is True
    # Only the built-in default contributes -> not modified.
    assert view.is_modified("use_chezmoi") is False


def test_modified_paths_lists_writable_touched_leaves(
    view: cp.ConfigPaneView,
) -> None:
    modified = view.modified_paths()
    assert "timezone" in modified
    assert "axe.max_hook_runners" in modified
    assert "axe.chop_script_dirs" in modified  # overlay contributed
    assert "use_chezmoi" not in modified


# --- Filtering / narrowing -------------------------------------------------


def test_visible_leaf_paths_unfiltered_returns_all_leaves(
    view: cp.ConfigPaneView,
) -> None:
    leaves = cp._visible_leaf_paths(view)
    assert "timezone" in leaves
    assert "axe.max_hook_runners" in leaves
    # Object containers are not leaves.
    assert "axe" not in leaves


def test_visible_leaf_paths_filters_by_path_and_description(
    view: cp.ConfigPaneView,
) -> None:
    assert cp._visible_leaf_paths(view, filter_text="timezone") == ["timezone"]
    # Description match ("IANA timezone name.") even without a path hit.
    assert "timezone" in cp._visible_leaf_paths(view, filter_text="iana")
    # Path-prefix match narrows to the axe subtree.
    axe_hits = cp._visible_leaf_paths(view, filter_text="axe.")
    assert set(axe_hits) == {"axe.max_hook_runners", "axe.chop_script_dirs"}


def test_visible_leaf_paths_modified_only(view: cp.ConfigPaneView) -> None:
    leaves = cp._visible_leaf_paths(view, modified_only=True)
    assert "timezone" in leaves
    assert "use_chezmoi" not in leaves


def test_visible_paths_includes_ancestor_sections(
    view: cp.ConfigPaneView,
) -> None:
    shown = cp._visible_paths(view, filter_text="max_hook")
    assert "axe.max_hook_runners" in shown
    assert "axe" in shown  # ancestor revealed so the leaf is reachable


# --- Row rendering ---------------------------------------------------------


def test_render_row_label_marks_modified_and_winning_layer(
    view: cp.ConfigPaneView,
) -> None:
    label = cp._render_row_label(view, "timezone")
    assert "●" in label.plain  # modified marker
    assert "timezone" in label.plain
    assert "user" in label.plain  # winning-layer badge
    assert "US/Pacific" in label.plain


def test_render_row_label_unmodified_has_no_marker(
    view: cp.ConfigPaneView,
) -> None:
    label = cp._render_row_label(view, "use_chezmoi")
    assert "●" not in label.plain
    assert "false" in label.plain


def test_format_row_value_summary_compacts_structured_values() -> None:
    assert cp._format_row_value_summary([1, 2, 3]) == "3 items"
    assert cp._format_row_value_summary({"name": "core"}) == "{...}"
    assert cp._format_row_value_summary("x" * 40) == ("x" * 29) + "..."


def test_render_row_label_section_is_bare_name(view: cp.ConfigPaneView) -> None:
    label = cp._render_row_label(view, "axe")
    assert label.plain == "axe"


def test_render_row_label_deprecated_field_struck(view: cp.ConfigPaneView) -> None:
    label = cp._render_row_label(view, "sibling_repos")
    assert "sibling_repos" in label.plain
    spans = [s for s in label.spans if "strike" in str(s.style)]
    assert spans, "deprecated field name should be struck through"


# --- Source rail -----------------------------------------------------------


def test_render_source_rail_lists_layers_with_badges(
    view: cp.ConfigPaneView,
) -> None:
    rail = cp._render_source_rail(view).plain
    assert "default" in rail
    assert "read-only" in rail  # built-in layer is read-only
    assert "user" in rail
    assert "missing" in rail  # overlay:missing.yml does not exist
    assert "keys" in rail


# --- Detail / provenance ---------------------------------------------------


def test_structured_value_predicate_distinguishes_blocks_from_inline() -> None:
    assert cp._is_structured_value({"enabled": True}) is True
    assert cp._is_structured_value({}) is False
    assert cp._is_structured_value([{"name": "core"}]) is True
    assert cp._is_structured_value([["builtin"]]) is True
    assert cp._is_structured_value(["builtin", "work"]) is False
    assert cp._is_structured_value(["x" * 24, "y" * 24]) is True
    assert cp._is_structured_value("plain") is False


def test_format_value_block_uses_sorted_multiline_yaml() -> None:
    assert (
        cp._format_value_block({"z": 1, "a": {"c": 3, "b": 2}})
        == "a:\n  b: 2\n  c: 3\nz: 1"
    )


def test_truncate_value_block_defaults_keep_large_detail_budget() -> None:
    code = "\n".join(f"line {index:03d}" for index in range(20))
    assert cp._truncate_value_block(code) == (code, 0)


def test_truncate_value_block_accepts_smaller_line_budget() -> None:
    code = "\n".join(f"line {index:03d}" for index in range(6))
    truncated, omitted = cp._truncate_value_block(code, max_lines=3)

    assert truncated == "line 000\nline 001\nline 002"
    assert omitted == 3


def test_truncate_value_block_caps_long_lines_before_rendering() -> None:
    code = "short\n" + ("x" * 20) + "\nlast"
    truncated, omitted = cp._truncate_value_block(code, max_line_width=10)

    assert truncated.splitlines() == ["short", "xxxxxxx...", "last"]
    assert omitted == 0


def test_render_detail_shows_value_and_priority_ordered_provenance(
    view: cp.ConfigPaneView,
) -> None:
    detail = cp._render_detail(view, "timezone").plain
    assert "default:" in detail
    assert "effective:" in detail
    assert "US/Pacific" in detail  # effective value from user layer
    assert "Provenance" in detail
    # Provenance is low -> high priority: default appears before user.
    assert detail.index("default") < detail.index("user")
    assert "▶" in detail  # winning marker present


def test_render_detail_keeps_scalar_values_inline(view: cp.ConfigPaneView) -> None:
    detail = cp._render_detail(view, "timezone").plain
    assert "default:   America/New_York" in detail
    assert "effective: US/Pacific" in detail


def test_render_detail_pretty_renders_object_values(view: cp.ConfigPaneView) -> None:
    rendered = cp._render_detail(view, "ace.lumberjack")
    detail = rendered.plain
    assert "default\n  builtin:\n    description: Builtin check runner." in detail
    assert "effective  user\n  builtin:" in detail
    assert "recent_audit:\n    description: Audit recent saves." in detail
    assert "  ▶ user\n      recent_audit:" in detail
    assert '{"' not in detail
    key_start = detail.index("recent_audit:")
    assert any(span.start <= key_start < span.end for span in rendered.spans)


def test_render_detail_pretty_renders_array_of_objects(
    view: cp.ConfigPaneView,
) -> None:
    rendered = cp._render_detail(view, "linked_repos")
    detail = rendered.plain
    assert "default:   []" in detail
    assert "effective  built-in\n  - name: core" in detail
    assert "  ▶ default\n      - name: core" in detail
    assert '[{"name": "core"}]' not in detail
    key_start = detail.index("name: core")
    assert any(span.start <= key_start < span.end for span in rendered.spans)


def test_render_detail_flags_deprecation_and_replacement(
    view: cp.ConfigPaneView,
) -> None:
    detail = cp._render_detail(view, "sibling_repos").plain
    assert "DEPRECATED" in detail
    assert "repos.linked" in detail  # replacement


def test_render_detail_section_summarizes_children(
    view: cp.ConfigPaneView,
) -> None:
    detail = cp._render_detail(view, "axe").plain
    assert "section" in detail
    assert "field(s)" in detail


def test_render_detail_none_is_placeholder(view: cp.ConfigPaneView) -> None:
    out = cp._render_detail(view, None)
    assert "Select a field" in out.plain


# --- Jump matching ---------------------------------------------------------


def test_match_path_prefers_exact_then_prefix_then_substring(
    view: cp.ConfigPaneView,
) -> None:
    assert cp.ConfigPane._match_path(view, "timezone") == "timezone"
    assert cp.ConfigPane._match_path(view, "axe.max") == "axe.max_hook_runners"
    assert cp.ConfigPane._match_path(view, "chop") == "axe.chop_script_dirs"
    assert cp.ConfigPane._match_path(view, "nonexistent") is None
    assert cp.ConfigPane._match_path(view, "") is None


# --- Inventory cache (stat-token) -----------------------------------------


def test_load_config_view_caches_by_stat_token() -> None:
    cp._clear_view_cache()
    calls = {"n": 0}
    real_inventory = build_config_inventory

    def counting_inventory(**_kwargs: Any) -> Any:
        calls["n"] += 1
        with patch(
            "sase.config.inventory.load_config_layers",
            return_value=_fixture_layers(),
        ):
            return real_inventory(schema=_fixture_schema())

    with (
        patch.object(cp, "current_config_token", return_value=("tok", 1)),
        patch.object(cp, "build_config_inventory", side_effect=counting_inventory),
        patch.object(
            cp,
            "config_field_model",
            return_value=config_field_model(_fixture_schema()),
        ),
    ):
        first = cp._load_config_view()
        second = cp._load_config_view()
        assert calls["n"] == 1  # second call served from cache
        assert second is first
        forced = cp._load_config_view(force=True)
        assert calls["n"] == 2  # force bypasses the cache
        assert forced.view is not None
    cp._clear_view_cache()


def test_load_config_view_reports_error_state() -> None:
    cp._clear_view_cache()
    with (
        patch.object(cp, "current_config_token", return_value=("tok", 2)),
        patch.object(cp, "build_config_inventory", side_effect=RuntimeError("boom")),
        patch.object(
            cp,
            "config_field_model",
            return_value=config_field_model(_fixture_schema()),
        ),
    ):
        result = cp._load_config_view()
    assert result.view is None
    assert result.error is not None and "boom" in result.error
    cp._clear_view_cache()
