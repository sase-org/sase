"""Mocked artifact-run-prune output-contract tests.

Split from ``tests.test_axe_chop_output_contract_retention``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.chops.builtin import run_builtin_chop
from sase.core.agent_artifact_run_retention_models import (
    AceRunRetentionCounts,
    AceRunRetentionPlan,
)

from tests._axe_chop_output_contract_helpers import (
    assert_configured_aware_timestamp,
    isolate_chop_result_file,  # noqa: F401 (registers the result-file isolation fixture)
    retention_empty_shard,
    retention_plan,
    retention_purge_result,
    retention_selected_item,
    write_output_contract_context,
)

__all__ = [
    "test_artifact_run_prune_busy_trash_lock_skips_notification",
    "test_artifact_run_prune_emits_noop_summary",
    "test_artifact_run_prune_notifies_when_protection_sources_are_unavailable",
    "test_artifact_run_prune_purges_before_plan_and_snapshot",
    "test_artifact_run_prune_supersedes_stale_preview_key",
    "test_artifact_run_prune_upserts_actionable_preview_notification",
]


def test_artifact_run_prune_emits_noop_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)
    plan = retention_plan()
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
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: retention_purge_result(),
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
        "purged_batches": 0,
        "restored_runs": 0,
        "freed_bytes": 0,
    }
    assert notifications == []


def test_artifact_run_prune_upserts_actionable_preview_notification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),),
        empty_shards=(retention_empty_shard(tmp_path),),
        reclaimable_bytes=2048,
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
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: retention_purge_result(),
    )
    monkeypatch.setattr(
        script,
        "write_snapshot",
        lambda *_args, **_kwargs: (
            "deadbeefdeadbeef",
            tmp_path / "deadbeefdeadbeef.json",
        ),
    )
    monkeypatch.setattr(script, "_read_last_preview_key", lambda _directory: None)
    monkeypatch.setattr(script, "_write_last_preview_key", lambda *_args: None)
    monkeypatch.setattr(
        script,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            label_for_ref=lambda _project: "Pretty Project"
        ),
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
    assert "run_prune_review" in notification.action_data
    assert kwargs["plus_one_timestamp"] == notification.timestamp
    assert_configured_aware_timestamp(notification.timestamp)
    report = json.loads(notification.action_data["report"])
    assert report["title"] == "ACE run pruning preview"
    assert "Pretty Project" in json.dumps(report)
    from sase.core.agent_artifact_run_prune_review import parse_run_prune_review

    review = parse_run_prune_review(notification.action_data)
    assert review is not None
    assert review.counts.selected == 1
    assert kwargs["plus_one_note"] == "Still available: 2.0 KiB across 1 runs."
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"


def test_artifact_run_prune_notifies_when_protection_sources_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)
    base = retention_plan()
    plan = AceRunRetentionPlan(
        policy=base.policy,
        protections=base.protections,
        selected=base.selected,
        protected=base.protected,
        empty_out_of_range_shards=base.empty_out_of_range_shards,
        counts=AceRunRetentionCounts(2, 0, 0, 2, 0),
        reclaimable_bytes=0,
        sources_unavailable=("beads: unreadable",),
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
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: retention_purge_result(),
    )
    monkeypatch.setattr(
        script,
        "write_snapshot",
        lambda *_args, **_kwargs: (
            "deadbeefdeadbeef",
            tmp_path / "deadbeefdeadbeef.json",
        ),
    )
    monkeypatch.setattr(
        script,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            label_for_ref=lambda _project: "Pretty Project"
        ),
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
    assert notification.notes[0] == "ACE run pruning is paused"
    assert kwargs["plus_one_timestamp"] == notification.timestamp
    assert_configured_aware_timestamp(notification.timestamp)
    assert (
        kwargs["plus_one_note"] == "Still paused: 1 protection sources are unreadable."
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["reason"] == "protection_unavailable"


def test_artifact_run_prune_purges_before_plan_and_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),), reclaimable_bytes=2048
    )
    events: list[str] = []
    monkeypatch.setattr(
        script, "collect_ace_run_retention_protections", lambda **_kw: object()
    )
    monkeypatch.setattr(
        script,
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: events.append("purge") or retention_purge_result(),
    )
    monkeypatch.setattr(
        script,
        "plan_ace_run_retention",
        lambda *_args, **_kwargs: events.append("plan") or plan,
    )
    monkeypatch.setattr(
        script,
        "write_snapshot",
        lambda *_args, **_kwargs: (
            events.append("snapshot")
            or ("deadbeefdeadbeef", tmp_path / "deadbeefdeadbeef.json")
        ),
    )
    monkeypatch.setattr(script, "_read_last_preview_key", lambda _directory: None)
    monkeypatch.setattr(script, "_write_last_preview_key", lambda *_args: None)
    monkeypatch.setattr(
        script,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            label_for_ref=lambda _project: "Pretty Project"
        ),
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda *_args, **_kwargs: events.append("notify"),
    )
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    assert events == ["purge", "plan", "snapshot", "notify"]


def test_artifact_run_prune_busy_trash_lock_skips_notification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),), reclaimable_bytes=2048
    )
    notifications: list[object] = []
    monkeypatch.setattr(
        script, "collect_ace_run_retention_protections", lambda **_kw: object()
    )
    monkeypatch.setattr(
        script,
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: retention_purge_result(blocked_reason="busy"),
    )
    monkeypatch.setattr(
        script, "plan_ace_run_retention", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda *args, **kwargs: notifications.append(args),
    )
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    assert notifications == []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "no_op"
    assert result["reason"] == "prune_in_progress"


def test_artifact_run_prune_supersedes_stale_preview_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),), reclaimable_bytes=2048
    )
    captured: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(
        script,
        "write_snapshot",
        lambda *_args, **_kwargs: ("deadbeefdeadbeef", tmp_path / "snapshot.json"),
    )
    monkeypatch.setattr(
        script, "_read_last_preview_key", lambda _directory: "old-preview"
    )
    monkeypatch.setattr(script, "_write_last_preview_key", lambda *_args: None)
    monkeypatch.setattr(
        script,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            label_for_ref=lambda _project: "Pretty Project"
        ),
    )
    monkeypatch.setattr(
        script,
        "upsert_notification",
        lambda notification, **kwargs: captured.append((notification, kwargs)),
    )

    script._notify_actionable_preview(plan)

    assert captured[0][1]["supersedes"] == "old-preview"
