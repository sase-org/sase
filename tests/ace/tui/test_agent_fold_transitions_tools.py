"""Fold-key dispatch tests for tools and non-agents tabs."""

from __future__ import annotations

from typing import Literal

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin

from ._agent_fold_transition_helpers import StubFoldApp, make_agent


class _ToolsDetail:
    def __init__(self, *, visible: bool = True, changed: bool = True) -> None:
        self.visible = visible
        self.changed = changed
        self.actions: list[str] = []

    def is_tools_visible(self) -> bool:
        return self.visible

    def expand_tools_detail(self) -> bool:
        self.actions.append("expand")
        return self.changed

    def collapse_tools_detail(self) -> bool:
        self.actions.append("collapse")
        return self.changed

    def set_tools_detail_level(self, level: object) -> bool:
        self.actions.append(f"set:{int(level)}")
        return self.changed


class _OtherTabExpandApp(AgentFoldingMixin):
    def __init__(self, current_tab: Literal["axe", "patches"]) -> None:
        self.current_tab = current_tab
        self.axe_expand_calls = 0
        self.patch_expand_calls = 0
        self.refresh_calls = 0

    def _expand_all_axe_folds(self) -> None:
        self.axe_expand_calls += 1

    def _expand_all_patch_group_folds(self) -> bool:
        self.patch_expand_calls += 1
        return True

    def _refresh_display(self) -> None:
        self.refresh_calls += 1


def test_tools_panel_h_navigates_while_capital_h_compacts_detail() -> None:
    agent = make_agent(agent_name="coder.claude", tribe="research")
    other = make_agent(agent_name="planner.codex", tribe="ops")
    detail = _ToolsDetail()
    app = StubFoldApp([agent, other], current_idx=0)
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")
    app._detail = detail

    app.action_expand_or_layout()
    app.action_hooks_or_collapse()
    app.action_expand_all_folds()
    app.action_hooks_or_collapse_all()

    assert detail.actions == ["expand", "set:0"]
    assert app._expanded_panel_focus is True
    assert app._panel_selection_memory["research"] == ("agent", 0)
    assert app.fold_selector_calls == 1
    assert app.refilter_calls == 0
    assert app.footer_refresh_calls == 2


def test_tools_panel_detail_clamp_does_not_fall_through_to_folds() -> None:
    agent = make_agent(agent_name="coder.claude")
    detail = _ToolsDetail(changed=False)
    app = StubFoldApp([agent], current_idx=0)
    app._detail = detail

    app.action_expand_or_layout()

    assert detail.actions == ["expand"]
    assert app.refilter_calls == 0
    assert app.footer_refresh_calls == 0


def test_capital_l_still_expands_all_folds_on_axe_but_not_patches() -> None:
    """sase-m6.9 moved Patches' fold-snap under the `z` fold-mode prefix (`zL`),
    freeing the bare `L` key for siblings' `artifacts_link_jump`. A bare `L`
    on Patches is now a no-op at this layer.
    """
    axe = _OtherTabExpandApp("axe")
    patches = _OtherTabExpandApp("patches")

    axe.action_expand_all_folds()
    patches.action_expand_all_folds()

    assert axe.axe_expand_calls == 1
    assert axe.refresh_calls == 0
    assert patches.patch_expand_calls == 0
    assert patches.refresh_calls == 0
