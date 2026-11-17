"""Agent Hijack pending-latch panel and proc completions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.actions.agents._hijack_decision import (
    hijack_ingress_available_for_footer,
    kill_modal_hijack_available,
    row_has_pending_latch,
)
from sase.ace.tui.actions.agents._hijack_pending_panel import (
    _CANCEL_RESULT,
    _FORCE_RESULT,
    _FORCE_WARNING,
    _pending_hijack_choices,
    _pending_latch_force_eligible,
    apply_hijack_proc_completion,
)
from sase.ace.tui.models.agent import Agent
from tests.ace.tui._agent_hijack_action_helpers import (
    make_hijack_agent,
    make_hijack_view,
    make_latched_record,
)


def test_footer_and_kill_modal_offer_hijack_for_pending_latch() -> None:
    agent = make_hijack_agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = make_latched_record()

    class App(AgentHijackActionMixin):
        pass

    app = App()
    app._store_hijack_decision(
        agent,
        make_hijack_view(
            agent,
            mode="refused",
            code="finalizing_turn",
            message="finalizing turns cannot be hijacked yet",
        ),
    )
    assert row_has_pending_latch(agent) is True
    assert hijack_ingress_available_for_footer(app, agent) is True
    assert kill_modal_hijack_available(app, agent) is True


def test_pending_row_opens_cancel_force_panel(monkeypatch: Any) -> None:
    agent = make_hijack_agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = make_latched_record()
    opened: list[Agent] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _get_selected_agent(self) -> Agent:
            return agent

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_pending_panel.open_pending_hijack_panel",
        lambda _app, row: opened.append(row) or True,
    )
    app._store_hijack_decision(
        agent,
        make_hijack_view(agent, mode="refused", code="finalizing_turn"),
    )

    assert app._start_hijack_agent() is True
    assert opened == [agent]


def test_pending_ingress_skips_when_selection_moves(monkeypatch: Any) -> None:
    pending = make_hijack_agent()
    pending.hijack_overlay = "pending"
    pending.hijack_record = make_latched_record()
    other = make_hijack_agent()
    other.agent_name = "other.1"
    other.raw_suffix = "20261103100001"
    opened: list[Agent] = []
    selected: list[Agent] = [pending]

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _get_selected_agent(self) -> Agent:
            current = selected[0]
            selected[0] = other
            return current

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_pending_panel.open_pending_hijack_panel",
        lambda _app, row: opened.append(row) or True,
    )
    assert app._start_hijack_agent() is False
    assert opened == []
    selected[0] = pending
    assert app._start_hijack_agent(pending) is True
    assert opened == [pending]


def test_latched_occupying_completion_stays_pending(monkeypatch: Any) -> None:
    agent = make_hijack_agent()
    callbacks: list[Any] = []
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: callbacks.append(kwargs["on_complete"]) or True,
    )
    app._store_hijack_decision(agent, make_hijack_view(agent, mode="latched"))

    assert app._start_hijack_agent(agent)
    assert agent.hijack_overlay == "pending"

    callbacks[0](
        SimpleNamespace(
            payload={
                "status": "latched",
                "hijack_id": "h-latched",
                "record": make_latched_record(),
            },
            message="",
            success=True,
        )
    )

    assert agent.hijack_overlay == "pending"
    assert agent.hijack_stop_failed is False
    assert agent.hijack_id == "h-latched"
    assert notifications == [
        ("Hijack latched; waiting for a safe boundary", "information")
    ]


def test_refused_force_keeps_pending_overlay() -> None:
    agent = make_hijack_agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = make_latched_record()
    notifications: list[tuple[str, str]] = []

    class App:
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    apply_hijack_proc_completion(
        App(),
        agent,
        agent,
        SimpleNamespace(
            payload={
                "status": "refused",
                "code": "force_too_early",
                "severity": "warning",
            },
            message="the pending latch is younger than 120 seconds",
            success=False,
        ),
    )

    assert agent.hijack_overlay == "pending"
    assert agent.hijack_stop_failed is False
    assert notifications == [
        ("the pending latch is younger than 120 seconds", "warning")
    ]


def test_moot_completion_toasts_exact_phrase() -> None:
    agent = make_hijack_agent()
    agent.hijack_overlay = "pending"
    notifications: list[tuple[str, str]] = []

    class App:
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    apply_hijack_proc_completion(
        App(),
        agent,
        agent,
        SimpleNamespace(
            payload={"status": "finished_first"},
            message="some other wording",
            success=True,
        ),
    )

    assert agent.hijack_overlay is None
    assert notifications == [
        ("finished before the hijack; nothing was held", "information")
    ]


def test_delayed_completion_applies_to_current_identity_row() -> None:
    original = make_hijack_agent()
    original.hijack_overlay = "pending"
    original.hijack_record = make_latched_record()
    refreshed = make_hijack_agent()
    refreshed.hijack_overlay = "pending"
    refreshed.hijack_record = make_latched_record()
    notifications: list[str] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [refreshed]
        _agents = [refreshed]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del severity
            notifications.append(message)

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    apply_hijack_proc_completion(
        app,
        app._hijack_row_for_identity(original.identity) or original,
        app._hijack_row_for_identity(original.identity) or original,
        SimpleNamespace(
            payload={"status": "cancelled"},
            message="latch cancelled",
            success=True,
        ),
    )

    assert refreshed.hijack_overlay is None
    assert original.hijack_overlay == "pending"
    assert notifications == ["latch cancelled"]


def test_pending_force_choice_appears_only_after_120s(monkeypatch: Any) -> None:
    record = make_latched_record()
    monkeypatch.setattr(
        "sase.agent.hijack.core.hijack_latch_force_eligibility",
        lambda _record, now: {
            "eligible": now >= 1_000_120,
            "age_seconds": now - 1_000_000,
            "threshold_seconds": 120,
        },
    )
    assert _pending_latch_force_eligible(record, now=1_000_119) is False
    young = _pending_hijack_choices(record, now=1_000_119)
    assert [choice.result for choice in young] == [_CANCEL_RESULT]
    assert _pending_latch_force_eligible(record, now=1_000_120) is True
    aged = _pending_hijack_choices(record, now=1_000_120)
    assert [choice.result for choice in aged] == [_CANCEL_RESULT, _FORCE_RESULT]
    assert aged[1].detail == _FORCE_WARNING
    assert aged[1].hotkey == "n"


def test_pending_cancel_submits_durable_cancel(monkeypatch: Any) -> None:
    agent = make_hijack_agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = make_latched_record()
    submitted: list[dict[str, Any]] = []
    pushed: list[Any] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def push_screen(self, modal: Any, callback: Any) -> None:
            pushed.append(modal)
            callback(_CANCEL_RESULT)

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: submitted.append(kwargs) or True,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.core.hijack_latch_force_eligibility",
        lambda *_args, **_kwargs: {"eligible": False},
    )

    from sase.ace.tui.actions.agents._hijack_pending_panel import (
        open_pending_hijack_panel,
    )

    assert open_pending_hijack_panel(app, agent) is True
    assert submitted[0]["action"] == "cancel"
    assert submitted[0]["hijack_id"] == "h-latched"
    assert submitted[0]["target_key"] == "proj:session-1"
    assert submitted[0]["name"] == "sase-demo.1"
    assert pushed[0]._title_text.startswith("⏏ Pending hijack")


def test_help_lists_pending_cancel_and_force() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_mode_sections import mode_sections

    boxes = dict(mode_sections(load_keymap_registry({})))
    leader = next(
        rows for title, rows in boxes.items() if title.startswith("Leader Mode")
    )
    descriptions = [description for _key, description in leader]
    assert "Hijack, cancel, or force latch" in descriptions
    assert len("Hijack, cancel, or force latch") <= 32
