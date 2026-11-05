from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import sase.artifact_cli.prune_runs as prune_runs_cli
from sase.core.agent_artifact_index_lifecycle_mutations import (
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_artifact_run_prune_review import write_snapshot
from sase.core.agent_artifact_run_retention import (
    AceRunProtectionSnapshot,
    AceRunRetentionPolicy,
    plan_ace_run_retention,
)
from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import load_notifications, upsert_notification


def _args(
    projects_root: Path,
    *,
    apply: bool = False,
    json_output: bool = True,
    snapshot: str | None = None,
    notify: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        apply=apply,
        index_path=None,
        json=json_output,
        keep_recent_months=2,
        limit=None,
        notify=notify,
        project=None,
        projects_root=str(projects_root),
        snapshot=snapshot,
    )


def _terminal_run(projects_root: Path, timestamp: str) -> Path:
    path = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    (path / "done.json").write_text('{"outcome":"completed"}', encoding="utf-8")
    (path / "payload.txt").write_text(f"run {timestamp}\n", encoding="utf-8")
    return path


def _empty_protections(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        prune_runs_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(),
    )


def test_prune_runs_defaults_to_dry_run(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)
    monkeypatch.setattr(
        prune_runs_cli,
        "datetime",
        type(
            "FrozenDatetime",
            (),
            {"now": staticmethod(lambda _tz=None: datetime(2026, 9, 12, 12, 0, 0))},
        ),
    )

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["blocked"] is False
    assert payload["plan"]["counts"]["selected"] == 1
    assert Path(payload["plan"]["selected"][0]["artifact_dir"]) == old
    assert payload["execution"] is None
    assert payload["snapshot"] is None
    assert old.exists()


def test_prune_runs_apply_quarantines_and_deindexes(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _terminal_run(projects_root, "20260501000000")
    recent_stamp = datetime.now(UTC).strftime("%Y%m%d") + "000000"
    recent = _terminal_run(projects_root, recent_stamp)
    _empty_protections(monkeypatch)

    indexed = upsert_agent_artifact_index_artifacts([old])
    assert indexed > 0

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "apply"
    assert payload["blocked"] is False
    execution = payload["execution"]
    assert execution["quarantined"] == 1
    assert execution["blocked_reason"] is None
    assert execution["batch_id"]
    assert execution["restorable_until"]
    assert execution["journal_path"]
    assert execution["deindexed"] >= 1
    assert not old.exists()
    assert recent.exists()


def test_prune_runs_apply_snapshot_intersection_keeps_newly_protected(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    reviewed = _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    policy = AceRunRetentionPolicy(
        now=datetime.now(get_timezone()),
        keep_recent_months=2,
        projects_root=projects_root,
    )
    plan = plan_ace_run_retention(policy, protections=AceRunProtectionSnapshot())
    assert plan.counts.selected == 1
    fingerprint, _path = write_snapshot(plan)

    # A second eligible run appears after the snapshot, and the reviewed run
    # loses its terminal marker, so the fresh plan protects it while the
    # snapshot still lists it.
    unreviewed = _terminal_run(projects_root, "20260401000000")
    (reviewed / "done.json").unlink()

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, snapshot=fingerprint)
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    execution = payload["execution"]
    assert execution["quarantined"] == 0
    assert execution["not_reviewed"] == 1
    assert any(item["outcome"] == "not_reviewed" for item in execution["items"])
    assert any(
        item["outcome"] == "kept" and "protected:not_terminal" in item["reasons"]
        for item in execution["items"]
    )
    assert reviewed.exists()
    assert unreviewed.exists()
    snapshot = payload["snapshot"]
    assert snapshot["fingerprint"] == fingerprint
    assert snapshot["reviewed"] == 1
    assert snapshot["eligible_now"] == 0
    assert snapshot["not_reviewed"] == 1


def test_prune_runs_apply_snapshot_intersection_moves_only_reviewed(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    reviewed = _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    policy = AceRunRetentionPolicy(
        now=datetime.now(get_timezone()),
        keep_recent_months=2,
        projects_root=projects_root,
    )
    plan = plan_ace_run_retention(policy, protections=AceRunProtectionSnapshot())
    fingerprint, _path = write_snapshot(plan)

    unreviewed = _terminal_run(projects_root, "20260401000000")

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, snapshot=fingerprint)
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    execution = payload["execution"]
    assert execution["quarantined"] == 1
    assert execution["not_reviewed"] == 1
    assert not reviewed.exists()
    assert unreviewed.exists()
    snapshot = payload["snapshot"]
    assert snapshot["fingerprint"] == fingerprint
    assert snapshot["reviewed"] == 1
    assert snapshot["eligible_now"] == 1
    assert snapshot["not_reviewed"] == 1


def test_prune_runs_apply_missing_snapshot_exits_2_without_mutation(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, snapshot="0123456789abcdef")
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["blocked"] is True
    assert payload["blocked_reason"] == "snapshot_unavailable"
    assert payload["execution"] is None
    assert old.exists()


def test_prune_runs_snapshot_requires_apply(
    monkeypatch: Any, capsys: Any, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, snapshot="0123456789abcdef")
    )

    assert exit_code == 2
    assert "requires --apply" in capsys.readouterr().err


def test_prune_runs_apply_blocked_when_protections_are_unavailable(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _terminal_run(projects_root, "20260501000000")
    monkeypatch.setattr(
        prune_runs_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(
            sources_unavailable=("plans sidecar",)
        ),
    )
    indexed = upsert_agent_artifact_index_artifacts([old])
    assert indexed > 0

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["mode"] == "apply"
    assert payload["blocked"] is True
    assert payload["execution"]["blocked_reason"] == "protection_unavailable"
    assert payload["execution"]["quarantined"] == 0
    assert old.exists()


def test_prune_runs_notify_writes_result_and_retires_previews(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)
    preview = Notification(
        id="preview-row",
        timestamp="2026-09-12T12:00:00+00:00",
        sender="axe",
        notes=["ACE run pruning preview is available"],
        tags=normalize_notification_tags(("artifact-retention", "ace-run", "preview")),
        action="ViewReport",
        action_data={},
        dedup_key="artifact_run_prune:deadbeefdeadbeef",
    )
    upsert_notification(
        preview,
        plus_one_note="Still previewing 1 run dir.",
        plus_one_timestamp="2026-09-12T12:00:00+00:00",
    )

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, notify=True)
    )

    assert exit_code == 0
    capsys.readouterr()
    rows = {row.dedup_key: row for row in load_notifications(include_dismissed=True)}
    assert rows["artifact_run_prune:deadbeefdeadbeef"].dismissed is True
    batch_id = next(
        key for key in rows if key and key.startswith("artifact_run_trash:")
    ).removeprefix("artifact_run_trash:")
    result_row = rows[f"artifact_run_trash:{batch_id}"]
    assert result_row.dismissed is False
    assert result_row.icon == "🧹"
    assert "artifact-retention" in result_row.tags
    report = json.loads(result_row.action_data["report"])
    assert report["title"] == "ACE runs moved to trash"
    assert any(
        f"sase artifact trash restore runs:{batch_id}" in block.get("text", "")
        for block in report["blocks"]
        if block.get("kind") == "text"
    )


