"""Hinted fold collapse (uppercase ``H``) on a selected tribe panel."""

from __future__ import annotations

from sase.ace.tui.models.agent_panels import PanelKey
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui.test_agent_panel_hint_folding import _agent, _EntryApp


class _PanelFocusEntryApp(_EntryApp):
    """``_EntryApp`` with a settable whole-panel focus, like ``h`` selection."""

    def __init__(self, *, panel_collapsed: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._panel_focus_collapsed = panel_collapsed

    def _resolve_focused_panel(self) -> AgentPanelFocus:
        return AgentPanelFocus(
            panel_key=self._panel_group.focused_key,
            collapsed=self._panel_focus_collapsed,
        )

    def _record_agents_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: PanelKey = None,
    ) -> None:
        # AgentFoldingMixin's real ``_persist_group_fold_change`` precedes
        # ``_StubApp``'s stub in MRO once mixed with this class, so record
        # here instead of relying on that lower-priority override.
        self.group_persistence_intents.append((panel_key, group_key, collapsed))


def _workflow_app(**kwargs: object) -> _PanelFocusEntryApp:
    parent = _agent("flow", "alpha", workflow="flow")
    return _PanelFocusEntryApp(
        agents=[parent],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
        **kwargs,  # type: ignore[arg-type]
    )


def test_capital_h_arms_collapse_intent_and_hints_only_expanded_folds() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")  # COLLAPSED -> EXPANDED

    app.action_hooks_or_collapse_all()

    assert app._panel_fold_hint_mode_active is True
    assert app._panel_fold_hint_intent == "collapse"
    assert app._panel_fold_hint_snapshot == app._enumerate_panel_fold_hint_targets(
        collapsible_only=True
    )
    assert ("agent", "alpha", 0, "flow") in app._panel_fold_hint_snapshot
    assert app.footer.fold_hint_collapse_only is True


def test_capital_h_picked_banner_collapses_and_never_toggles_open() -> None:
    app = _PanelFocusEntryApp(collapsed_panels=set())
    app.action_hooks_or_collapse_all()
    group_target = next(
        target for target in app._panel_fold_hint_snapshot if target[0] == "group"
    )
    registry = app._group_fold_registry.for_panel("alpha")
    assert not registry.is_collapsed(group_target[2])

    assert app._handle_panel_fold_hint_key(app.hint_for(group_target)) is True

    assert registry.is_collapsed(group_target[2])
    assert app.group_persistence_intents == [("alpha", group_target[2], True)]
    assert app.notifications[-1] == "Fold collapsed"


def test_capital_h_picked_agent_fold_lands_collapsed_from_expanded() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")
    assert app._fold_manager.get("flow") == FoldLevel.EXPANDED

    app.action_hooks_or_collapse_all()
    target = next(
        target for target in app._panel_fold_hint_snapshot if target[0] == "agent"
    )
    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app._fold_manager.get("flow") == FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Fold collapsed"


def test_capital_h_picked_agent_fold_lands_collapsed_from_fully_expanded() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")
    app._fold_manager.expand("flow")
    assert app._fold_manager.get("flow") == FoldLevel.FULLY_EXPANDED

    app.action_hooks_or_collapse_all()
    target = next(
        target for target in app._panel_fold_hint_snapshot if target[0] == "agent"
    )
    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app._fold_manager.get("flow") == FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Fold collapsed"


def test_capital_h_selected_panel_with_no_expanded_folds_warns_without_arming() -> None:
    app = _workflow_app()
    assert app._fold_manager.get("flow") == FoldLevel.COLLAPSED
    app._group_fold_registry.for_panel("alpha").collapse(("flow",))
    assert app._enumerate_panel_fold_hint_targets(collapsible_only=True) == ()

    app.action_hooks_or_collapse_all()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "No expanded folds in the selected tribe"


def test_capital_h_collapsed_selected_panel_keeps_existing_warning() -> None:
    app = _PanelFocusEntryApp(collapsed_panels=set(), panel_collapsed=True)

    app.action_hooks_or_collapse_all()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "Panel is already collapsed"


def test_capital_h_escape_tears_down_without_mutating_fold_state() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")
    app.action_hooks_or_collapse_all()
    assert app._panel_fold_hint_mode_active is True

    assert app._handle_panel_fold_hint_key("escape") is True

    assert app._panel_fold_hint_mode_active is False
    assert app._panel_fold_hint_intent == "toggle"
    assert app._fold_manager.get("flow") == FoldLevel.EXPANDED


def test_capital_h_unmapped_key_exits_without_mutating_fold_state() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")
    app.action_hooks_or_collapse_all()

    assert app._handle_panel_fold_hint_key("?") is True

    assert app._panel_fold_hint_mode_active is False
    assert app._fold_manager.get("flow") == FoldLevel.EXPANDED


def test_capital_h_stale_snapshot_aborts_apply() -> None:
    app = _workflow_app()
    app._fold_manager.expand("flow")
    app.action_hooks_or_collapse_all()
    target = app._panel_fold_hint_snapshot[0]
    hint = app.hint_for(target)
    app._agents.append(_agent("new-alpha-project", "alpha"))
    app._invalidate_agent_panel_cache()

    app._handle_panel_fold_hint_key(hint)

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "Visible folds changed; retry fold selection"
    assert app._fold_manager.get("flow") == FoldLevel.EXPANDED


def test_arming_l_after_h_re_enumerates_with_toggle_intent() -> None:
    open_agent = _agent("flow-open", "alpha", workflow="flow-open")
    shut_agent = _agent("flow-shut", "alpha", workflow="flow-shut")
    app = _PanelFocusEntryApp(
        agents=[open_agent, shut_agent],
        collapsed_panels=set(),
        fold_counts={"flow-open": (1, 0), "flow-shut": (1, 0)},
    )
    app._fold_manager.expand("flow-open")  # COLLAPSED -> EXPANDED
    assert app._fold_manager.get("flow-shut") == FoldLevel.COLLAPSED

    app.action_hooks_or_collapse_all()

    assert app._panel_fold_hint_intent == "collapse"
    assert not any(
        target[0] == "agent" and target[3] == "flow-shut"
        for target in app._panel_fold_hint_snapshot
    )

    app.action_expand_all_folds()

    assert app._panel_fold_hint_intent == "toggle"
    assert app.footer.fold_hint_collapse_only is False
    assert app._panel_fold_hint_snapshot == app._enumerate_panel_fold_hint_targets()
    shut_target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "agent" and target[3] == "flow-shut"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(shut_target)) is True

    assert app._fold_manager.get("flow-shut") == FoldLevel.EXPANDED
    assert app.notifications[-1] == "Fold expanded"
