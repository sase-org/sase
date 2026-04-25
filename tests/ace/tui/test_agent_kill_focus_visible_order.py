"""Regression tests for `agents_kill_focus_visible_order`.

When the deterministic group-tree ordering puts agents in a different
order than ``_agents``, killing or dismissing the focused row must move
the highlight to the agent visually below the killed one — not to
whichever agent happens to occupy the post-deletion ``_agents`` index
the bare clamp produced.

Mirrors the ``test_agent_jk_navigation`` regression suite for the j/k
fix; both share the same root cause (``_agents`` order != visible order
under the level-3 grouping walk).
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.actions.agents._killing import AgentKillingMixin
from sase.ace.tui.models.agent import Agent, AgentType


class _StubApp(AgentKillingMixin, AgentDismissingMixin):
    """Minimal harness exercising the kill / dismiss focus-restoration path.

    Inherits the real kill / dismiss mixins so the production code paths
    drive the test, and supplies the shared visible-order helpers inline
    (mirrors the ``_StubApp`` in ``test_agent_jk_navigation``).
    """

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._agents_with_children = list(agents)
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._kill_persistence_inflight: set[tuple[AgentType, str, str | None]] = set()
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self.notifications: list[tuple[str, str]] = []
        self.scheduled: list[tuple[object, tuple[object, ...]]] = []
        self.refresh_calls: list[tuple[bool, bool]] = []
        self._refilter_called = False

    # --- AgentsMixinCore-equivalent helpers ---

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def call_later(self, callback: object, *args: object) -> None:
        self.scheduled.append((callback, args))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refresh_calls.append((list_changed, defer_detail))

    def _refresh_notification_count(self) -> None:
        return

    def _schedule_agents_async_refresh(self) -> None:
        return

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        # Mirror what the real refilter pipeline does for tests:
        # remove dismissed agents from `_agents` (the cache they live in
        # is `_agents_with_children`, already pruned by the caller), then
        # re-anchor focus.
        self._refilter_called = True
        self._agents = list(self._agents_with_children)
        self._restore_focus_after_removal(prior_pos)

    # --- Visible-order helpers ---

    def _agents_visible_order(self) -> list[int]:
        from sase.ace.tui.models.agent_groups import build_agent_tree

        tree = build_agent_tree(self._agents, group_fold_level=3)
        return [
            entry.agent_idx
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _capture_focused_visible_pos(self) -> int | None:
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return None
        visible = self._agents_visible_order()
        try:
            return visible.index(self.current_idx)
        except ValueError:
            return None

    def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
        if not self._agents:
            self.current_idx = 0
            return

        if self.current_idx >= len(self._agents):
            self.current_idx = len(self._agents) - 1
        if self.current_idx < 0:
            self.current_idx = 0

        if prior_visible_pos is not None:
            visible = self._agents_visible_order()
            if visible:
                self.current_idx = visible[min(prior_visible_pos, len(visible) - 1)]


def _agent(
    *,
    tag: str = "",
    project: str = "proj",
    cl: str = "demo",
    name: str = "alpha",
    status: str = "RUNNING",
    pid: int | None = 12345,
    raw_suffix: str | None = None,
) -> Agent:
    """Build an Agent with controllable grouping keys.

    Mirrors the helper in ``test_agent_jk_navigation`` so tag-based
    visible-order assertions match the production grouping walk.
    """
    if raw_suffix is None:
        raw_suffix = f"{name}-suffix"
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag or None,
        pid=pid,
        raw_suffix=raw_suffix,
    )


def _scrambled_three() -> list[Agent]:
    """`_agents` order ``[zeta, alpha, beta]``; visible order ``[alpha, beta, zeta]``."""
    return [
        _agent(tag="zeta", name="z1"),
        _agent(tag="alpha", name="a1"),
        _agent(tag="beta", name="b1"),
    ]


# ---- Single kill --------------------------------------------------------


def test_single_kill_at_fold_3_lands_on_visually_next_agent() -> None:
    """Killing the visually-first agent moves focus to the visually-next."""
    agents = _scrambled_three()
    alpha = agents[1]  # zeta=0, alpha=1, beta=2 in `_agents` order
    app = _StubApp(agents, current_idx=1)  # alpha (visually first)

    app._apply_killed_agents_in_memory({alpha.identity})

    # Survivors `_agents` order: [zeta=0, beta=1]; visible order [beta, zeta].
    # Visual position 0 (where alpha was) now points to beta.
    assert [ag.agent_name for ag in app._agents] == ["z1", "b1"]
    assert app.current_idx == 1  # beta in new `_agents`
    assert app._agents[app.current_idx].agent_name == "b1"


def test_single_kill_at_end_of_visible_order_falls_back_to_last() -> None:
    """Killing the visually-last agent moves focus to the new last-visible."""
    agents = _scrambled_three()
    zeta = agents[0]  # visible order: [alpha, beta, zeta]
    app = _StubApp(agents, current_idx=0)  # zeta — visually last

    app._apply_killed_agents_in_memory({zeta.identity})

    # Survivors: [alpha, beta]; visible: [alpha, beta]. zeta was at
    # visible position 2; clamped to last visible row → beta.
    assert [ag.agent_name for ag in app._agents] == ["a1", "b1"]
    assert app._agents[app.current_idx].agent_name == "b1"


def test_workflow_parent_kill_lands_on_unrelated_after_cascade() -> None:
    """Killing a workflow parent removes children and re-anchors visibly."""
    parent = _agent(tag="alpha", name="parent")
    parent.raw_suffix = "ts_parent"
    parent.agent_type = AgentType.WORKFLOW
    unrelated = _agent(tag="zeta", name="unrelated")
    child = _agent(tag="", name="parent.step1")
    child.parent_timestamp = "ts_parent"
    child.parent_workflow = "wf"
    agents = [parent, unrelated, child]
    # Visible order: [parent, child, unrelated] (child inherits parent's
    # alpha grouping; unrelated's zeta sorts after alpha).
    app = _StubApp(agents, current_idx=0)  # parent

    app._apply_killed_agents_in_memory({parent.identity, child.identity})

    # Only unrelated survives; cursor lands on it.
    assert [ag.agent_name for ag in app._agents] == ["unrelated"]
    assert app.current_idx == 0


def test_last_agent_in_panel_killed_falls_back_safely() -> None:
    """Killing the only agent leaves the cursor in a valid state."""
    only_one = _agent(tag="alpha", name="solo")
    app = _StubApp([only_one], current_idx=0)

    app._apply_killed_agents_in_memory({only_one.identity})

    assert app._agents == []
    assert app.current_idx == 0


# ---- Single dismiss -----------------------------------------------------


def test_single_dismiss_at_fold_3_lands_on_visually_next_agent() -> None:
    """Same scrambled fixture, but exercising the dismiss pipeline."""
    agents = [
        _agent(tag="zeta", name="z1", status="DONE", pid=None),
        _agent(tag="alpha", name="a1", status="DONE", pid=None),
        _agent(tag="beta", name="b1", status="DONE", pid=None),
    ]
    alpha = agents[1]
    app = _StubApp(agents, current_idx=1)  # alpha — visually first

    app._apply_dismissal_in_memory([alpha])

    # Survivors `_agents` order: [zeta=0, beta=1]; visible [beta, zeta].
    assert [ag.agent_name for ag in app._agents] == ["z1", "b1"]
    assert app._agents[app.current_idx].agent_name == "b1"


# ---- Bulk kill ----------------------------------------------------------


def test_bulk_kill_lands_on_first_surviving_visible_at_or_below_anchor() -> None:
    """Bulk-killing alpha + zeta from focus on alpha lands on beta."""
    agents = _scrambled_three()
    zeta, alpha = agents[0], agents[1]
    app = _StubApp(agents, current_idx=1)  # alpha

    app._apply_killed_agents_in_memory({alpha.identity, zeta.identity})

    assert [ag.agent_name for ag in app._agents] == ["b1"]
    assert app.current_idx == 0


# ---- Banner focus -------------------------------------------------------


def test_banner_focus_kill_does_not_anchor_to_visible_position() -> None:
    """When focus is out-of-range, prior_pos is None — clamp fallback runs.

    This guards the no-anchor path used by the group-banner bulk kill flow
    at fold level < 3. We capture by hand to assert the contract that
    ``_capture_focused_visible_pos`` returns ``None`` when selection is
    not on a real agent row.
    """
    agents = _scrambled_three()
    app = _StubApp(agents, current_idx=99)  # out-of-range — no anchor

    assert app._capture_focused_visible_pos() is None
    # And `_restore_focus_after_removal(None)` runs the safe fallback.
    app._agents = list(agents)
    app._restore_focus_after_removal(None)
    # current_idx clamped into bounds.
    assert 0 <= app.current_idx < len(app._agents)
