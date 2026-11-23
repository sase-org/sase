"""Bead-display fingerprint coverage for bead warmup."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models.agent_bead import _bead_display_fingerprint
from tests.ace.tui._agents_bead_warmup_helpers import (
    clear_bead_display_cache,
    make_agent,
)

pytestmark = pytest.mark.usefixtures("clear_bead_display_cache")

__all__ = [
    "test_bead_display_fingerprint_ignores_other_event_lineages",
    "test_bead_display_fingerprint_tracks_candidate_lineage_creation",
    "test_bead_display_fingerprint_tracks_legacy_store_changes",
]


def test_bead_display_fingerprint_ignores_other_event_lineages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n", encoding="utf-8")
    (beads_dir / "events" / "manifest.json").write_text(
        '{"schema_version":1,"stream_count":2}\n', encoding="utf-8"
    )
    candidate_stream = streams_dir / "sase-x.jsonl"
    unrelated_stream = streams_dir / "other.jsonl"
    candidate_stream.write_text("candidate event\n", encoding="utf-8")
    unrelated_stream.write_text("unrelated event\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    agent = make_agent(
        agent_name="sase-x.3",
        cl_name="fingerprint",
        raw_suffix="1",
        project_file=str(tmp_path / "project" / "project.yml"),
    )

    before = _bead_display_fingerprint(agent)
    assert before is not None

    unrelated_stream.write_text(
        "unrelated stream received another event\n", encoding="utf-8"
    )
    assert _bead_display_fingerprint(agent) == before

    candidate_stream.write_text("candidate lineage changed\n", encoding="utf-8")
    assert _bead_display_fingerprint(agent) != before


def test_bead_display_fingerprint_tracks_candidate_lineage_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n", encoding="utf-8")
    manifest = beads_dir / "events" / "manifest.json"
    manifest.write_text('{"schema_version":1,"stream_count":1}\n', encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    agent = make_agent(
        agent_name="sase-new.1",
        cl_name="new-lineage",
        raw_suffix="1",
        project_file=str(tmp_path / "project" / "project.yml"),
    )

    missing = _bead_display_fingerprint(agent)
    assert missing is not None
    (streams_dir / "sase-new.jsonl").write_text(
        "new candidate bead\n", encoding="utf-8"
    )
    manifest.write_text('{"schema_version":1,"stream_count":2}\n', encoding="utf-8")

    assert _bead_display_fingerprint(agent) != missing


def test_bead_display_fingerprint_tracks_legacy_store_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    (beads_dir / "config.json").write_text("{}\n", encoding="utf-8")
    issues = beads_dir / "issues.jsonl"
    issues.write_text('{"id":"sase-x.3"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    agent = make_agent(
        agent_name="sase-x.3",
        cl_name="legacy",
        raw_suffix="1",
        project_file=str(tmp_path / "project" / "project.yml"),
    )

    before = _bead_display_fingerprint(agent)
    assert before is not None
    issues.write_text('{"id":"sase-x.3","title":"updated"}\n', encoding="utf-8")

    assert _bead_display_fingerprint(agent) != before
