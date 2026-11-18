"""Facade tests for the agent/bead touch index (bead sase-14j.2)."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core import bead_touch_index_facade as touch_index
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)
from sase.core.bead_touch_index_query import _touch_from_dict
from sase.core.bead_touch_index_store import _refresh_touch_index

_CREATOR = "claude_coder"
_OWNER = AgentOwnerIdentity("bbugyi200", "athena")
_IDENTITY = AgentIdentitySnapshot(_OWNER)
_GLOBALIZED = "bbugyi200.athena.0oa"


def _make_store(tmp_path: Path) -> BeadProject:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return BeadProject.init(workspace)


def test_mutation_refresh_reduces_exactly_the_streams_it_wrote(
    tmp_path: Path,
) -> None:
    """A real mutation followed by a refresh reduces exactly its streams."""
    with _make_store(tmp_path) as project:
        bead = project.create("Indexed work", IssueType.PLAN, created_by=_CREATOR)
        index_path = tmp_path / "agent_bead_touches.json"

        report = _refresh_touch_index(project.beads_dir, index_path)

        on_disk = {
            path.stem
            for path in (project.beads_dir / "events" / "streams").glob("*.jsonl")
        }
        assert on_disk, "the mutation must write at least one stream"
        assert report.full_rebuild is True
        assert report.wrote is True
        assert set(report.reduced_streams) == on_disk
        assert report.reused_streams == 0
        assert report.touch_count >= 1

        query = touch_index.query_touches_for_agent(
            index_path,
            globalized_name=_CREATOR,
            local_name=_CREATOR,
            identity=_IDENTITY,
        )
        rows = [
            touch
            for touch in query.touches
            if touch.bead_id == bead.id and touch.actor == _CREATOR
        ]
        assert len(rows) == 1
        assert rows[0].title == "Indexed work"
        assert rows[0].verbs.get("created") == 1

        steady = _refresh_touch_index(project.beads_dir, index_path)
        assert steady.full_rebuild is False
        assert steady.wrote is False
        assert steady.reduced_streams == ()
        assert steady.reused_streams == report.stream_count

        status = touch_index.touch_index_status(project.beads_dir, index_path)
        assert status.state == "fresh"
        assert status.changed_streams == ()


def test_query_actor_filter_and_missing_index_are_harmless(
    tmp_path: Path,
) -> None:
    """Actor filtering is exact; a missing index is a cache miss."""
    with _make_store(tmp_path) as project:
        project.create("Indexed work", IssueType.PLAN, created_by=_CREATOR)
        index_path = tmp_path / "agent_bead_touches.json"
        _refresh_touch_index(project.beads_dir, index_path)

        rows, _source, generation, schema = touch_index.query_touch_index_members(
            index_path,
            [touch_index.TouchQueryMember(_CREATOR, _CREATOR)],
            _IDENTITY,
        )
        assert len(rows) == 1
        assert schema == 4
        assert generation != ""

        nobody, _source, _generation, _schema = touch_index.query_touch_index_members(
            index_path,
            [touch_index.TouchQueryMember("nobody", "nobody")],
            _IDENTITY,
        )
        assert nobody == []

        missing, source, generation, _schema = touch_index.query_touch_index_members(
            tmp_path / "absent.json",
            [touch_index.TouchQueryMember(_CREATOR, _CREATOR)],
            _IDENTITY,
        )
        assert missing == []
        assert generation == ""
        assert source.missing is True

        status = touch_index.touch_index_status(
            project.beads_dir, tmp_path / "absent.json"
        )
    assert status.state == "missing"


def test_note_preview_wire_conversion_is_additive_and_defensive() -> None:
    touch = _touch_from_dict(
        {
            "actor": "owner.machine.alpha",
            "bead_id": "sase-note.2",
            "current_note_count": 2,
            "note_preview": {
                "id": "sase-note.2:7",
                "author": "owner.machine.alpha",
                "timestamp": "2026-09-25T12:34:56Z",
                "text": "Current edited note",
                "edited_at": "2026-09-25T12:35:00Z",
                "edited_by": "owner.machine.beta",
                "truncated": True,
            },
        }
    )

    assert touch.current_note_count == 2
    assert touch.note_preview == touch_index.BeadNotePreview(
        id="sase-note.2:7",
        author="owner.machine.alpha",
        timestamp="2026-09-25T12:34:56Z",
        text="Current edited note",
        edited_at="2026-09-25T12:35:00Z",
        edited_by="owner.machine.beta",
        truncated=True,
    )

    malformed = _touch_from_dict(
        {
            "actor": "owner.machine.alpha",
            "bead_id": "sase-note.2",
            "current_note_count": "not-a-count",
            "note_preview": {
                "id": "sase-note.2:7",
                "author": "owner.machine.alpha",
                "timestamp": "not-a-timestamp",
                "text": "would be unsafe",
            },
        }
    )
    assert malformed.current_note_count == 0
    assert malformed.note_preview is None


def test_close_wire_conversion_is_additive_and_defensive() -> None:
    touch = _touch_from_dict(
        {
            "actor": "owner.machine.beta",
            "bead_id": "sase-close.2",
            "close": {
                "closed_at": "2026-09-25T17:34:01Z",
                "resolution": "canceled",
                "reason": "  duplicate  ",
                "standing": True,
            },
        }
    )
    assert touch.close == touch_index.BeadTouchClose(
        closed_at="2026-09-25T17:34:01Z",
        resolution="canceled",
        reason="duplicate",
        standing=True,
    )

    missing = _touch_from_dict(
        {"actor": "owner.machine.beta", "bead_id": "sase-close.2"}
    )
    assert missing.close is None

    malformed = _touch_from_dict(
        {
            "actor": "owner.machine.beta",
            "bead_id": "sase-close.2",
            "close": {
                "closed_at": "   ",
                "resolution": 1,
                "reason": None,
                "standing": 1,
            },
        }
    )
    assert malformed.close is None

    defaults = _touch_from_dict(
        {
            "actor": "owner.machine.beta",
            "bead_id": "sase-close.2",
            "close": {"closed_at": "2026-09-25T17:34:01Z", "standing": "true"},
        }
    )
    assert defaults.close == touch_index.BeadTouchClose(
        closed_at="2026-09-25T17:34:01Z",
        resolution="done",
        reason="",
        standing=False,
    )


def test_creation_reason_wire_conversion_is_additive_and_defensive() -> None:
    touch = _touch_from_dict(
        {
            "actor": "owner.machine.alpha",
            "bead_id": "sase-1ap.3",
            "creation_reason": "  A second agent reproduced dropped retries  ",
            "creation_reason_truncated": True,
        }
    )
    assert touch.creation_reason == "A second agent reproduced dropped retries"
    assert touch.creation_reason_truncated is True

    legacy = _touch_from_dict({"actor": "owner.machine.alpha", "bead_id": "sase-1ap.3"})
    assert legacy.creation_reason == ""
    assert legacy.creation_reason_truncated is False

    malformed = _touch_from_dict(
        {
            "actor": "owner.machine.alpha",
            "bead_id": "sase-1ap.3",
            "creation_reason": 42,
            "creation_reason_truncated": "true",
        }
    )
    assert malformed.creation_reason == ""
    assert malformed.creation_reason_truncated is False


def test_touch_matches_agent_identity_rules() -> None:
    """Globalized, local, and legacy bare-local actors match; rest do not."""
    assert touch_index.touch_matches_agent(
        _GLOBALIZED, globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
    assert touch_index.touch_matches_agent(
        "  bbugyi200.athena.0oa  ",
        globalized_name=_GLOBALIZED,
        identity=_IDENTITY,
    )
    assert touch_index.touch_matches_agent(
        "0oa", globalized_name="other.agent", local_name="0oa"
    )
    assert touch_index.touch_matches_agent(
        "0oa", globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
    assert not touch_index.touch_matches_agent(
        "someone.else", globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
    assert not touch_index.touch_matches_agent(
        "", globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
    assert not touch_index.touch_matches_agent(
        "!!!", globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
    assert not touch_index.touch_matches_agent(
        "bryanbugyi34@gmail.com",
        globalized_name=_GLOBALIZED,
        identity=_IDENTITY,
    )

    rows = [
        touch_index.BeadTouch(actor="0oa", bead_id="sase-1"),
        touch_index.BeadTouch(actor="someone.else", bead_id="sase-2"),
        touch_index.BeadTouch(actor=_GLOBALIZED, bead_id="sase-3"),
    ]
    matched = [
        touch
        for touch in rows
        if touch_index.touch_matches_agent(
            touch.actor, globalized_name=_GLOBALIZED, identity=_IDENTITY
        )
    ]
    assert [touch.bead_id for touch in matched] == ["sase-1", "sase-3"]


def test_best_effort_refresh_never_raises(tmp_path: Path) -> None:
    """An unusable store resolves to a quiet skip or empty index."""
    report = touch_index.refresh_touch_index_best_effort(
        tmp_path / "no-such-store",
        index_path=tmp_path / "agent_bead_touches.json",
    )
    assert report is None or report.stream_count == 0


def test_fold_read_reasons_orders_newest_first_dedupes_and_trims() -> None:
    assert touch_index.fold_read_reasons(
        [
            ("2026-09-20T16:00:00Z", "  older reason  "),
            ("2026-09-20T16:05:00Z", "newer reason"),
            ("2026-09-20T16:06:00Z", "newer reason"),
            ("", "undated reason"),
            ("2026-09-20T16:07:00Z", "   "),
            (None, ""),
        ]
    ) == ("newer reason", "older reason", "undated reason")


def test_fold_touches_per_bead_carries_read_reasons() -> None:
    folded = touch_index.fold_touches_per_bead(
        [
            touch_index.BeadTouch(
                actor="0oa",
                bead_id="sase-1",
                verbs={"read": 1},
                first_at="2026-09-20T16:00:00Z",
                last_at="2026-09-20T16:00:00Z",
                read_reasons=("older reason",),
            ),
            touch_index.BeadTouch(
                actor="0oa",
                bead_id="sase-1",
                verbs={"read": 1},
                first_at="2026-09-20T16:05:00Z",
                last_at="2026-09-20T16:05:00Z",
                read_reasons=("newer reason",),
            ),
        ]
    )
    assert folded[0].read_reasons == ("newer reason", "older reason")


def _write_member_index(index_path: Path, touches: list[dict[str, object]]) -> None:
    """Write a raw schema-4 touch index with one row per mapping."""
    import json

    doc = {
        "schema_version": 4,
        "generation": "gen-member",
        "streams": {"s-1": [7, 700]},
        "touches": [
            {
                "actor": row["actor"],
                "bead_id": row["bead_id"],
                "title": row.get("title", ""),
                "issue_type": "task",
                "status": "open",
                "verbs": row.get("verbs", {"updated": 1}),
                "first_at": row.get("last_at", "2026-06-01T00:00:00Z"),
                "last_at": row.get("last_at", "2026-06-01T00:00:00Z"),
                "current_note_count": 0,
                "creation_reason_truncated": False,
                "stream_id": "s-1",
            }
            for row in touches
        ],
    }
    index_path.write_text(json.dumps(doc), encoding="utf-8")


def test_member_query_matches_exact_local_and_legacy_bare_names(
    tmp_path: Path,
) -> None:
    """Exact, local, and recovered bare-local actors match; rest do not."""
    index_path = tmp_path / "agent_bead_touches.json"
    _write_member_index(
        index_path,
        [
            {
                "actor": _GLOBALIZED,
                "bead_id": "sase-g",
                "last_at": "2026-06-03T00:00:00Z",
            },
            {"actor": "0oa", "bead_id": "sase-b", "last_at": "2026-06-02T00:00:00Z"},
            {
                "actor": "  0oa  ",
                "bead_id": "sase-w",
                "last_at": "2026-06-01T00:00:00Z",
            },
            {
                "actor": "someone.else",
                "bead_id": "sase-x",
                "last_at": "2026-06-04T00:00:00Z",
            },
            {
                "actor": "bryanbugyi34@gmail.com",
                "bead_id": "sase-e",
                "last_at": "2026-06-05T00:00:00Z",
            },
        ],
    )
    rows, _source, _generation, _schema = touch_index.query_touch_index_members(
        index_path,
        [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")],
        _IDENTITY,
    )
    # Newest first; the email and unrelated dotted actors never match.
    assert [(row.touch.bead_id, row.member_index) for row in rows] == [
        ("sase-g", 0),
        ("sase-b", 0),
        ("sase-w", 0),
    ]


def test_member_query_attributes_context_members_in_order(
    tmp_path: Path,
) -> None:
    """First claiming member wins, so context labels stay stable."""
    index_path = tmp_path / "agent_bead_touches.json"
    _write_member_index(
        index_path,
        [
            {"actor": "0oa", "bead_id": "sase-1", "last_at": "2026-06-01T00:00:00Z"},
            {"actor": "other", "bead_id": "sase-2", "last_at": "2026-06-02T00:00:00Z"},
        ],
    )
    rows, _source, _generation, _schema = touch_index.query_touch_index_members(
        index_path,
        [
            touch_index.TouchQueryMember(_GLOBALIZED, "0oa"),
            touch_index.TouchQueryMember("other-global", "other"),
        ],
        _IDENTITY,
    )
    assert [(row.touch.bead_id, row.member_index) for row in rows] == [
        ("sase-2", 1),
        ("sase-1", 0),
    ]


def test_member_query_rejects_truncated_and_wrong_schema_indexes(
    tmp_path: Path,
) -> None:
    """Corrupt indexes are empty misses, never partial answers."""
    members = [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")]

    truncated = tmp_path / "truncated.json"
    truncated.write_bytes(b'{"schema_version":4,"touches":[{')
    rows, source, generation, _schema = touch_index.query_touch_index_members(
        truncated, members, _IDENTITY
    )
    assert rows == [] and generation == "" and source.missing is False

    wrong_schema = tmp_path / "wrong.json"
    wrong_schema.write_text(
        '{"schema_version": 3, "generation": "g", "touches": []}',
        encoding="utf-8",
    )
    rows, _source, generation, _schema = touch_index.query_touch_index_members(
        wrong_schema, members, _IDENTITY
    )
    assert rows == [] and generation == ""


def test_member_query_source_identity_tracks_replacement(
    tmp_path: Path,
) -> None:
    """Atomic replacement — even with equal size — changes the identity."""
    index_path = tmp_path / "agent_bead_touches.json"
    members = [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")]
    _write_member_index(index_path, [{"actor": "0oa", "bead_id": "sase-1"}])
    _rows, first, _generation, _schema = touch_index.query_touch_index_members(
        index_path, members, _IDENTITY
    )

    import os

    replacement = tmp_path / "replacement.json"
    _write_member_index(replacement, [{"actor": "0oa", "bead_id": "sase-1"}])
    # Atomic replacement hands the path a new inode; force the mtime back
    # so only the file identity can distinguish the new content.
    os.replace(replacement, index_path)
    os.utime(index_path, ns=(first.mtime_ns, first.mtime_ns))
    _rows, second, _generation, _schema = touch_index.query_touch_index_members(
        index_path, members, _IDENTITY
    )

    first_key = (first.dev, first.ino, first.mtime_ns, first.size)
    second_key = (second.dev, second.ino, second.mtime_ns, second.size)
    assert first_key != second_key


def test_view_member_query_folds_only_claimed_events(tmp_path: Path) -> None:
    """Only claimed view events fold; malformed rows are skipped."""
    import json

    views_path = tmp_path / "bead_views.jsonl"
    lines = [
        {
            "schema_version": 1,
            "id": "v-1",
            "timestamp": "2026-06-01T00:00:00Z",
            "project": "p",
            "cwd": "/",
            "bead_id": "sase-1",
            "agent_name": _GLOBALIZED,
        },
        {
            "schema_version": 1,
            "id": "v-2",
            "timestamp": "2026-06-03T00:00:00Z",
            "project": "p",
            "cwd": "/",
            "bead_id": "sase-1",
            "agent_name": _GLOBALIZED,
        },
        {
            "schema_version": 1,
            "id": "v-3",
            "timestamp": "not-a-time",
            "project": "p",
            "cwd": "/",
            "bead_id": "sase-1",
            "agent_name": _GLOBALIZED,
        },
        {
            "schema_version": 1,
            "id": "v-4",
            "timestamp": "2026-06-02T00:00:00Z",
            "project": "p",
            "cwd": "/",
            "bead_id": "sase-2",
            "agent_name": "stranger",
        },
        {"schema_version": 999, "id": "v-5"},
        "not-json",
    ]
    with views_path.open("w", encoding="utf-8") as handle:
        for line in lines:
            if isinstance(line, str):
                handle.write(line + "\n")
            else:
                json.dump(line, handle)
                handle.write("\n")

    rows, source, complete = touch_index.query_bead_view_members(
        views_path,
        [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")],
        _IDENTITY,
    )
    assert complete is True
    assert source.missing is False
    assert len(rows) == 1
    assert rows[0].member_index == 0
    assert rows[0].touch.verbs == {"viewed": 3}
    assert rows[0].touch.first_at == "2026-06-01T00:00:00Z"
    assert rows[0].touch.last_at == "2026-06-03T00:00:00Z"


def test_view_member_query_reports_incomplete_for_unreadable_source(
    tmp_path: Path,
) -> None:
    """A directory as the views path is a miss, never partial rows."""
    rows, _source, complete = touch_index.query_bead_view_members(
        tmp_path,
        [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")],
        _IDENTITY,
    )
    assert rows == [] and complete is False


def test_member_query_scales_with_matches_not_source(tmp_path: Path) -> None:
    """Twenty thousand unrelated touches cost one scan, not one snapshot."""
    import gc

    index_path = tmp_path / "agent_bead_touches.json"
    _write_member_index(
        index_path,
        [{"actor": f"unrelated-{n}", "bead_id": f"sase-9.{n}"} for n in range(20_000)]
        + [
            {"actor": "0oa", "bead_id": "sase-keep.1"},
            {"actor": _GLOBALIZED, "bead_id": "sase-keep.2"},
        ],
    )
    gc.collect()
    before = sum(
        1
        for obj in gc.get_objects()
        if type(obj).__module__ == "sase.core.bead_touch_index_models"
        and type(obj).__qualname__ == "BeadTouch"
    )
    rows, _source, _generation, _schema = touch_index.query_touch_index_members(
        index_path,
        [touch_index.TouchQueryMember(_GLOBALIZED, "0oa")],
        _IDENTITY,
    )
    assert [row.touch.bead_id for row in rows] == ["sase-keep.1", "sase-keep.2"]
    gc.collect()
    after = sum(
        1
        for obj in gc.get_objects()
        if type(obj).__module__ == "sase.core.bead_touch_index_models"
        and type(obj).__qualname__ == "BeadTouch"
    )
    # Only the two claimed rows survive the query as Python objects.
    assert after - before == 2


def test_fold_touches_per_bead_prefers_standing_close() -> None:
    standing = touch_index.BeadTouchClose(
        closed_at="2026-09-20T15:00:00Z",
        standing=True,
    )
    newer = touch_index.BeadTouchClose(
        closed_at="2026-09-20T16:00:00Z",
        standing=False,
    )
    folded = touch_index.fold_touches_per_bead(
        [
            touch_index.BeadTouch(actor="a", bead_id="sase-1", close=newer),
            touch_index.BeadTouch(actor="b", bead_id="sase-1", close=standing),
        ]
    )
    assert folded[0].close == standing
