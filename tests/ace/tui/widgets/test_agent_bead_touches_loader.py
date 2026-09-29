"""Loader tests for agent bead touches.

Split from ``test_agent_bead_touches``; shared builders live in
``_agent_bead_touches_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest

import sase.ace.tui._bead_touches_loader as bead_touches
from sase.ace.tui._bead_touches_loader import (
    MAX_KEPT_TOUCHES,
    load_bead_touches_for_agent_context,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.bead_touch_index_facade import BeadTouch, BeadTouchQuery
from tests.ace.tui.widgets._agent_bead_touches_helpers import make_bead_touch
from tests.ace.tui.widgets._agent_display_helpers import make_agent

__all__ = [
    "test_agent_session_loader_attributes_touches_with_role_labels",
    "test_loader_caches_snapshot_across_agents",
    "test_loader_caps_at_max_kept_touches",
    "test_loader_filters_to_agent_by_local_and_globalized_name",
    "test_loader_respects_limit",
    "test_loader_returns_empty_when_project_unresolvable",
    "test_loader_returns_empty_when_query_fails",
    "test_loader_throttles_reread_then_refreshes_on_change",
    "test_single_member_agent_session_takes_per_agent_path",
]

_FAKE_GLOBALIZED = {
    "alpha": "owner.machine.alpha",
    "beta": "owner.machine.beta",
}


def _fake_globalize(name: str, identity: object = None) -> str:
    return _FAKE_GLOBALIZED.get(name, name)


class _StubSnapshot:
    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        return AgentIdentitySnapshot.unconfigured()


@pytest.fixture
def _loader_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Stub project, index path, identity, and caches for loader tests."""
    index_path = tmp_path / "agent_bead_touches.json"
    index_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        bead_touches, "_project_name_for_agent", lambda agent: "test-proj"
    )
    monkeypatch.setattr(bead_touches, "touch_index_path", lambda project: index_path)
    monkeypatch.setattr(bead_touches, "AgentIdentitySnapshot", _StubSnapshot)
    monkeypatch.setattr(bead_touches, "globalize_owned_agent_name", _fake_globalize)
    monkeypatch.setattr(bead_touches, "_bead_touches_cache", {})
    monkeypatch.setattr(bead_touches, "_bead_touches_context_cache", {})
    monkeypatch.setattr(bead_touches, "_bead_touches_snapshot_cache", OrderedDict())
    return {"index_path": index_path}


def _stub_query(
    monkeypatch: pytest.MonkeyPatch, touches: list[BeadTouch]
) -> list[object]:
    calls: list[object] = []

    def _query(index_path: object, actors: object = None) -> BeadTouchQuery:
        calls.append(index_path)
        return BeadTouchQuery(schema_version=1, generation="g", touches=tuple(touches))

    monkeypatch.setattr(bead_touches, "query_touch_index", _query)
    return calls


def test_loader_filters_to_agent_by_local_and_globalized_name(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            make_bead_touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z"),
            make_bead_touch(
                "owner.machine.alpha", "sase-2", last_at="2026-09-20T17:00:00Z"
            ),
            make_bead_touch("beta", "sase-3", last_at="2026-09-20T18:00:00Z"),
            make_bead_touch("stranger", "sase-4", last_at="2026-09-20T19:00:00Z"),
            make_bead_touch("", "sase-5", last_at="2026-09-20T20:00:00Z"),
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-2", "sase-1"]
    assert all(event.agent_label is None for event in events)


def test_loader_returns_empty_when_project_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [make_bead_touch("alpha", "sase-1")])
    monkeypatch.setattr(bead_touches, "_project_name_for_agent", lambda agent: None)

    assert load_bead_touches_for_agent_context(make_agent()) == ()
    assert calls == []


def test_loader_returns_empty_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    def _boom(index_path: object, actors: object = None) -> BeadTouchQuery:
        raise ImportError("no extension")

    monkeypatch.setattr(bead_touches, "query_touch_index", _boom)

    assert load_bead_touches_for_agent_context(make_agent(agent_name="alpha")) == ()


def test_loader_caches_snapshot_across_agents(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [make_bead_touch("alpha", "sase-1")])

    load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )
    load_bead_touches_for_agent_context(
        make_agent(agent_name="beta", cl_name="beta_cl")
    )

    assert len(calls) == 1


def test_loader_throttles_reread_then_refreshes_on_change(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [make_bead_touch("alpha", "sase-1")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)

    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 1

    # Same stat within the throttle window: no re-query.
    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 1

    # Changed file after the throttle window: re-query.
    index_path.write_text("{}\nmore-bytes-here\n", encoding="utf-8")
    key = bead_touches._cache_key("test-proj", agent)
    bead_touches._bead_touches_cache[key].last_read_monotonic -= 10.0
    snapshot = bead_touches._bead_touches_snapshot_cache["test-proj"]
    snapshot.last_read_monotonic -= 10.0
    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 2


def test_loader_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            make_bead_touch("alpha", f"sase-{n}", last_at=f"2026-09-20T16:{n:02d}:00Z")
            for n in range(10)
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent, limit=3)

    assert len(events) == 3
    assert events[0].touch.bead_id == "sase-9"


def test_loader_caps_at_max_kept_touches(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            make_bead_touch("alpha", f"sase-{n}", last_at="2026-09-20T16:00:00Z")
            for n in range(MAX_KEPT_TOUCHES + 5)
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    assert len(load_bead_touches_for_agent_context(agent)) == MAX_KEPT_TOUCHES


def test_agent_session_loader_attributes_touches_with_role_labels(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            make_bead_touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z"),
            make_bead_touch(
                "owner.machine.beta", "sase-2", last_at="2026-09-20T17:00:00Z"
            ),
            make_bead_touch("stranger", "sase-3", last_at="2026-09-20T18:00:00Z"),
        ],
    )
    member = make_agent(agent_name="beta", cl_name="beta_cl", role_suffix="--code")
    root = make_agent(
        agent_name="alpha",
        cl_name="alpha_cl",
        role_suffix="--plan",
        followup_agents=[member],
    )

    events = load_bead_touches_for_agent_context(root)

    assert [(event.touch.bead_id, event.agent_label) for event in events] == [
        ("sase-2", "coder"),
        ("sase-1", "plan"),
    ]


def test_single_member_agent_session_takes_per_agent_path(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(monkeypatch, [make_bead_touch("alpha", "sase-1")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-1"]
    assert events[0].agent_label is None
