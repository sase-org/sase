"""Tests for legacy agent bead views (bead sase-14j.6).

``bead_views.jsonl`` is no longer written — agents are refused at
``sase bead show`` — but the panel loader folds legacy rows behind the
durable index facts as a weaker ``viewed`` signal that is never promoted
to ``read`` and never touches the audited artifact-read log. The fold
itself runs in the Rust member query; these tests prove the loader
surfaces the folded rows, refreshes when the log changes, and keeps the
established merge/render contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.ace.tui._bead_touches_loader as bead_touches
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.ace.tui._bead_touches_loader import load_bead_touches_for_agent_context
from sase.ace.tui._bead_touches_merge import merge_bead_touch_entries
from sase.ace.tui._bead_touches_shared import (
    BeadTouchDisplayEvent as _BeadTouchDisplayEvent,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    _bead_touch_glyph,
    _styled_bead_verb_chips,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import MEMORY_GLYPH
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)
from sase.core.bead_touch_index_facade import (
    BeadTouch,
    merge_view_touches,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_PROJECT = "gh_sase-org__sase"
_AGENT = "owner.machine.alpha"


def _view_row(bead_id: str, agent_name: str = _AGENT) -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "view-1",
        "timestamp": "2026-09-20T16:00:00+00:00",
        "project": _PROJECT,
        "cwd": "/work/sase_31",
        "bead_id": bead_id,
        "agent_name": agent_name,
    }


def _write_views_log(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            json.dump(row, handle, sort_keys=True)
            handle.write("\n")


def _write_index(index_path: Path, rows: list[dict[str, object]]) -> None:
    doc = {
        "schema_version": 4,
        "generation": "gen-1",
        "streams": {"s-1": [1, 100]},
        "touches": [
            {
                "actor": row["actor"],
                "bead_id": row["bead_id"],
                "title": f"Title {row['bead_id']}",
                "issue_type": "task",
                "status": "open",
                "verbs": row.get("verbs", {"updated": 1}),
                "first_at": row.get("last_at", "2026-09-20T16:00:00Z"),
                "last_at": row.get("last_at", "2026-09-20T16:00:00Z"),
                "current_note_count": 0,
                "creation_reason_truncated": False,
                "stream_id": "s-1",
            }
            for row in rows
        ],
    }
    index_path.write_text(json.dumps(doc), encoding="utf-8")


def _viewed_touch(
    bead_id: str,
    *,
    actor: str = "alpha",
    count: int = 1,
    first_at: str = "2026-09-20T16:00:00+00:00",
    last_at: str = "2026-09-20T16:00:00+00:00",
) -> BeadTouch:
    """Build the folded ``viewed`` row the member query returns."""
    return BeadTouch(
        actor=actor,
        bead_id=bead_id,
        verbs={"viewed": count},
        first_at=first_at,
        last_at=last_at,
    )


# --- merge + render -------------------------------------------------------


def test_facade_merge_orders_durable_first() -> None:
    durable = (BeadTouch(actor="a", bead_id="sase-1", verbs={"noted": 1}),)
    views = (BeadTouch(actor="a", bead_id="sase-2", verbs={"viewed": 1}),)

    merged = merge_view_touches(durable, views)

    assert [row.bead_id for row in merged] == ["sase-1", "sase-2"]
    assert durable[0].verbs == {"noted": 1}


def _display(touch: BeadTouch) -> _BeadTouchDisplayEvent:
    return _BeadTouchDisplayEvent(touch=touch)


def test_merge_folds_viewed_behind_durable_title_and_verbs() -> None:
    durable = BeadTouch(
        actor="a",
        bead_id="sase-14j.6",
        title="Record agent bead views",
        verbs={"noted": 2},
        first_at="2026-09-20T14:00:00Z",
        last_at="2026-09-20T15:00:00Z",
    )
    viewed = _viewed_touch("sase-14j.6")

    (entry,) = merge_bead_touch_entries((_display(durable), _display(viewed)), (), ())

    assert entry.title == "Record agent bead views"
    assert entry.verbs == {"noted": 2, "viewed": 1}
    assert entry.last_at == "2026-09-20T16:00:00+00:00"
    assert entry.first_at == "2026-09-20T14:00:00Z"


def test_viewed_only_entry_renders_weakest_and_never_read() -> None:
    viewed = _viewed_touch(
        "sase-9v",
        first_at="2026-09-20T16:00:00+00:00",
        last_at="2026-09-20T16:05:00+00:00",
        count=2,
    )
    (entry,) = merge_bead_touch_entries((_display(viewed),), (), ())

    assert entry.verbs == {"viewed": 2}
    assert "read" not in entry.verbs
    assert _bead_touch_glyph(entry) == MEMORY_GLYPH
    assert [chip for chip, _ in _styled_bead_verb_chips(entry)] == ["viewed ×2"]


def test_viewed_chip_sorts_after_read() -> None:
    (entry,) = merge_bead_touch_entries(
        (
            _display(
                BeadTouch(
                    actor="a",
                    bead_id="sase-1",
                    verbs={"noted": 1, "read": 2, "viewed": 3},
                )
            ),
        ),
        (),
        (),
    )

    assert [chip for chip, _ in _styled_bead_verb_chips(entry)] == [
        "noted",
        "read ×2",
        "viewed ×3",
    ]


# --- loader ---------------------------------------------------------------


class _StubSnapshot:
    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        return AgentIdentitySnapshot(AgentOwnerIdentity("owner", "machine"))


@pytest.fixture
def _views_loader_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    index_path = tmp_path / "agent_bead_touches.json"
    index_path.write_text(
        json.dumps(
            {"schema_version": 4, "generation": "gen-1", "streams": {}, "touches": []}
        ),
        encoding="utf-8",
    )
    views_path = tmp_path / "bead_views.jsonl"
    monkeypatch.setattr(
        bead_touches, "_project_name_for_agent", lambda agent: "test-proj"
    )
    monkeypatch.setattr(bead_touches, "touch_index_path", lambda project: index_path)
    monkeypatch.setattr(bead_touches, "AgentIdentitySnapshot", _StubSnapshot)
    monkeypatch.setattr(bead_touches, "_bead_touches_cache", BoundedLRUCache(128))
    monkeypatch.setattr(
        bead_touches, "_bead_touches_context_cache", BoundedLRUCache(128)
    )
    monkeypatch.setattr(bead_touches, "bead_views_log_path", lambda project: views_path)
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


def test_loader_surfaces_viewed_only_beads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _views_loader_env: dict[str, object],
) -> None:
    views_path = _views_loader_env["views_path"]
    assert isinstance(views_path, Path)
    _write_views_log(
        views_path,
        [
            _view_row("sase-9v", agent_name=_AGENT),
            _view_row("sase-9w", agent_name="stranger"),
        ],
    )

    events = load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )

    assert [(event.touch.bead_id, event.touch.verbs) for event in events] == [
        ("sase-9v", {"viewed": 1})
    ]


def test_loader_folds_view_counts_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _views_loader_env: dict[str, object],
) -> None:
    views_path = _views_loader_env["views_path"]
    assert isinstance(views_path, Path)
    _write_views_log(
        views_path,
        [
            dict(
                _view_row("sase-9v", agent_name=_AGENT),
                timestamp="2026-09-20T16:00:00+00:00",
            ),
            dict(
                _view_row("sase-9v", agent_name=_AGENT),
                timestamp="2026-09-20T17:00:00+00:00",
            ),
            dict(_view_row("sase-9v", agent_name=_AGENT), timestamp="not-a-time"),
            dict(_view_row("sase-9w", agent_name="stranger")),
        ],
    )

    events = load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )

    assert [(event.touch.bead_id, event.touch.verbs) for event in events] == [
        ("sase-9v", {"viewed": 3})
    ]
    assert events[0].touch.first_at == "2026-09-20T16:00:00+00:00"
    assert events[0].touch.last_at == "2026-09-20T17:00:00+00:00"


def test_loader_refreshes_when_views_log_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _views_loader_env: dict[str, object],
) -> None:
    views_path = _views_loader_env["views_path"]
    assert isinstance(views_path, Path)
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    assert load_bead_touches_for_agent_context(agent) == ()

    _write_views_log(views_path, [_view_row("sase-9v", agent_name=_AGENT)])
    for entry in bead_touches._bead_touches_cache.values():
        entry.last_read_monotonic -= 10.0

    events = load_bead_touches_for_agent_context(agent)
    assert [event.touch.bead_id for event in events] == ["sase-9v"]
