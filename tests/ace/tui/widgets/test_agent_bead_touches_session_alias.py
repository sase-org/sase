"""Session-container alias tests for the bead-touch loader.

Bead mutations record ``$SASE_AGENT_NAME`` as the event actor, which holds
the session container name for pre-rename roots and in-process continuation
turns. The loader accepts that container name as an actor alias wherever
the whole session is in view. Fixture and stub patterns mirror
``test_agent_bead_touches.py`` without importing its private helpers.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rich.text import Text

import sase.ace.tui._bead_touches_loader as bead_touches
from sase.ace.tui._bead_touches_loader import load_bead_touches_for_agent_context
from sase.ace.tui._bead_touches_merge import (
    merge_bead_touch_entries,
    own_bead_ids_for_agent,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    append_agent_bead_touch_rows,
)
from sase.bead.bead_views import BEAD_VIEW_LOG_SCHEMA_VERSION, BeadViewEvent
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.bead_touch_index_facade import (
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
    BeadTouchQuery,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _touch(
    actor: str,
    bead_id: str,
    *,
    verbs: dict[str, int] | None = None,
    last_at: str = "",
    note_preview: BeadNotePreview | None = None,
    close: BeadTouchClose | None = None,
) -> BeadTouch:
    return BeadTouch(
        actor=actor,
        bead_id=bead_id,
        verbs=dict(verbs or {}),
        last_at=last_at,
        note_preview=note_preview,
        close=close,
    )


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
    monkeypatch.setattr(bead_touches, "_bead_views_snapshot_cache", OrderedDict())
    return {"index_path": index_path}


def _stub_query(monkeypatch: pytest.MonkeyPatch, touches: list[BeadTouch]) -> None:
    def _query(index_path: object, actors: object = None) -> BeadTouchQuery:
        return BeadTouchQuery(schema_version=1, generation="g", touches=tuple(touches))

    monkeypatch.setattr(bead_touches, "query_touch_index", _query)


def _stub_views(monkeypatch: pytest.MonkeyPatch, events: list[BeadViewEvent]) -> None:
    def _read(
        *, project: object = None, log_path: object = None
    ) -> tuple[BeadViewEvent, ...]:
        return tuple(events)

    monkeypatch.setattr(bead_touches, "read_bead_view_events", _read)


def _view(agent_name: str, bead_id: str) -> BeadViewEvent:
    return BeadViewEvent(
        schema_version=BEAD_VIEW_LOG_SCHEMA_VERSION,
        id=f"{agent_name}:{bead_id}",
        timestamp="2026-09-20T16:00:00Z",
        project="test-proj",
        cwd="/tmp/test",
        bead_id=bead_id,
        agent_name=agent_name,
    )


_BASE_TIME = datetime(2024, 1, 1, 14, 0, 0)


def _member(
    tmp_path: Path,
    token: str,
    *,
    agent_name: str,
    role_suffix: str,
    agent_session_role: str,
    plan_chain_root: bool = False,
) -> object:
    """Build one session member with a distinct cache key and artifacts dir."""
    artifacts_dir = tmp_path / f"{token}-artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    offset = abs(hash(token)) % 3600
    return make_agent(
        cl_name="alias_cl",
        raw_suffix=token,
        start_time=_BASE_TIME + timedelta(seconds=offset),
        artifacts_dir=str(artifacts_dir),
        agent_name=agent_name,
        role_suffix=role_suffix,
        agent_session="alpha",
        agent_session_role=agent_session_role,
        plan_chain_root=plan_chain_root,
    )


def _session_root(tmp_path: Path, **overrides: object) -> object:
    """Build the ``alpha`` session root with ``--gate`` and ``--code`` turns."""
    gate = _member(
        tmp_path,
        "gate",
        agent_name="alpha--gate",
        role_suffix="--gate",
        agent_session_role="gate",
    )
    code = _member(
        tmp_path,
        "code",
        agent_name="alpha--code",
        role_suffix="--code",
        agent_session_role="code",
    )
    params: dict[str, object] = {
        "agent_name": "alpha--plan",
        "role_suffix": "--plan",
        "agent_session": "alpha",
        "agent_session_role": "root",
        "plan_chain_root": True,
        "followup_agents": [gate, code],
    }
    params.update(overrides)
    root_dir = tmp_path / "root-artifacts"
    root_dir.mkdir(exist_ok=True)
    return make_agent(
        cl_name="alias_cl",
        raw_suffix="root",
        start_time=_BASE_TIME,
        artifacts_dir=str(root_dir),
        **params,  # type: ignore[arg-type]
    )


def _by_id(events: tuple[object, ...]) -> dict[str, object]:
    return {event.touch.bead_id: event for event in events}  # type: ignore[union-attr]


def test_session_container_row_credits_container_actor(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(
        monkeypatch,
        [
            _touch(
                "alpha",
                "sase-1",
                verbs={"closed": 1, "noted": 1},
                last_at="2026-09-20T16:00:00Z",
                close=BeadTouchClose(
                    closed_at="2026-09-20T16:00:00Z",
                    resolution="done",
                    standing=True,
                ),
            ),
            _touch(
                "alpha--code",
                "sase-2",
                verbs={"noted": 1},
                last_at="2026-09-20T17:00:00Z",
            ),
            _touch("stranger", "sase-3", last_at="2026-09-20T18:00:00Z"),
        ],
    )
    root = _session_root(tmp_path)

    events = load_bead_touches_for_agent_context(root)  # type: ignore[arg-type]

    found = _by_id(events)
    assert set(found) == {"sase-1", "sase-2"}
    assert found["sase-1"].agent_label is None  # type: ignore[union-attr]
    assert found["sase-2"].agent_label == "coder"  # type: ignore[union-attr]


def test_globalized_container_spelling_matches(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(
        monkeypatch,
        [_touch("owner.machine.alpha", "sase-1", last_at="2026-09-20T16:00:00Z")],
    )
    root = _session_root(tmp_path)

    events = load_bead_touches_for_agent_context(root)  # type: ignore[arg-type]

    assert [event.touch.bead_id for event in events] == ["sase-1"]  # type: ignore[union-attr]
    assert events[0].agent_label is None  # type: ignore[union-attr]


def test_members_win_over_alias_for_never_renamed_root(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(
        monkeypatch,
        [_touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z")],
    )
    code = _member(
        tmp_path,
        "code",
        agent_name="alpha--code",
        role_suffix="--code",
        agent_session_role="code",
    )
    root_dir = tmp_path / "root-artifacts"
    root_dir.mkdir(exist_ok=True)
    root = make_agent(
        cl_name="alias_cl",
        raw_suffix="root",
        start_time=_BASE_TIME,
        artifacts_dir=str(root_dir),
        agent_name="alpha",
        role_suffix="--plan",
        agent_session="alpha",
        agent_session_role="root",
        plan_chain_root=True,
        followup_agents=[code],
    )

    events = load_bead_touches_for_agent_context(root)

    assert [(event.touch.bead_id, event.agent_label) for event in events] == [
        ("sase-1", "plan")
    ]


def test_root_without_followups_matches_alias_on_single_member_path(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(
        monkeypatch,
        [_touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z")],
    )
    root_dir = tmp_path / "root-artifacts"
    root_dir.mkdir(exist_ok=True)
    root = make_agent(
        cl_name="alias_cl",
        raw_suffix="root",
        start_time=_BASE_TIME,
        artifacts_dir=str(root_dir),
        agent_name="alpha--plan",
        role_suffix="--plan",
        agent_session="alpha",
        agent_session_role="root",
        plan_chain_root=True,
    )

    events = load_bead_touches_for_agent_context(root)

    assert [event.touch.bead_id for event in events] == ["sase-1"]
    assert events[0].agent_label is None


def test_non_root_member_row_gets_no_alias(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(
        monkeypatch,
        [_touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z")],
    )
    code = _member(
        tmp_path,
        "code",
        agent_name="alpha--code",
        role_suffix="--code",
        agent_session_role="code",
    )

    events = load_bead_touches_for_agent_context(code)  # type: ignore[arg-type]

    assert events == ()


def test_viewed_rows_use_container_alias(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    _stub_query(monkeypatch, [])
    _stub_views(monkeypatch, [_view("alpha", "sase-9")])
    root = _session_root(tmp_path)

    events = load_bead_touches_for_agent_context(root)  # type: ignore[arg-type]

    assert [(event.touch.bead_id, event.agent_label) for event in events] == [  # type: ignore[union-attr]
        ("sase-9", None)
    ]
    assert events[0].touch.verbs == {"viewed": 1}  # type: ignore[union-attr]


def test_merge_and_render_fold_container_close(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
    tmp_path: Path,
) -> None:
    preview = BeadNotePreview(
        id="sase-1:1",
        author="alpha",
        timestamp="2026-09-20T16:00:00Z",
        text="bench note",
    )
    _stub_query(
        monkeypatch,
        [
            _touch(
                "alpha",
                "sase-1",
                verbs={"closed": 1, "noted": 1},
                last_at="2026-09-20T16:00:00Z",
                note_preview=preview,
                close=BeadTouchClose(
                    closed_at="2026-09-20T16:00:00Z",
                    resolution="done",
                    standing=True,
                ),
            ),
            _touch(
                "alpha--code",
                "sase-2",
                verbs={"noted": 1},
                last_at="2026-09-20T17:00:00Z",
            ),
        ],
    )
    root = _session_root(tmp_path, phase_bead_id="sase-1")

    events = load_bead_touches_for_agent_context(root)  # type: ignore[arg-type]
    entries = merge_bead_touch_entries(
        events,  # type: ignore[arg-type]
        (),
        own_bead_ids_for_agent(root),  # type: ignore[arg-type]
    )
    by_id = {entry.bead_id: entry for entry in entries}

    assert by_id["sase-1"].own is True
    assert by_id["sase-1"].agent_close is not None
    assert by_id["sase-1"].agent_close.standing is True
    assert by_id["sase-1"].verbs["closed"] == 1
    assert by_id["sase-1"].verbs["noted"] == 1

    text = Text()
    append_agent_bead_touch_rows(text, entries=entries)
    assert "CLOSED" in text.plain
