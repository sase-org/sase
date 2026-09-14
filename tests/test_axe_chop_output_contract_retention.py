"""Output-contract tests for the artifact-run-prune, epic-launch-flush, and
notification-store-compact chops.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.chops.builtin import run_builtin_chop

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def test_artifact_run_prune_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    plan = SimpleNamespace(
        counts=SimpleNamespace(
            candidates=0,
            selected=0,
            empty_out_of_range_shards=0,
            protected=0,
        ),
        reclaimable_bytes=0,
        sources_unavailable=(),
    )
    monkeypatch.setattr(
        script,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "artifact_run_prune:" in out
    assert "reason=nothing_reclaimable" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_reclaimable"
    assert result["counters"] == {
        "bytes": 0,
        "candidates": 0,
        "empty_shards": 0,
        "protected": 0,
        "selected": 0,
        "unavailable": 0,
    }


def test_epic_launch_flush_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_epic_launch_flush")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        script,
        "flush_orphaned_deferrals",
        lambda: SimpleNamespace(
            pending_scanned=2,
            active=0,
            young=2,
            flushed=0,
            settled_reaped=0,
            errors=0,
        ),
    )

    run_builtin_chop("epic_launch_flush", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "epic_launch_flush:" in out
    assert "pending=2" in out
    assert "young=2" in out
    assert "reason=nothing_due" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_due"
    assert result["counters"] == {
        "active": 0,
        "errors": 0,
        "flushed": 0,
        "pending": 2,
        "settled_reaped": 0,
        "young": 2,
    }


def test_notification_store_compact_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module(
        "sase.scripts.sase_chop_notification_store_compact"
    )
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        script,
        "compact_notification_store",
        lambda: SimpleNamespace(
            live_exists=True,
            live_bytes_before=128,
            live_bytes_after=128,
            live_rows_after=4,
            archived_count=0,
            archive_path=str(tmp_path / "notifications-archive.jsonl"),
        ),
    )

    run_builtin_chop("notification_store_compact", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "notification_store_compact:" in out
    assert "archived=0" in out
    assert "reason=nothing_archived" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "nothing_archived"
    assert result["counters"] == {
        "archived": 0,
        "live_bytes_after": 128,
        "live_bytes_before": 128,
        "live_rows": 4,
    }


def test_notification_store_compact_emits_missing_store_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module(
        "sase.scripts.sase_chop_notification_store_compact"
    )
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        script,
        "compact_notification_store",
        lambda: SimpleNamespace(
            live_exists=False,
            live_bytes_before=0,
            live_bytes_after=0,
            live_rows_after=0,
            archived_count=0,
            archive_path=str(tmp_path / "notifications-archive.jsonl"),
        ),
    )

    run_builtin_chop("notification_store_compact", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "reason=store_missing" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "store_missing"
    assert result["counters"]["archived"] == 0


def test_notification_store_compact_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module(
        "sase.scripts.sase_chop_notification_store_compact"
    )
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    monkeypatch.setattr(
        script,
        "compact_notification_store",
        lambda: SimpleNamespace(
            live_exists=True,
            live_bytes_before=13_600_000,
            live_bytes_after=120_000,
            live_rows_after=12,
            archived_count=1_001,
            archive_path=str(tmp_path / "notifications-archive.jsonl"),
        ),
    )

    run_builtin_chop("notification_store_compact", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "archived 1001 dismissed notifications" in out
    assert "archived=1001" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["counters"] == {
        "archived": 1001,
        "live_bytes_after": 120_000,
        "live_bytes_before": 13_600_000,
        "live_rows": 12,
    }
