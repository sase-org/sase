"""Golden tests for done, failed, retry, and mentor scan records."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

from .agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_FAILED,
    TS_ACE_RUN_REPEAT_STOPPED,
    TS_ACE_RUN_RETRIED_CHILD,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_MENTOR_DONE,
)
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_done_record_parses_done_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert rec.agent_meta is not None
    assert rec.agent_meta.plan_committed is True
    assert rec.has_done_marker is True
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.cl_name == "feature_alpha"
    assert rec.done.workspace_num == 3
    assert rec.done.workspace_dir == "/tmp/workspaces/alpha_3"
    assert rec.done.diff_path == "/tmp/diff_alpha.diff"
    assert rec.done.markdown_pdf_paths == ["/tmp/markdown_pdfs/notes.pdf"]
    assert rec.done.image_paths == ["/tmp/images/alpha.png"]
    assert rec.done.video_paths == ["/tmp/videos/alpha.mp4"]
    assert rec.done.response_path == "/tmp/resp_alpha.md"
    assert rec.done.output_path == "/tmp/out_alpha.log"
    # The agent_meta.json adds a stopped_at timestamp.
    assert rec.agent_meta is not None
    assert rec.agent_meta.stopped_at == "2026-04-27T12:05:00Z"


def test_repeat_stopped_record_carries_repeat_stop_fields(
    fixture_root: Path,
    tmp_path: Path,
) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_REPEAT_STOPPED)
    assert rec.done is not None
    # Outcome stays "completed" so %wait cascading still resolves the slot.
    assert rec.done.outcome == "completed"
    assert rec.done.repeat_stopped is True
    assert rec.done.stopped_by == "repeat_slot_1"

    # The fields survive the SQLite index round-trip (stored in record_json).
    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, fixture_root)
    indexed = query_agent_artifact_index(
        index_path,
        fixture_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=True,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=True,
        ),
    )
    indexed_rec = record_by_timestamp(indexed, TS_ACE_RUN_REPEAT_STOPPED)
    assert indexed_rec.done is not None
    assert indexed_rec.done.repeat_stopped is True
    assert indexed_rec.done.stopped_by == "repeat_slot_1"


def test_non_repeat_done_record_defaults_repeat_stop_fields(
    fixture_root: Path,
) -> None:
    # Backward-compatible defaults: an ordinary completed marker omits the
    # repeat-stop fields and must read as not-stopped.
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert rec.done is not None
    assert rec.done.repeat_stopped is False
    assert rec.done.stopped_by is None


def test_failed_record_carries_error_and_traceback(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_FAILED)
    assert rec.done is not None
    assert rec.done.outcome == "failed"
    assert rec.done.error == "RuntimeError: kaboom"
    assert rec.done.traceback is not None and "Traceback" in rec.done.traceback


def test_retried_records_link_via_lineage_fields(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    parent = record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_PARENT)
    child = record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_CHILD)

    assert parent.done is not None
    assert parent.done.retried_as_timestamp == TS_ACE_RUN_RETRIED_CHILD
    assert parent.done.retry_chain_root_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert parent.done.retry_error_category == "transient"
    assert parent.agent_meta is not None
    assert parent.agent_meta.retry_terminal is True

    assert child.agent_meta is not None
    assert child.agent_meta.retry_of_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert child.agent_meta.retry_attempt == 1
    assert child.agent_meta.retry_chain_root_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert child.has_done_marker is False  # the child is still running


def test_mentor_dir_is_walked(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_MENTOR_DONE)
    assert rec.workflow_dir_name == "mentor-bryan"
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.response_path == "/tmp/mentor.md"
    # No agent_meta.json was written; the wire keeps it as None.
    assert rec.agent_meta is None
