"""Output-contract tests for the artifact-run-prune, epic-launch-flush, and
notification-store-compact chops.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.chops.builtin import run_builtin_chop
from sase.core.agent_artifact_run_retention_models import (
    AceRunProtectionSnapshot,
    AceRunRetentionCounts,
    AceRunRetentionItem,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    EmptyAceRunShard,
)
from sase.core.time import get_timezone
from sase.notifications.store import load_notifications

from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    _write_context,
)


def _assert_configured_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    expected_offset = get_timezone().utcoffset(parsed.replace(tzinfo=None))
    assert parsed.utcoffset() == expected_offset
    return parsed


def _retention_plan(
    *,
    selected: tuple[AceRunRetentionItem, ...] = (),
    empty_shards: tuple[EmptyAceRunShard, ...] = (),
    sources_unavailable: tuple[str, ...] = (),
    reclaimable_bytes: int = 0,
) -> AceRunRetentionPlan:
    counts = AceRunRetentionCounts(
        candidates=len(selected),
        selected=len(selected),
        empty_out_of_range_shards=len(empty_shards),
        protected=0,
        truncated=0,
    )
    return AceRunRetentionPlan(
        policy=AceRunRetentionPolicy(
            now=datetime(2026, 1, 15, 12, 0, 0),
            keep_recent_months=2,
        ),
        protections=AceRunProtectionSnapshot(),
        selected=selected,
        protected=(),
        empty_out_of_range_shards=empty_shards,
        counts=counts,
        reclaimable_bytes=reclaimable_bytes,
        sources_unavailable=sources_unavailable,
    )


def _selected_item(tmp_path: Path) -> AceRunRetentionItem:
    return AceRunRetentionItem(
        project="proj",
        timestamp="20260101000000",
        artifact_dir=str(tmp_path / "proj" / "artifacts" / "ace-run" / "old-run"),
        size_bytes=2048,
        reason="older_than_recent_2_months",
    )


def _empty_shard(tmp_path: Path) -> EmptyAceRunShard:
    return EmptyAceRunShard(
        project="proj",
        kind="day",
        path=str(tmp_path / "proj" / "artifacts" / "ace-run" / "202501" / "01"),
        reason="outside_startup_shard_window",
    )


def _stub_retention_plan(
    monkeypatch: pytest.MonkeyPatch, plan: AceRunRetentionPlan
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    monkeypatch.setattr(
        script,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )


def _run_artifact_prune(tmp_path: Path) -> dict[str, object]:
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    return json.loads(result_path.read_text(encoding="utf-8"))


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
    notifications: list[Any] = []
    monkeypatch.setattr(
        script,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda notification, **kwargs: notifications.append((notification, kwargs)),
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
    assert notifications == []


def test_artifact_run_prune_upserts_actionable_preview_notification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    plan = SimpleNamespace(
        counts=SimpleNamespace(
            candidates=3,
            selected=1,
            empty_out_of_range_shards=1,
            protected=1,
        ),
        reclaimable_bytes=2048,
        sources_unavailable=(),
        selected=(
            SimpleNamespace(
                project="proj",
                timestamp="20260101000000",
                artifact_dir="/tmp/proj/artifacts/ace-run/202601/01/20260101000000",
                size_bytes=2048,
            ),
        ),
        empty_out_of_range_shards=(
            SimpleNamespace(project="proj", kind="day", path="/tmp/proj/day"),
        ),
    )
    notifications: list[Any] = []
    monkeypatch.setattr(
        script,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda notification, **kwargs: notifications.append((notification, kwargs)),
    )

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    out = capsys.readouterr().out
    assert "selected=1" in out
    assert len(notifications) == 1
    notification, kwargs = notifications[0]
    assert notification.sender == "axe"
    assert notification.action == "ViewReport"
    assert notification.dedup_key.startswith("artifact_run_prune:")
    assert "artifact-retention" in notification.tags
    assert "apply_command" not in notification.action_data
    assert kwargs["plus_one_timestamp"] == notification.timestamp
    _assert_configured_aware_timestamp(notification.timestamp)
    report = json.loads(notification.action_data["report"])
    assert report["title"] == "ACE run pruning preview"
    assert kwargs["plus_one_note"] == (
        "Still previewing 1 run dir(s), 1 empty shard(s), 2.0 KiB reclaimable."
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"


def test_artifact_run_prune_notifies_when_protection_sources_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = _write_context(tmp_path, result_path)
    plan = SimpleNamespace(
        counts=SimpleNamespace(
            candidates=2,
            selected=0,
            empty_out_of_range_shards=0,
            protected=2,
        ),
        reclaimable_bytes=0,
        sources_unavailable=("beads: unreadable",),
        selected=(),
        empty_out_of_range_shards=(),
    )
    notifications: list[Any] = []
    monkeypatch.setattr(
        script,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda notification, **kwargs: notifications.append((notification, kwargs)),
    )

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    err = capsys.readouterr().err
    assert "protection source unavailable" in err
    assert len(notifications) == 1
    notification, kwargs = notifications[0]
    assert notification.color == "#D14343"
    assert notification.notes[0] == "ACE run pruning needs attention"
    assert kwargs["plus_one_timestamp"] == notification.timestamp
    _assert_configured_aware_timestamp(notification.timestamp)
    assert kwargs["plus_one_note"] == "Still blocked by 1 protection source(s)."
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "protection_unavailable"


def test_artifact_run_prune_real_store_reclaimable_preview_uses_aware_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = _retention_plan(
        selected=(_selected_item(tmp_path),),
        empty_shards=(_empty_shard(tmp_path),),
        reclaimable_bytes=2048,
    )
    _stub_retention_plan(monkeypatch, plan)

    result = _run_artifact_prune(tmp_path)

    out = capsys.readouterr().out
    assert "selected=1" in out
    assert result["status"] == "ok"
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.action == "ViewReport"
    assert notification.dedup_key is not None
    _assert_configured_aware_timestamp(notification.timestamp)


def test_artifact_run_prune_real_store_repeat_appends_aware_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = _retention_plan(
        selected=(_selected_item(tmp_path),),
        empty_shards=(_empty_shard(tmp_path),),
        reclaimable_bytes=2048,
    )
    _stub_retention_plan(monkeypatch, plan)

    first_result = _run_artifact_prune(tmp_path)
    first = load_notifications()[0]
    second_result = _run_artifact_prune(tmp_path)

    assert first_result["status"] == "ok"
    assert second_result["status"] == "ok"
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.id == first.id
    assert notification.timestamp == first.timestamp
    assert len(notification.plus_ones) == 1
    plus_one = notification.plus_ones[0]
    _assert_configured_aware_timestamp(plus_one.timestamp)
    assert plus_one.note == (
        "Still previewing 1 run dir(s), 1 empty shard(s), 2.0 KiB reclaimable."
    )


def test_artifact_run_prune_real_store_protection_warning_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = _retention_plan(sources_unavailable=("beads: unreadable",))
    _stub_retention_plan(monkeypatch, plan)

    first_result = _run_artifact_prune(tmp_path)
    second_result = _run_artifact_prune(tmp_path)

    err = capsys.readouterr().err
    assert "protection source unavailable" in err
    assert first_result["status"] == "check_error"
    assert first_result["reason"] == "protection_unavailable"
    assert second_result["status"] == "check_error"
    assert second_result["reason"] == "protection_unavailable"
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.color == "#D14343"
    _assert_configured_aware_timestamp(notification.timestamp)
    assert len(notification.plus_ones) == 1
    plus_one = notification.plus_ones[0]
    _assert_configured_aware_timestamp(plus_one.timestamp)
    assert plus_one.note == "Still blocked by 1 protection source(s)."


def test_artifact_run_prune_real_store_empty_shards_only_preview_notifies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = _retention_plan(empty_shards=(_empty_shard(tmp_path),))
    _stub_retention_plan(monkeypatch, plan)

    result = _run_artifact_prune(tmp_path)

    assert result["status"] == "ok"
    assert result["counters"]["empty_shards"] == 1
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    _assert_configured_aware_timestamp(notification.timestamp)
    assert notification.notes[1] == ("0 run dir(s), 1 empty shard(s), 0 B reclaimable.")


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
