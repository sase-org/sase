"""Tests for legacy agent bead views (bead sase-14j.6).

``bead_views.jsonl`` is no longer written — agents are refused at
``sase bead show`` — but the panel loader still folds legacy rows behind the
durable index facts as a weaker ``viewed`` signal that is never promoted to
``read`` and never touches the audited artifact-read log.
"""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path

import pytest

import sase.ace.tui.bead_touches as bead_touches
from sase.ace.tui.bead_touches import (
    _BeadTouchDisplayEvent,
    load_bead_touches_for_agent_context,
    merge_bead_touch_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    _bead_touch_glyph,
    _ordered_bead_verb_chips,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import MEMORY_GLYPH
from sase.bead.bead_views import (
    BEAD_VIEW_LOG_SCHEMA_VERSION,
    BeadViewEvent,
    read_bead_view_events,
    view_touches_for_agent,
    views_to_touches,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.bead_touch_index_facade import (
    BeadTouch,
    BeadTouchQuery,
    merge_view_touches,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_PROJECT = "gh_sase-org__sase"
_AGENT = "owner.machine.alpha"


def _view_row(bead_id: str, agent_name: str = _AGENT) -> dict[str, object]:
    return {
        "schema_version": BEAD_VIEW_LOG_SCHEMA_VERSION,
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


# --- read -----------------------------------------------------------------


def test_read_skips_malformed_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "bead_views.jsonl"
    _write_views_log(
        log_path,
        [
            _view_row("sase-1"),
            {"schema_version": 99, "bead_id": "sase-bad-schema"},
            {"schema_version": BEAD_VIEW_LOG_SCHEMA_VERSION},
            _view_row("   "),
            _view_row("sase-2", agent_name="  "),
        ],
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")

    events = read_bead_view_events(log_path=log_path)

    assert [event.bead_id for event in events] == ["sase-1"]


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_bead_view_events(log_path=tmp_path / "missing.jsonl") == ()


def test_read_requires_project_or_path() -> None:
    with pytest.raises(ValueError, match="project is required"):
        read_bead_view_events()


# --- synthesize -----------------------------------------------------------


def _event(
    bead_id: str, agent_name: str = _AGENT, timestamp: str = "2026-09-20T16:00:00+00:00"
) -> BeadViewEvent:
    return BeadViewEvent(
        schema_version=BEAD_VIEW_LOG_SCHEMA_VERSION,
        id="view-1",
        timestamp=timestamp,
        project=_PROJECT,
        cwd="/work",
        bead_id=bead_id,
        agent_name=agent_name,
    )


def test_views_to_touches_groups_counts_and_moments() -> None:
    rows = views_to_touches(
        [
            _event("sase-1", timestamp="2026-09-20T16:00:00+00:00"),
            _event("sase-1", timestamp="2026-09-20T17:00:00+00:00"),
            _event("sase-2", timestamp="2026-09-20T15:00:00+00:00"),
            _event("sase-2", agent_name="other", timestamp="2026-09-20T15:30:00+00:00"),
        ]
    )

    assert [(row.bead_id, row.actor) for row in rows] == [
        ("sase-1", _AGENT),
        ("sase-2", _AGENT),
        ("sase-2", "other"),
    ]
    assert rows[0].verbs == {"viewed": 2}
    assert rows[0].first_at == "2026-09-20T16:00:00+00:00"
    assert rows[0].last_at == "2026-09-20T17:00:00+00:00"
    assert rows[0].title == ""


def test_views_to_touches_empty() -> None:
    assert views_to_touches(()) == ()


def test_view_touches_for_agent_matches_like_durable() -> None:
    events = (
        _event("sase-1", agent_name=_AGENT),
        _event("sase-2", agent_name="alpha"),
        _event("sase-3", agent_name="stranger"),
        _event("sase-4", agent_name=""),
    )

    rows = view_touches_for_agent(events, globalized_name=_AGENT, local_name="alpha")

    assert [(row.bead_id, row.actor) for row in rows] == [
        ("sase-1", _AGENT),
        ("sase-2", "alpha"),
    ]


def test_facade_merge_orders_durable_first() -> None:
    durable = (BeadTouch(actor="a", bead_id="sase-1", verbs={"noted": 1}),)
    views = (BeadTouch(actor="a", bead_id="sase-2", verbs={"viewed": 1}),)

    merged = merge_view_touches(durable, views)

    assert [row.bead_id for row in merged] == ["sase-1", "sase-2"]
    assert durable[0].verbs == {"noted": 1}


# --- merge + render -------------------------------------------------------


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
    (viewed,) = views_to_touches(
        [_event("sase-14j.6", timestamp="2026-09-20T16:00:00+00:00")]
    )

    (entry,) = merge_bead_touch_entries((_display(durable), _display(viewed)), (), ())

    assert entry.title == "Record agent bead views"
    assert entry.verbs == {"noted": 2, "viewed": 1}
    assert entry.last_at == "2026-09-20T16:00:00+00:00"
    assert entry.first_at == "2026-09-20T14:00:00Z"


def test_viewed_only_entry_renders_weakest_and_never_read() -> None:
    (viewed,) = views_to_touches(
        [
            _event("sase-9v", timestamp="2026-09-20T16:00:00+00:00"),
            _event("sase-9v", timestamp="2026-09-20T16:05:00+00:00"),
        ]
    )
    (entry,) = merge_bead_touch_entries((_display(viewed),), (), ())

    assert entry.verbs == {"viewed": 2}
    assert "read" not in entry.verbs
    assert _bead_touch_glyph(entry) == MEMORY_GLYPH
    assert _ordered_bead_verb_chips(entry) == ["viewed ×2"]


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

    assert _ordered_bead_verb_chips(entry) == ["noted", "read ×2", "viewed ×3"]


# --- loader ---------------------------------------------------------------


_FAKE_GLOBALIZED = {"alpha": _AGENT}


def _fake_globalize(name: str, identity: object = None) -> str:
    return _FAKE_GLOBALIZED.get(name, name)


class _StubSnapshot:
    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        return AgentIdentitySnapshot.unconfigured()


@pytest.fixture
def _views_loader_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    index_path = tmp_path / "agent_bead_touches.json"
    index_path.write_text("{}\n", encoding="utf-8")
    views_path = tmp_path / "bead_views.jsonl"
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
    monkeypatch.setattr(bead_touches, "bead_views_log_path", lambda project: views_path)

    def _query(index_path: object, actors: object = None) -> BeadTouchQuery:
        return BeadTouchQuery(schema_version=1, generation="g", touches=())

    monkeypatch.setattr(bead_touches, "query_touch_index", _query)
    return {"views_path": views_path}


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
    for cache in (
        bead_touches._bead_touches_cache,
        bead_touches._bead_views_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic -= 10.0

    events = load_bead_touches_for_agent_context(agent)
    assert [event.touch.bead_id for event in events] == ["sase-9v"]
