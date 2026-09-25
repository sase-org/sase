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

        report = touch_index._refresh_touch_index(project.beads_dir, index_path)

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

        query = touch_index.query_touch_index(index_path)
        rows = [
            touch
            for touch in query.touches
            if touch.bead_id == bead.id and touch.actor == _CREATOR
        ]
        assert len(rows) == 1
        assert rows[0].title == "Indexed work"
        assert rows[0].verbs.get("created") == 1

        steady = touch_index._refresh_touch_index(project.beads_dir, index_path)
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
        touch_index._refresh_touch_index(project.beads_dir, index_path)

        assert len(touch_index.query_touch_index(index_path, [_CREATOR]).touches) == 1
        assert touch_index.query_touch_index(index_path, ["nobody"]).touches == ()

        missing = touch_index.query_touch_index(tmp_path / "absent.json")
        assert missing.touches == ()
        assert missing.generation == ""

        status = touch_index.touch_index_status(
            project.beads_dir, tmp_path / "absent.json"
        )
    assert status.state == "missing"


def test_note_preview_wire_conversion_is_additive_and_defensive() -> None:
    touch = touch_index._touch_from_dict(
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

    malformed = touch_index._touch_from_dict(
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
    touch = touch_index._touch_from_dict(
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

    missing = touch_index._touch_from_dict(
        {"actor": "owner.machine.beta", "bead_id": "sase-close.2"}
    )
    assert missing.close is None

    malformed = touch_index._touch_from_dict(
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

    defaults = touch_index._touch_from_dict(
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
    matched = touch_index.touches_for_agent(
        rows, globalized_name=_GLOBALIZED, identity=_IDENTITY
    )
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
