from __future__ import annotations

import pytest

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.ace.tui.widgets.tools_panel import ToolDetailLevel
from tests.ace.tui._agent_fold_transition_helpers import (
    StubFoldApp,
    make_loader_shaped_aliased_plan_family,
    make_standalone_workflow_lane,
)


def _labels(bindings: list[tuple[str, str]]) -> set[tuple[str, str]]:
    return set(bindings)


def test_footer_tools_detail_chips_follow_level() -> None:
    footer = KeybindingFooter()

    compact = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.COMPACT,
        )
    )
    expanded = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        )
    )
    full = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.FULL,
        )
    )
    hidden = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=False,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        )
    )

    assert ("l", "more detail") in compact
    assert ("h", "less detail") not in compact
    assert ("H", "compact tools") not in compact
    assert ("l", "more detail") in expanded
    assert ("h", "less detail") not in expanded
    assert ("H", "compact tools") in expanded
    assert ("l", "more detail") not in full
    assert ("h", "less detail") not in full
    assert ("H", "compact tools") in full
    assert ("l", "more detail") not in hidden
    assert ("h", "less detail") not in hidden
    assert ("H", "compact tools") not in hidden


def test_footer_without_selected_agent_omits_agent_only_actions() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        completed_count=3,
        marked_count=0,
    )
    labels = {label for _key, label in bindings}

    assert labels == {"cleanup (3 done)"}
    assert labels.isdisjoint(
        {"retry", "dismiss", "kill", "edit chat", "edit tribe", "tmux"}
    )


def test_footer_selected_panel_advertises_hinted_collapse_fold() -> None:
    footer = KeybindingFooter()

    collapsible = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=False,
            panel_hint_collapse_available=True,
            panel_isolation_available=True,
        )
    )
    # Row-focus availability flags are ignored while whole-panel focus holds,
    # since the panel-wide ladder they used to drive is retired.
    row_flags_ignored = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=False,
            lane_collapse_available=True,
            clan_collapse_available=True,
            group_collapse_available=True,
        )
    )
    terminal = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=False,
        )
    )
    collapsed = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=True,
            panel_isolation_available=True,
        )
    )
    collapsed_with_jump = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=True,
            panel_collapse_jump_available=True,
        )
    )

    assert ("H", "collapse fold") in collapsible
    assert not any(key == "H" for key, _label in row_flags_ignored)
    assert ("h", "collapse panel") in terminal
    assert not any(key == "H" for key, _label in terminal)
    assert ("=", "only panel") in collapsible
    assert ("=", "only panel") in collapsed
    assert not any(key == "H" for key, _label in collapsed)
    assert ("h", "last expanded panel") not in collapsed
    assert ("h", "last expanded panel") in collapsed_with_jump


def test_footer_armed_panel_isolation_advertises_restore_action() -> None:
    footer = KeybindingFooter()

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_restore_armed=True,
            panel_isolation_available=True,
        )
    )

    assert ("=", "restore panels") in bindings
    assert ("=", "only panel") not in bindings
    assert ("H", "restore panels") not in bindings


def test_footer_panel_fold_sweep_chip_follows_availability() -> None:
    footer = KeybindingFooter()

    sweep_available = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_fold_sweep_available=True,
        )
    )
    restore_armed = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_fold_restore_armed=True,
        )
    )
    neither = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
        )
    )

    assert ("-", "collapse folds") in sweep_available
    assert ("-", "restore folds") not in sweep_available
    assert ("-", "restore folds") in restore_armed
    assert ("-", "collapse folds") not in restore_armed
    assert not any(key == "-" for key, _label in neither)


def test_footer_panel_fold_sweep_prefers_collapse_over_restore_chip() -> None:
    footer = KeybindingFooter()

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_fold_sweep_available=True,
            panel_fold_restore_armed=True,
        )
    )

    assert ("-", "collapse folds") in bindings
    assert ("-", "restore folds") not in bindings


def test_footer_row_focus_advertises_isolation_when_two_or_more_panels() -> None:
    footer = KeybindingFooter()

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=False,
            panel_isolation_available=True,
        )
    )
    armed = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=False,
            panel_isolation_available=True,
            panel_restore_armed=True,
        )
    )

    assert ("=", "only panel") in bindings
    assert ("=", "restore panels") in armed
    assert ("=", "only panel") not in armed


def test_footer_panel_isolation_uses_custom_isolate_action_key() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry(
            {
                "keymaps": {
                    "app": {
                        "isolate_panels": "f2",
                        "hooks_or_collapse_all": "f3",
                    }
                }
            }
        )
    )

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_hint_collapse_available=True,
            panel_isolation_available=True,
        )
    )

    assert ("<f2>", "only panel") in bindings
    assert ("<f3>", "collapse fold") in bindings


def test_footer_selected_panel_hinted_collapse_uses_custom_collapse_action_key() -> (
    None
):
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry({"keymaps": {"app": {"hooks_or_collapse_all": "f3"}}})
    )

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_hint_collapse_available=True,
        )
    )

    assert ("<f3>", "collapse fold") in bindings


def test_footer_selected_clan_rung_uses_singular_custom_collapse_action_key() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry({"keymaps": {"app": {"hooks_or_collapse_all": "f3"}}})
    )

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            clan_collapse_available=True,
            selected_clan_collapse_available=True,
        )
    )

    assert ("<f3>", "collapse clan") in bindings
    assert ("<f3>", "collapse clans") not in bindings


