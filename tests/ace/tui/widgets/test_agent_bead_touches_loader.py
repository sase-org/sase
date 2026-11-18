"""Loader tests for agent bead touches.

Split from ``test_agent_bead_touches``; shared builders live in
``_agent_bead_touches_helpers`` and the original module re-exports these
tests so its import path keeps working. Queries run against real index
and views files through the Rust member query with a counting wrapper,
so these tests prove the loader only asks for the context's rows and
caches the bounded answers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.ace.tui._bead_touches_loader as bead_touches
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.ace.tui._bead_touches_loader import (
    MAX_KEPT_TOUCHES,
    load_bead_touches_for_agent_context,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

__all__ = [
    "test_agent_session_loader_attributes_touches_with_role_labels",
    "test_loader_caches_results_per_agent",
    "test_loader_caps_at_max_kept_touches",
    "test_loader_filters_to_agent_by_local_and_globalized_name",
    "test_loader_respects_limit",
    "test_loader_returns_empty_when_project_unresolvable",
    "test_loader_returns_empty_when_query_fails",
    "test_loader_throttles_reread_then_refreshes_on_change",
    "test_single_member_agent_session_takes_per_agent_path",
]


class _StubSnapshot:
    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        return AgentIdentitySnapshot(AgentOwnerIdentity("owner", "machine"))


def _write_index(index_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Write a schema-4 touch index with one ``updated`` row per triple."""
    doc = {
        "schema_version": 4,
        "generation": "gen-1",
        "streams": {"s-1": [1, 100]},
        "touches": [
            {
                "actor": actor,
                "bead_id": bead_id,
                "title": f"Title {bead_id}",
                "issue_type": "task",
                "status": "open",
                "verbs": {"updated": 1},
                "first_at": last_at,
                "last_at": last_at,
                "current_note_count": 0,
                "creation_reason_truncated": False,
                "stream_id": "s-1",
            }
            for actor, bead_id, last_at in rows
        ],
    }
    index_path.write_text(json.dumps(doc), encoding="utf-8")


def _write_views(views_path: Path, rows: list[tuple[str, str]]) -> None:
    """Write view events as ``(agent_name, bead_id)`` pairs."""
    with views_path.open("w", encoding="utf-8") as handle:
        for number, (agent_name, bead_id) in enumerate(rows):
            json.dump(
                {
                    "schema_version": 1,
                    "id": f"view-{number}",
                    "timestamp": "2026-09-20T16:00:00Z",
                    "project": "test-proj",
                    "cwd": "/tmp/test",
                    "bead_id": bead_id,
                    "agent_name": agent_name,
                },
                handle,
            )
            handle.write("\n")


