"""Tests for AttemptRecord loading from artifacts directories."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models.agent import AttemptRecord, load_attempt_history


def _write_attempt(
    artifacts_dir: Path,
    n: int,
    *,
    status: str = "failed",
    error_snippet: str = "something went wrong",
) -> None:
    sub = artifacts_dir / "attempts" / f"{n:02d}"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "live_reply.md").write_text(f"attempt {n} content", encoding="utf-8")
    (sub / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")
    meta = {
        "attempt_number": n,
        "status": status,
        "start_epoch": 100.0 + n,
        "end_epoch": 150.0 + n,
        "model": "claude-sonnet-4-5",
        "used_fallback": False,
        "error_snippet": error_snippet,
        "error_full": error_snippet + " full",
    }
    (sub / "attempt_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_loads_well_formed_tree(tmp_path: Path) -> None:
    _write_attempt(tmp_path, 1)
    _write_attempt(tmp_path, 2, status="raised", error_snippet="final failure")

    records = load_attempt_history(str(tmp_path))
    assert len(records) == 2
    assert [r.attempt_number for r in records] == [1, 2]
    assert records[1].status == "raised"
    assert records[0].error_snippet == "something went wrong"


def test_missing_attempts_dir_returns_empty(tmp_path: Path) -> None:
    assert load_attempt_history(str(tmp_path)) == []


def test_none_artifacts_dir_returns_empty() -> None:
    assert load_attempt_history(None) == []


def test_malformed_meta_is_skipped(tmp_path: Path) -> None:
    _write_attempt(tmp_path, 1)
    bad = tmp_path / "attempts" / "02"
    bad.mkdir(parents=True)
    (bad / "attempt_meta.json").write_text("not json{{{", encoding="utf-8")

    records = load_attempt_history(str(tmp_path))
    assert len(records) == 1
    assert records[0].attempt_number == 1


def test_sorts_by_attempt_number_regardless_of_fs_order(tmp_path: Path) -> None:
    _write_attempt(tmp_path, 3)
    _write_attempt(tmp_path, 1)
    _write_attempt(tmp_path, 2)

    records = load_attempt_history(str(tmp_path))
    assert [r.attempt_number for r in records] == [1, 2, 3]


def test_record_read_methods_work(tmp_path: Path) -> None:
    _write_attempt(tmp_path, 1)
    records = load_attempt_history(str(tmp_path))
    assert records[0].get_reply_content() == "attempt 1 content"
    # No timestamps written → chunks is None (no entries).
    assert records[0].get_timestamped_reply_chunks() is None


def test_attempt_record_is_frozen() -> None:
    record = AttemptRecord(
        attempt_number=1,
        status="failed",
        start_epoch=0.0,
        end_epoch=1.0,
        model=None,
        used_fallback=False,
        error_snippet="x",
        error_full="x",
        live_reply_path="/nonexistent",
        timestamps_path="/nonexistent",
    )
    try:
        record.attempt_number = 2  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("AttemptRecord should be frozen")
