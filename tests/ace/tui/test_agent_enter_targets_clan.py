"""Clan-container Enter-on-agent delegation to a lone stopped member."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._agent_enter_models import CLAN_EMPTY_MESSAGE
from sase.ace.tui.models.agent import Agent

from ._agent_enter_targets_helpers import (
    _EnterApp,
    _agent_session,
    _gate_row,
    _matching_action_data,
    _notification,
    _resolve,
    _sources,
)
from ._agent_unread_helpers import make_agent

_CLAN = "testclan"
_GEN = "20260918010101"


def _clan_member(
    name: str,
    status: str = "DONE",
    *,
    suffix: str,
) -> Agent:
    return replace(
        make_agent(name=name, status=status, raw_suffix=suffix),
        agent_clan=_CLAN,
        agent_clan_generation=_GEN,
    )


def _clan_container(members: list[Agent]) -> Agent:
    container = replace(
        make_agent(name=_CLAN, raw_suffix=_GEN),
        is_clan_container=True,
        agent_clan=_CLAN,
        agent_clan_generation=_GEN,
    )
    container.runtime_children = list(members)
    return container


def test_clan_session_plus_done_members_delegates_to_session() -> None:
    gate = _gate_row("010101", notification_id="n-sudo")
    session = _agent_session(members=[gate])
    session.agent_clan = _CLAN
    session.agent_clan_generation = _GEN
    session.status_bucket = "Stopped"
    done_a = _clan_member("done-a", "DONE", suffix="20260918020202")
    done_b = _clan_member("done-b", "DONE", suffix="20260918030303")
    clan = _clan_container([session, done_a, done_b])
    notifications = [
        _notification("n-sudo", "SudoRequest", action_data=_matching_action_data(gate))
    ]

    expected = _resolve(session, notifications)
    resolution = _resolve(clan, notifications)

    assert resolution.targets == expected.targets
    assert resolution.scope_title == expected.scope_title
    assert resolution.subject_identity == session.identity
    assert resolution.empty_message is None


def test_clan_lone_question_member_yields_question_marker() -> None:
    member = _clan_member("~", "QUESTION", suffix="20260918020202")
    clan = _clan_container([member])
    resolution = _resolve(clan)

    assert "question_marker" in _sources(resolution)
    assert resolution.scope_title == _resolve(member).scope_title
    assert resolution.subject_identity == member.identity


def test_clan_zero_stopped_members_keeps_empty_message() -> None:
    running = _clan_member("run", "RUNNING", suffix="20260918020202")
    done = _clan_member("done", "DONE", suffix="20260918030303")
    clan = _clan_container([running, done])
    resolution = _resolve(clan)

    assert resolution.targets == ()
    assert resolution.empty_message == CLAN_EMPTY_MESSAGE
    assert resolution.subject_identity is None


def test_clan_two_stopped_members_keeps_empty_message() -> None:
    first = _clan_member("~", "QUESTION", suffix="20260918020202")
    second = _clan_member("plan", "PLAN", suffix="20260918030303")
    clan = _clan_container([first, second])
    resolution = _resolve(clan)

    assert resolution.targets == ()
    assert resolution.empty_message == CLAN_EMPTY_MESSAGE
    assert resolution.subject_identity is None


def test_clan_duplicate_identity_still_delegates() -> None:
    member = _clan_member("~", "QUESTION", suffix="20260918020202")
    clan = _clan_container([member, member])
    resolution = _resolve(clan)

    assert "question_marker" in _sources(resolution)
    assert resolution.subject_identity == member.identity


def test_clan_lone_stopped_member_with_no_targets_keeps_empty_message() -> None:
    member = _clan_member("~", "PLAN", suffix="20260918020202")
    clan = _clan_container([member])
    resolution = _resolve(clan)

    assert resolution.targets == ()
    assert resolution.empty_message == CLAN_EMPTY_MESSAGE
    assert resolution.subject_identity is None
    assert _resolve(member).targets == ()


def test_clan_stopped_member_plus_running_sibling_still_delegates() -> None:
    stopped = _clan_member("~", "QUESTION", suffix="20260918020202")
    running = _clan_member("run", "RUNNING", suffix="20260918030303")
    clan = _clan_container([stopped, running])
    resolution = _resolve(clan)

    assert "question_marker" in _sources(resolution)
    assert resolution.subject_identity == stopped.identity


def test_clan_stopped_outsider_is_ignored() -> None:
    stopped = _clan_member("~", "QUESTION", suffix="20260918020202")
    other_clan = replace(
        make_agent(name="other.q", status="QUESTION", raw_suffix="other"),
        agent_clan="otherclan",
        agent_clan_generation=_GEN,
    )
    wrong_generation = replace(
        make_agent(name="old.q", status="QUESTION", raw_suffix="oldq"),
        agent_clan=_CLAN,
        agent_clan_generation="old-generation",
    )
    clan = _clan_container([stopped, other_clan, wrong_generation])
    resolution = _resolve(clan)

    assert "question_marker" in _sources(resolution)
    assert resolution.subject_identity == stopped.identity


def test_clan_dispatch_question_marker_uses_member_identity() -> None:
    member = _clan_member("~", "QUESTION", suffix="20260918020202")
    clan = _clan_container([member])
    app = _EnterApp(agents=[clan, member])
    app._dispatch_agent_enter_resolution(clan, app._agent_enter_resolution(clan))
    assert app.marker_calls == [member]


def test_clan_dispatch_chooser_titles_and_re_resolves_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = _clan_member("worker", "PLAN", suffix="20260918020202")
    notification = _notification(
        "n-plan", "PlanApproval", action_data=_matching_action_data(member)
    )
    clan = _clan_container([member])
    app = _EnterApp(notifications=[notification], agents=[clan, member])
    captured: dict[str, Any] = {}

    def _push_screen(modal: Any, callback: Any) -> None:
        captured["title"] = modal._title_text
        captured["callback"] = callback

    app.push_screen = _push_screen  # type: ignore[method-assign]
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda _app, note: dispatched.append(note.id) or True,
    )

    resolution = app._agent_enter_resolution(clan)
    assert len(resolution.targets) >= 2
    gate = next(target for target in resolution.targets if target.kind == "gate")
    app._dispatch_agent_enter_resolution(clan, resolution)

    assert captured["title"] == f"Act on {resolution.scope_title}"
    assert resolution.scope_title == _resolve(member, [notification]).scope_title
    captured["callback"](gate.key)
    assert dispatched == ["n-plan"]
