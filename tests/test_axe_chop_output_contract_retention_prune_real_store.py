"""Real-store artifact-run-prune output-contract tests.

Split from ``tests.test_axe_chop_output_contract_retention``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.chops.builtin import run_builtin_chop
from sase.core.agent_artifact_run_retention_models import (
    AceRunProtectionSnapshot,
    AceRunRetentionPlan,
)
from sase.notifications.store import load_notifications

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
    "test_artifact_run_prune_real_store_empty_shards_only_preview_notifies",
    "test_artifact_run_prune_real_store_protection_warning_deduplicates",
    "test_artifact_run_prune_real_store_reclaimable_preview_uses_aware_timestamps",
    "test_artifact_run_prune_real_store_repeat_appends_aware_plus_one",
    "test_artifact_run_prune_real_store_supersedes_changed_preview",
]


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
    monkeypatch.setattr(
        script,
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: retention_purge_result(),
    )
    monkeypatch.setattr(
        script,
        "write_snapshot",
        lambda *_args, **_kwargs: (
            script.preview_fingerprint(plan),
            Path("/tmp") / f"{script.preview_fingerprint(plan)}.json",
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


def _run_artifact_prune(tmp_path: Path) -> dict[str, object]:
    result_path = tmp_path / "result.json"
    context_path = write_output_contract_context(tmp_path, result_path)

    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])

    return json.loads(result_path.read_text(encoding="utf-8"))


def test_artifact_run_prune_real_store_reclaimable_preview_uses_aware_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),),
        empty_shards=(retention_empty_shard(tmp_path),),
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
    assert_configured_aware_timestamp(notification.timestamp)


def test_artifact_run_prune_real_store_repeat_appends_aware_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),),
        empty_shards=(retention_empty_shard(tmp_path),),
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
    assert_configured_aware_timestamp(plus_one.timestamp)
    assert plus_one.note == "Still available: 2.0 KiB across 1 runs."


def test_artifact_run_prune_real_store_supersedes_changed_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.core.agent_artifact_run_prune_review import (
        load_snapshot,
        parse_run_prune_review,
    )

    script = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    monkeypatch.setattr(
        script,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            label_for_ref=lambda _project: "Pretty Project"
        ),
    )
    first_plan = retention_plan(
        selected=(retention_selected_item(tmp_path),), reclaimable_bytes=2048
    )
    second_plan = retention_plan(
        selected=(retention_selected_item(tmp_path),),
        empty_shards=(retention_empty_shard(tmp_path),),
        reclaimable_bytes=2048,
    )

    script._notify_actionable_preview(first_plan)
    first = load_notifications()[0]
    script._notify_actionable_preview(second_plan)

    notifications = load_notifications()
    assert len(notifications) == 1
    current = notifications[0]
    assert current.id != first.id
    assert current.dedup_key == (
        f"artifact_run_prune:{script.preview_fingerprint(second_plan)}"
    )
    archived = {row.id: row for row in load_notifications(include_dismissed=True)}
    assert archived[first.id].dismissed
    review = parse_run_prune_review(current.action_data)
    assert review is not None
    snapshot = load_snapshot(review.fingerprint)
    assert snapshot is not None
    assert snapshot.empty_shard_count == 1
    assert snapshot.items[0].artifact_dir == first_plan.selected[0].artifact_dir


def test_artifact_run_prune_real_store_protection_warning_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = retention_plan(sources_unavailable=("beads: unreadable",))
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
    assert_configured_aware_timestamp(notification.timestamp)
    assert len(notification.plus_ones) == 1
    plus_one = notification.plus_ones[0]
    assert_configured_aware_timestamp(plus_one.timestamp)
    assert plus_one.note == "Still paused: 1 protection sources are unreadable."


def test_artifact_run_prune_real_store_empty_shards_only_preview_notifies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tz_divergence: None,
) -> None:
    plan = retention_plan(empty_shards=(retention_empty_shard(tmp_path),))
    _stub_retention_plan(monkeypatch, plan)

    result = _run_artifact_prune(tmp_path)

    assert result["status"] == "ok"
    assert result["counters"]["empty_shards"] == 1
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert_configured_aware_timestamp(notification.timestamp)
    assert "0 runs · 0 projects" in notification.notes[1]