def test_prune_runs_notify_failure_keeps_exit_0(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("store is down")

    monkeypatch.setattr(prune_runs_cli, "upsert_notification", _boom)

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, notify=True)
    )

    assert exit_code == 0
    assert "notification failed" in capsys.readouterr().err


def test_prune_runs_apply_text_reports_batch_and_restore_hint(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)

    exit_code = prune_runs_cli.handle_prune_runs(
        _args(projects_root, apply=True, json_output=False)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Moved 1 run dirs" in out
    assert "to trash" in out
    assert "restorable until" in out
    assert "sase artifact trash restore runs:" in out


def test_prune_runs_emits_typed_operation_result(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
    tmp_path_factory: Any,
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)
    result_path = tmp_path_factory.mktemp("result") / "result.json"
    monkeypatch.setenv("SASE_PROC_RESULT_PATH", str(result_path))

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root, apply=True))

    assert exit_code == 0
    capsys.readouterr()
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored["operation"] == "artifact.prune-runs"
    assert stored["success"] is True
    assert stored["payload"]["quarantined"] == 1
    assert stored["payload"]["blocked_reason"] is None


def test_prune_runs_fingerprint_matches_chop_preview(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.core.agent_artifact_run_prune_review import preview_fingerprint
    from sase.scripts.sase_chop_artifact_run_prune import (
        _preview_report as _chop_report,
    )

    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    _empty_protections(monkeypatch)
    policy = AceRunRetentionPolicy(
        now=datetime.now(get_timezone()),
        keep_recent_months=2,
        projects_root=projects_root,
    )
    plan = plan_ace_run_retention(policy, protections=AceRunProtectionSnapshot())
    assert (
        preview_fingerprint(plan)
        == hashlib.sha256(
            json.dumps(
                {
                    "selected": [
                        {
                            "project": item.project,
                            "timestamp": item.timestamp,
                            "artifact_dir": item.artifact_dir,
                            "size_bytes": item.size_bytes,
                        }
                        for item in plan.selected
                    ],
                    "empty_shards": [
                        {
                            "project": shard.project,
                            "kind": shard.kind,
                            "path": shard.path,
                        }
                        for shard in plan.empty_out_of_range_shards
                    ],
                    "sources_unavailable": list(plan.sources_unavailable),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
    )
    assert _chop_report(plan).title == "ACE run pruning preview"
