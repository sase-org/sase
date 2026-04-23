"""Tests for the per-attempt snapshot helper."""

from __future__ import annotations

import json
from pathlib import Path

from sase.axe.run_agent_exec_attempts import snapshot_attempt


def _touch(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_snapshot_moves_files_and_writes_meta(tmp_path: Path) -> None:
    _touch(tmp_path / "live_reply.md", "partial reply bytes")
    _touch(
        tmp_path / "live_reply_timestamps.jsonl",
        '{"byte_offset": 0, "timestamp": "2026-04-22T12:00:00+00:00"}\n',
    )

    snapshot_attempt(
        str(tmp_path),
        1,
        status="failed",
        start_epoch=100.0,
        end_epoch=200.0,
        error_full="Prompt is too long\nfull traceback here",
        error_snippet="Prompt is too long",
        model="claude-sonnet-4-5",
        used_fallback=False,
    )

    snap_dir = tmp_path / "attempts" / "01"
    assert snap_dir.is_dir()
    assert (snap_dir / "live_reply.md").read_text() == "partial reply bytes"
    assert (snap_dir / "live_reply_timestamps.jsonl").exists()

    meta = json.loads((snap_dir / "attempt_meta.json").read_text())
    assert meta["attempt_number"] == 1
    assert meta["status"] == "failed"
    assert meta["error_snippet"] == "Prompt is too long"
    assert meta["model"] == "claude-sonnet-4-5"
    assert meta["used_fallback"] is False

    # Root files are truncated to empty so attempt 2 streams into a clean slate.
    assert (tmp_path / "live_reply.md").read_text() == ""
    assert (tmp_path / "live_reply_timestamps.jsonl").read_text() == ""

    # No lingering .tmp directory.
    assert not (tmp_path / "attempts" / "01.tmp").exists()


def test_snapshot_handles_missing_source_files(tmp_path: Path) -> None:
    # No live_reply files to move.
    snapshot_attempt(
        str(tmp_path),
        1,
        status="raised",
        start_epoch=100.0,
        end_epoch=200.0,
        error_full="boom",
        error_snippet="boom",
        model=None,
        used_fallback=False,
    )

    snap_dir = tmp_path / "attempts" / "01"
    assert (snap_dir / "attempt_meta.json").exists()
    meta = json.loads((snap_dir / "attempt_meta.json").read_text())
    assert meta["status"] == "raised"


def test_snapshot_is_idempotent(tmp_path: Path) -> None:
    _touch(tmp_path / "live_reply.md", "first")

    snapshot_attempt(
        str(tmp_path),
        1,
        status="failed",
        start_epoch=1.0,
        end_epoch=2.0,
        error_full="err",
        error_snippet="err",
        model=None,
        used_fallback=False,
    )

    # After first call, root is truncated. Write fresh content in root and
    # call again with the same attempt_number — it should be a no-op.
    _touch(tmp_path / "live_reply.md", "attempt 2 in progress")
    snapshot_attempt(
        str(tmp_path),
        1,
        status="failed",
        start_epoch=10.0,
        end_epoch=20.0,
        error_full="different",
        error_snippet="different",
        model=None,
        used_fallback=False,
    )

    # Snapshot content preserved from first call.
    assert (tmp_path / "attempts" / "01" / "live_reply.md").read_text() == "first"
    # Root file untouched by second call (still has "attempt 2 in progress").
    assert (tmp_path / "live_reply.md").read_text() == "attempt 2 in progress"
