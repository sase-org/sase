"""Shared public helpers for the Artifacts Beads filtering tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts.beads_data import BeadsSnapshot
from sase.ace.tui.widgets.artifacts.query_rows import build_beads_query_index
from sase.bead.filter_query import parse_bead_filter_query, to_query_string
from sase.bead.model import BeadNote
from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many
from tests.ace.tui._artifacts_beads_helpers import snapshot


def matched_bead_records(value: BeadsSnapshot, query: str) -> list[Any]:
    profile = compiled_profile_for_builtin_pane("beads")
    assert profile is not None
    filter_index, query_index = build_beads_query_index(
        value,
        pane_id="beads",
        generation=1,
        profile=profile,
    )
    matched_option_ids = frozenset(
        evaluate_artifact_query_many(query, query_index).matched_row_ids
    )
    return [record for record in filter_index if record.option_id in matched_option_ids]


def matched_bead_ids(tmp_path: Path, query: str) -> list[str]:
    value = snapshot(tmp_path)
    value.epics[0].issue.is_ready_to_work = True
    value.epics[0].issue.model = "codex/gpt-5"
    value.epics[0].issue.patch_name = "sase-dd"
    value.epics[0].issue.patch_bug_id = "42"
    value.epics[0].issue.external_ref = "bug:alpha#42"
    value.tasks[1].issue.assignee = "worker.alpha"
    value.phases_by_epic[("alpha", "alpha-1")][0].issue.notes = [
        BeadNote(
            id="note-1",
            timestamp="2026-01-01T00:00:00Z",
            author="test",
            text="Closed phase notes.",
        )
    ]
    value = replace(value, blocked_ids=frozenset({("alpha", "alpha-open")}))
    parsed = parse_bead_filter_query(
        query,
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )
    return [
        record.bead_id
        for record in matched_bead_records(value, to_query_string(parsed))
    ]