@pytest.fixture
def _loader_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Stub project, index/views paths, identity, and caches for loader tests."""
    index_path = tmp_path / "agent_bead_touches.json"
    views_path = tmp_path / "bead_views.jsonl"
    _write_index(index_path, [])
    monkeypatch.setattr(
        bead_touches, "_project_name_for_agent", lambda agent: "test-proj"
    )
    monkeypatch.setattr(bead_touches, "touch_index_path", lambda project: index_path)
    monkeypatch.setattr(bead_touches, "bead_views_log_path", lambda project: views_path)
    monkeypatch.setattr(bead_touches, "AgentIdentitySnapshot", _StubSnapshot)
    monkeypatch.setattr(bead_touches, "_bead_touches_cache", BoundedLRUCache(128))
    monkeypatch.setattr(
        bead_touches, "_bead_touches_context_cache", BoundedLRUCache(128)
    )
    counts = {"index": 0, "views": 0}
    real_index = bead_touches.query_touch_index_members
    real_views = bead_touches.query_bead_view_members

    def _counted_index(
        path: object, members: object, identity: object = None
    ) -> object:
        counts["index"] += 1
        return real_index(path, members, identity)  # type: ignore[arg-type]

    def _counted_views(
        path: object, members: object, identity: object = None
    ) -> object:
        counts["views"] += 1
        return real_views(path, members, identity)  # type: ignore[arg-type]

    monkeypatch.setattr(bead_touches, "query_touch_index_members", _counted_index)
    monkeypatch.setattr(bead_touches, "query_bead_view_members", _counted_views)
    return {"index_path": index_path, "views_path": views_path, "counts": counts}


def _counts(env: dict[str, object]) -> dict[str, int]:
    counts = env["counts"]
    assert isinstance(counts, dict)
    return counts  # type: ignore[return-value]


def test_loader_filters_to_agent_by_local_and_globalized_name(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(
        index_path,
        [
            ("alpha", "sase-1", "2026-09-20T16:00:00Z"),
            ("owner.machine.alpha", "sase-2", "2026-09-20T17:00:00Z"),
            ("beta", "sase-3", "2026-09-20T18:00:00Z"),
            ("stranger", "sase-4", "2026-09-20T19:00:00Z"),
            ("", "sase-5", "2026-09-20T20:00:00Z"),
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-2", "sase-1"]
    assert all(event.agent_label is None for event in events)
    assert _counts(_loader_env) == {"index": 1, "views": 1}


def test_loader_returns_empty_when_project_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    monkeypatch.setattr(bead_touches, "_project_name_for_agent", lambda agent: None)

    assert load_bead_touches_for_agent_context(make_agent()) == ()
    assert _counts(_loader_env) == {"index": 0, "views": 0}


def test_loader_returns_empty_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    def _boom(path: object, members: object, identity: object = None) -> object:
        raise ImportError("no extension")

    monkeypatch.setattr(bead_touches, "query_touch_index_members", _boom)

    assert load_bead_touches_for_agent_context(make_agent(agent_name="alpha")) == ()


def test_loader_caches_results_per_agent(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(index_path, [("alpha", "sase-1", "2026-09-20T16:00:00Z")])

    load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )
    load_bead_touches_for_agent_context(
        make_agent(agent_name="beta", cl_name="beta_cl")
    )

    # Targeted queries ask per agent: no shared full snapshot remains.
    assert _counts(_loader_env) == {"index": 2, "views": 2}

    load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )
    assert _counts(_loader_env) == {"index": 2, "views": 2}


def test_loader_throttles_reread_then_refreshes_on_change(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(index_path, [("alpha", "sase-1", "2026-09-20T16:00:00Z")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    load_bead_touches_for_agent_context(agent)
    assert _counts(_loader_env) == {"index": 1, "views": 1}

    # Same identity within the throttle window: no re-query.
    load_bead_touches_for_agent_context(agent)
    assert _counts(_loader_env) == {"index": 1, "views": 1}

    # Changed file after the throttle window: re-query.
    _write_index(
        index_path,
        [
            ("alpha", "sase-1", "2026-09-20T16:00:00Z"),
            ("alpha", "sase-2", "2026-09-20T17:00:00Z"),
        ],
    )
    key = bead_touches._cache_key("test-proj", agent)
    bead_touches._bead_touches_cache[key].last_read_monotonic -= 10.0
    events = load_bead_touches_for_agent_context(agent)
    assert _counts(_loader_env) == {"index": 2, "views": 2}
    assert [event.touch.bead_id for event in events] == ["sase-2", "sase-1"]


def test_loader_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(
        index_path,
        [("alpha", f"sase-{n}", f"2026-09-20T16:{n:02d}:00Z") for n in range(10)],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent, limit=3)

    assert len(events) == 3
    assert events[0].touch.bead_id == "sase-9"


def test_loader_caps_at_max_kept_touches(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(
        index_path,
        [
            ("alpha", f"sase-{n}", "2026-09-20T16:00:00Z")
            for n in range(MAX_KEPT_TOUCHES + 5)
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    assert len(load_bead_touches_for_agent_context(agent)) == MAX_KEPT_TOUCHES


def test_agent_session_loader_attributes_touches_with_role_labels(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(
        index_path,
        [
            ("alpha", "sase-1", "2026-09-20T16:00:00Z"),
            ("owner.machine.beta", "sase-2", "2026-09-20T17:00:00Z"),
            ("stranger", "sase-3", "2026-09-20T18:00:00Z"),
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
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)
    _write_index(index_path, [("alpha", "sase-1", "2026-09-20T16:00:00Z")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-1"]
    assert events[0].agent_label is None
