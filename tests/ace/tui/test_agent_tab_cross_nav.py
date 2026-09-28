"""Switch-then-reveal cross-tab navigation tests (sase-1bc.6.1.4).

Covers the shared ``_ensure_agent_tab_for`` helper (switch, same-tab and
unknown-identity no-ops, flag-off identity), the off-tab label map, the
shared reveal ladder, jump-back anchors across tabs, ``,J`` stopped jumps,
and Node Finder omission of off-tab rows.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents._agent_tab_jump import (
    ensure_agent_tab_for_identity,
    off_tab_labels_for_owner,
    restore_agent_tab,
)
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.actions.agents._node_finder_finalize import (
    apply_snapshot_omission,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY
from sase.feature_flags import override_flags

from ._agent_tab_cross_nav_helpers import (
    SASE,
    AnchorOwner,
    cross_tab_harness_class,
    finder_row,
    prepare_cross_tab_app,
    row,
    two_tab_owner,
    view,
)
from ._agent_unread_navigation_helpers import UnreadJumpApp


def test_ensure_switches_to_target_tab() -> None:
    owner = two_tab_owner()
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert [a.raw_suffix for a in owner._agents] == ["a"]
    previous = ensure_agent_tab_for_identity(
        owner, owner._agents_with_children[1].identity
    )
    assert previous == DEFAULT_AGENT_TAB_KEY
    assert owner._active_agent_tab == SASE
    assert [a.raw_suffix for a in owner._agents] == ["b"]


def test_ensure_accepts_row_and_mixin_reports_switch() -> None:
    owner = two_tab_owner()
    assert owner._ensure_agent_tab_for(owner._agents_with_children[1]) is True
    assert owner._active_agent_tab == SASE
    assert owner._ensure_agent_tab_for(owner._agents_with_children[1]) is False


def test_ensure_noop_same_tab_and_unknown() -> None:
    owner = two_tab_owner()
    assert (
        ensure_agent_tab_for_identity(owner, owner._agents_with_children[0].identity)
        is None
    )
    assert (
        ensure_agent_tab_for_identity(owner, (AgentType.RUNNING, "x", "nope")) is None
    )


def test_restore_agent_tab_returns_to_previous() -> None:
    owner = two_tab_owner()
    previous = ensure_agent_tab_for_identity(
        owner, owner._agents_with_children[1].identity
    )
    assert owner._active_agent_tab == SASE
    restore_agent_tab(owner, previous)
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert [a.raw_suffix for a in owner._agents] == ["a"]
    restore_agent_tab(owner, None)


def test_off_tab_labels_for_owner() -> None:
    owner = two_tab_owner()
    labels = off_tab_labels_for_owner(owner)
    assert labels == {owner._agents_with_children[1].identity: "sase"}


def test_try_reveal_agent_row_switches_tabs() -> None:
    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows)
    app._agents = _scoped_agents_for_owner(app, list(rows))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0
    failure = app._try_reveal_agent_row(rows[1].identity)
    assert failure is None
    assert app._active_agent_tab == SASE
    assert app._agents[app.current_idx].identity == rows[1].identity


def test_try_reveal_agent_row_back_jump_restores_source_tab_and_row() -> None:
    """A real cross-tab jump, then a back-jump, returns to the origin.

    The pre-fix ``_try_reveal_agent_row`` switched tabs (via
    ``ensure_agent_tab_for_identity``) before capturing the source row and
    saving the back-anchor, so the anchor recorded the destination tab's own
    remembered row instead of where the jump started. The existing
    back/forward tests call ``_ensure_agent_tab_for`` directly and never
    exercised the reveal's own ordering.
    """
    from sase.ace.tui.actions.agents._tab_scope import AgentTabScopeMixin

    class _Harness(cross_tab_harness_class(), AgentTabScopeMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app._agents = _scoped_agents_for_owner(app, list(rows))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0

    failure = app._try_reveal_agent_row(rows[1].identity)
    assert failure is None
    assert app._active_agent_tab == SASE
    assert app._agents[app.current_idx].identity == rows[1].identity

    anchor = app._entry_jump_agents_anchor_stack[-1]
    assert anchor[0] == "agent"
    assert anchor[1] == 0
    assert anchor[-1] == "default"

    assert app._restore_agents_jump_anchor() is True
    assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert app._agents[app.current_idx].identity == rows[0].identity


def test_failed_reveal_restores_previous_tab() -> None:
    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows)
    # The cached query result is stale: it no longer holds the target, so
    # the post-switch reveal filters it out and must restore the old tab.
    app._agents_query_result = [rows[0]]
    app._entry_jump_agents_anchor_stack = [("agent", 0, None, "default")]
    app._entry_jump_agents_forward_anchor_stack = [("agent", 1, None, "named:sase")]
    saved_back = list(app._entry_jump_agents_anchor_stack)
    saved_forward = list(app._entry_jump_agents_forward_anchor_stack)
    app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0
    from sase.ace.tui.actions.navigation._agent_reveal import AgentRevealFailure

    failure = app._try_reveal_agent_row(rows[1].identity)
    assert failure is AgentRevealFailure.TARGET_FILTERED
    assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert app._entry_jump_agents_anchor_stack == saved_back
    assert app._entry_jump_agents_forward_anchor_stack == saved_forward


def test_jump_anchor_records_tab_and_restores_across_tabs() -> None:
    owner = AnchorOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    owner.current_idx = 0
    owner._save_agents_jump_anchor()
    saved = owner._entry_jump_agents_anchor_stack[-1]
    assert saved == ("agent", 0, None, "default")
    assert owner._ensure_agent_tab_for(owner._agents_with_children[1].identity) is True
    assert owner._restore_agents_jump_anchor() is True
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert owner.current_idx == 0


def test_jump_forward_returns_across_tabs() -> None:
    owner = AnchorOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    owner.current_idx = 0
    owner._save_agents_jump_anchor()
    assert owner._ensure_agent_tab_for(owner._agents_with_children[1].identity) is True
    assert owner._restore_agents_jump_anchor() is True
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    forward_stack = owner._entry_jump_agents_forward_stack()
    assert forward_stack == [("agent", 0, None, "named:sase")]
    anchor = owner._pop_agents_jump_anchor(forward_stack)
    assert anchor is not None
    owner._restore_agents_jump_anchor_value(anchor)
    assert owner._active_agent_tab == SASE
    assert owner.current_idx == 0


def test_jump_anchor_with_gone_tab_is_dropped() -> None:
    owner = AnchorOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    owner._entry_jump_agents_anchor_stack.append(("agent", 0, None, "named:gone"))
    assert owner._restore_agents_jump_anchor() is False
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_pop_anchor_restores_starting_tab_when_every_anchor_is_stale() -> None:
    """A failed back-jump must not leave the tab switched.

    The anchor names a real tab (so the pop loop switches to it first), but
    the row index it recorded no longer exists there. With the stack
    exhausted, the call must restore the tab it started on instead of
    stranding the user on the last anchor's tab.
    """
    owner = AnchorOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    owner._entry_jump_agents_anchor_stack.append(("agent", 99, None, "named:sase"))
    assert owner._pop_agents_jump_anchor() is None
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_pop_anchor_without_tab_token_belongs_to_current_tab() -> None:
    """An anchor saved while the flag was off (no tab token) still validates.

    Comparing a missing token against the current tab's token literally
    always failed once the flag was on, dropping every legacy anchor as
    stale; it should instead be treated as belonging to whatever tab is
    current now.
    """
    owner = AnchorOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    owner._entry_jump_agents_anchor_stack.append(("agent", 0, None))
    anchor = owner._pop_agents_jump_anchor()
    assert anchor == ("agent", 0, None)
    assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_stopped_jump_crosses_tabs() -> None:
    rows = [row("a", status="RUNNING"), row("b", tab="sase", status="PLAN")]
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), view())
    app._ensure_agent_tabs_state()
    app._agents = _scoped_agents_for_owner(app, list(rows))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0

    def _rescope() -> None:
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)

    app._rescope_agents_to_active_tab = _rescope  # type: ignore[method-assign]
    assert app._jump_to_next_stopped_agent() is True
    assert app._active_agent_tab == SASE
    assert app._agents[app.current_idx].identity == rows[1].identity


def test_jump_to_off_tab_timed_candidate_reveals_through_collapsed_clan() -> None:
    """``,j`` reveals an off-tab candidate hidden under a collapsed clan fold.

    ``_off_tab_jump_candidates`` builds candidates from the tab-independent
    query result, which can include a row hidden under a collapsed fold on
    its own tab. The old post-switch plain scan of ``_agents`` never found
    such a row (fold-hidden rows are absent from the filtered roster
    entirely) and wrongly toasted "not found"; the fix reveals through the
    same fold-expanding pipeline as every other cross-tab jump.
    """
    from sase.ace.tui.actions.agents._unread_jump_candidates import (
        TimedAgentJumpCandidate,
    )
    from sase.ace.tui.models._agent_tree import agent_fold_key
    from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
    from sase.ace.tui.models.fold_state import FoldStateManager

    from ._member_jump_navigation_helpers import make_clan

    projected, container = make_clan(2)
    container.agent_tab = "sase"
    member = container.runtime_children[1]
    member.status = "DONE"

    class _Harness(UnreadJumpApp):
        def _rescope_agents_to_active_tab(self) -> None:
            folded, _ = filter_agents_by_fold_state(
                self._agents_with_children, self._fold_manager
            )
            self._agents = _scoped_agents_for_owner(self, folded)
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            folded, _ = filter_agents_by_fold_state(
                self._agents_with_children, self._fold_manager
            )
            self._agents = _scoped_agents_for_owner(self, folded)
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

    app = _Harness(projected, with_panels=True)
    app._fold_manager = FoldStateManager()
    app._agents_with_children = list(projected)
    app._agents_query_result = list(projected)
    app._ensure_agent_tabs_state()
    app._agent_tab_index = build_agent_tab_index(list(projected), view())
    app._unread_completed_agent_ids = {member.identity}

    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)

    app._refilter_agents()
    assert app._agents == []

    sase_key = app._agent_tab_index.key_for(member)
    candidate = TimedAgentJumpCandidate(
        identity=member.identity,
        panel_key=None,
        jump_time=None,
        visible_idx=None,
        tab_key=sase_key,
    )

    def _predicate(agent: Agent) -> bool:
        return agent.identity in app._unread_completed_agent_ids

    assert app._jump_to_off_tab_timed_candidate(
        candidate, predicate=_predicate, after_select=None
    )
    assert app._active_agent_tab == sase_key
    assert app._agents[app.current_idx].identity == member.identity


def test_jump_to_off_tab_timed_candidate_rolls_back_anchor_and_tab_on_mismatch() -> (
    None
):
    """A stale off-tab candidate rolls back both the anchor and the tab.

    The saved back-anchor and the tab switch used to survive a failed
    reveal, so the next ``,j`` picked the same stuck candidate again.
    """
    from sase.ace.tui.actions.agents._unread_jump_candidates import (
        TimedAgentJumpCandidate,
    )

    rows = [row("a", status="RUNNING"), row("b", tab="sase", status="DONE")]
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), view())
    app._ensure_agent_tabs_state()
    app._agents = _scoped_agents_for_owner(app, list(rows))
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app.current_idx = 0

    def _rescope() -> None:
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)

    app._rescope_agents_to_active_tab = _rescope  # type: ignore[method-assign]

    candidate = TimedAgentJumpCandidate(
        identity=rows[1].identity,
        panel_key=None,
        jump_time=None,
        visible_idx=None,
        tab_key=SASE,
    )
    result = app._jump_to_off_tab_timed_candidate(
        candidate, predicate=lambda _agent: False, after_select=None
    )
    assert result is False
    assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY
    assert app._entry_jump_agents_anchor_stack == []


def test_omission_keeps_off_tab_rows() -> None:
    owner = two_tab_owner()
    on_tab = owner._agents_with_children[0].identity
    off_tab = owner._agents_with_children[1].identity
    rows = [
        finder_row(on_tab, rendered=True),
        finder_row(off_tab, tab_label="sase"),
    ]
    kept, index, _chains = apply_snapshot_omission(list(rows), set(), {on_tab}, set())
    assert {row.identity for row in kept} == {on_tab, off_tab}
    assert index[off_tab] == 1


def test_node_finder_off_tab_chip_survives_other_hidden_reasons() -> None:
    """An off-tab row keeps its chip even when it is also query-hidden.

    ``build_snapshot_rows`` used to add the off-tab chip only when
    ``reason_mask == 0``, so an off-tab row that was also folded or
    query-hidden got no chip and looked unreachable in the Node Finder.
    """
    from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
    from sase.ace.tui.actions.agents._node_finder_snapshot import (
        build_node_finder_snapshot,
    )
    from sase.ace.tui.models.node_finder import NodeFinderReason, NodeFinderRole

    class _Harness(cross_tab_harness_class(), EntryJumpModeMixin):
        pass

    rows = [row("a"), row("b", tab="sase")]
    app = prepare_cross_tab_app(rows, harness_cls=_Harness)
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    with override_flags(agents_unified_query=False):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        # A search query that only "a" matches gives "b" a QUERY hidden
        # reason on top of already being off-tab.
        app._agent_search_query = "agent-a"

        snap = build_node_finder_snapshot(app)
        finder = next(
            finder
            for finder in snap.rows
            if finder.role is NodeFinderRole.NODE
            and finder.identity == rows[1].identity
        )
        assert NodeFinderReason.QUERY in finder.reasons
        assert finder.tab_label == "sase"