def test_footer_left_navigation_and_collapse_target_labels() -> None:
    footer = KeybindingFooter()

    workflow = _labels(
        footer._compute_agent_bindings(None, left_navigation_kind="workflow")
    )
    family = _labels(
        footer._compute_agent_bindings(None, left_navigation_kind="family")
    )
    clan = _labels(footer._compute_agent_bindings(None, left_navigation_kind="clan"))
    tribe = _labels(
        footer._compute_agent_bindings(
            None,
            left_navigation_kind="tribe",
            group_focused=True,
        )
    )
    tools = _labels(
        footer._compute_agent_bindings(
            None,
            left_navigation_kind="family",
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        )
    )
    panel = _labels(
        footer._compute_agent_bindings(
            None,
            left_navigation_kind="family",
            panel_focused=True,
            structural_collapse_kind="family",
            panel_isolation_available=True,
        )
    )
    workflow_collapse = _labels(
        footer._compute_agent_bindings(
            None,
            structural_collapse_kind="workflow",
        )
    )
    family_collapse = _labels(
        footer._compute_agent_bindings(None, structural_collapse_kind="family")
    )
    clan_collapse = _labels(
        footer._compute_agent_bindings(None, structural_collapse_kind="clan")
    )
    selected_clan_collapse = _labels(
        footer._compute_agent_bindings(
            None,
            clan_collapse_available=True,
            selected_clan_collapse_available=True,
        )
    )
    group_clan_collapse = _labels(
        footer._compute_agent_bindings(
            None,
            clan_collapse_available=True,
        )
    )
    lane_collapse = _labels(
        footer._compute_agent_bindings(
            None,
            lane_collapse_available=True,
            clan_collapse_available=True,
            structural_collapse_kind="clan",
            group_collapse_available=True,
        )
    )
    panel_hinted_collapse = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_hint_collapse_available=True,
            clan_collapse_available=True,
            structural_collapse_kind="family",
            group_collapse_available=True,
        )
    )
    group_collapse = _labels(
        footer._compute_agent_bindings(None, group_collapse_available=True)
    )

    assert ("h", "parent workflow") in workflow
    assert ("h", "parent family") in family
    assert ("h", "parent clan") in clan
    assert ("h", "parent tribe") in tribe
    assert ("h", "parent family") in tools
    assert ("H", "compact tools") in tools
    assert not any(label.startswith("parent ") for _key, label in panel)
    assert ("=", "only panel") in panel
    assert ("H", "only panel") not in panel
    assert ("H", "collapse workflow") in workflow_collapse
    assert ("H", "collapse family") in family_collapse
    assert ("H", "collapse clan") in clan_collapse
    assert ("H", "collapse clan") in selected_clan_collapse
    assert ("H", "collapse clans") not in selected_clan_collapse
    assert ("H", "collapse clans") in group_clan_collapse
    assert ("H", "collapse clan") not in group_clan_collapse
    assert ("H", "collapse sase agents") in lane_collapse
    assert ("H", "collapse clan") not in lane_collapse
    assert ("H", "collapse group") not in lane_collapse
    # Whole-panel focus ignores row-scoped availability flags and shows the
    # single hinted-collapse chip instead of the retired panel-wide ladder.
    assert ("H", "collapse fold") in panel_hinted_collapse
    assert ("H", "collapse clans") not in panel_hinted_collapse
    assert ("H", "collapse family") not in panel_hinted_collapse
    assert ("H", "collapse group") not in panel_hinted_collapse
    assert ("H", "collapse group") in group_collapse


@pytest.mark.parametrize("step_kind", ["bash", "python", "pre_prompt"])
def test_footer_labels_aliased_family_workflow_steps_from_shared_resolver(
    step_kind: str,
) -> None:
    agents, _root, _main, _coder, steps = make_loader_shaped_aliased_plan_family()
    app = StubFoldApp(agents, current_idx=agents.index(steps[step_kind]))
    target = app._resolve_agent_left_navigation_target()
    assert target is not None

    bindings = _labels(
        KeybindingFooter()._compute_agent_bindings(
            None,
            left_navigation_kind=target.kind,
        )
    )

    assert ("h", "parent family") in bindings


def test_footer_omits_parent_for_invalid_ancestry() -> None:
    agents, root, steps = make_standalone_workflow_lane()
    selected = steps["python"]
    selected.tree_parent_key = root.raw_suffix
    selected.tree_depth = 7
    app = StubFoldApp(agents, current_idx=agents.index(selected))
    target = app._resolve_agent_left_navigation_target()

    bindings = _labels(
        KeybindingFooter()._compute_agent_bindings(
            None,
            left_navigation_kind=None if target is None else target.kind,
        )
    )

    assert not any(label.startswith("parent ") for _key, label in bindings)


def test_footer_saturated_hidden_leaf_advertises_group_lane_collapse() -> None:
    agents, root, steps = make_standalone_workflow_lane()
    app = StubFoldApp(agents, current_idx=agents.index(steps["pre_prompt"]))
    assert root.raw_suffix is not None
    app._fold_manager.expand(root.raw_suffix)
    app._fold_manager.expand(root.raw_suffix)
    assert app._fold_manager.get(root.raw_suffix) is FoldLevel.FULLY_EXPANDED
    left = app._resolve_agent_left_navigation_target()
    collapse = app._resolve_sase_agent_collapse_target()
    assert left is not None
    assert collapse is not None

    bindings = _labels(
        KeybindingFooter()._compute_agent_bindings(
            None,
            left_navigation_kind=left.kind,
            lane_collapse_available=True,
        )
    )

    assert ("h", "parent workflow") in bindings
    assert ("H", "collapse sase agents") in bindings
