from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_run_prune_review import (
    RUN_PRUNE_REVIEW_SCHEMA_VERSION,
    RunPruneReview,
    build_review,
    encode_run_prune_review,
    load_snapshot,
    parse_run_prune_review,
    preview_fingerprint,
    snapshot_dir,
    write_snapshot,
)
from sase.core.agent_artifact_run_retention_models import (
    AceRunProtectionSnapshot,
    AceRunRetentionCounts,
    AceRunRetentionItem,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    EmptyAceRunShard,
)


def _plan(now: datetime | None = None) -> AceRunRetentionPlan:
    moment = now or datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
    policy = AceRunRetentionPolicy(
        now=moment, keep_recent_months=2, projects_root="/tmp/roots"
    )
    selected = (
        AceRunRetentionItem(
            project="sase",
            timestamp="20260701000000",
            artifact_dir="/tmp/roots/sase/artifacts/ace-run/202607/01/20260701000000",
            size_bytes=2048,
            reason="older_than_recent_2_months",
        ),
        AceRunRetentionItem(
            project="home",
            timestamp="20260715000000",
            artifact_dir="/tmp/roots/home/artifacts/ace-run/202607/15/20260715000000",
            size_bytes=1024,
            reason="older_than_recent_2_months",
        ),
    )
    return AceRunRetentionPlan(
        policy=policy,
        protections=AceRunProtectionSnapshot(),
        selected=selected,
        protected=(),
        empty_out_of_range_shards=(
            EmptyAceRunShard(
                project="sase", path="/tmp/roots/sase/x", kind="day", reason="r"
            ),
        ),
        counts=AceRunRetentionCounts(
            candidates=10,
            selected=2,
            protected=8,
            empty_out_of_range_shards=1,
            truncated=0,
        ),
        reclaimable_bytes=3072,
        sources_unavailable=(),
    )


def test_preview_fingerprint_is_stable_and_hex() -> None:
    plan = _plan()
    first = preview_fingerprint(plan)
    assert first == preview_fingerprint(_plan())
    assert len(first) == 16
    assert all(c in "0123456789abcdef" for c in first)
    changed = _plan()
    bigger = AceRunRetentionPlan(
        policy=changed.policy,
        protections=changed.protections,
        selected=changed.selected
        + (
            AceRunRetentionItem(
                project="sase",
                timestamp="20260601000000",
                artifact_dir="/tmp/roots/sase/artifacts/ace-run/202606/01/x",
                size_bytes=1,
                reason="older_than_recent_2_months",
            ),
        ),
        protected=changed.protected,
        empty_out_of_range_shards=changed.empty_out_of_range_shards,
        counts=changed.counts,
        reclaimable_bytes=changed.reclaimable_bytes,
        sources_unavailable=changed.sources_unavailable,
    )
    assert preview_fingerprint(bigger) != first


def test_write_and_load_snapshot_round_trip(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    plan = _plan()
    fingerprint, path = write_snapshot(plan)

    assert path == snapshot_dir() / f"{fingerprint}.json"
    snapshot = load_snapshot(fingerprint)
    assert snapshot is not None
    assert snapshot.fingerprint == fingerprint
    assert snapshot.keep_recent_months == 2
    assert len(snapshot.items) == 2
    assert snapshot.items[0].project == "sase"
    assert snapshot.items[0].size_bytes == 2048
    assert snapshot.empty_shard_count == 1
    assert snapshot.sources_unavailable == ()
    reviewed = snapshot.to_reviewed()
    assert reviewed.fingerprint == fingerprint
    assert len(reviewed.dirs) == 2


def test_load_snapshot_returns_none_for_missing_or_invalid(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    assert load_snapshot("0123456789abcdef") is None
    assert load_snapshot("not-a-fingerprint") is None
    assert load_snapshot("") is None
    bad = snapshot_dir() / ("0" * 16 + ".json")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not json", encoding="utf-8")
    assert load_snapshot("0" * 16) is None


def test_snapshot_gc_keeps_newest_eight(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    kept: list[str] = []
    for day in range(1, 12):
        plan = _plan(now=datetime(2026, 9, day, 12, 0, 0, tzinfo=UTC))
        bumped = AceRunRetentionPlan(
            policy=plan.policy,
            protections=plan.protections,
            selected=tuple(
                AceRunRetentionItem(
                    project=item.project,
                    timestamp=item.timestamp,
                    artifact_dir=item.artifact_dir,
                    size_bytes=item.size_bytes + day,
                    reason=item.reason,
                )
                for item in plan.selected
            ),
            protected=plan.protected,
            empty_out_of_range_shards=plan.empty_out_of_range_shards,
            counts=plan.counts,
            reclaimable_bytes=plan.reclaimable_bytes,
            sources_unavailable=plan.sources_unavailable,
        )
        fingerprint, _path = write_snapshot(
            bumped, captured_at=datetime(2026, 9, day, 12, 0, 0, tzinfo=UTC)
        )
        kept.append(fingerprint)
    assert len(set(kept)) == len(kept)
    survivors = {path.stem for path in snapshot_dir().glob("*.json")}
    assert len(survivors) == 8
    # The newest snapshots survive; the just-written one is never deleted.
    assert kept[-1] in survivors
    assert kept[0] not in survivors


def test_build_review_payload_shape_and_order() -> None:
    plan = _plan()
    review = build_review(
        plan,
        fingerprint="f" * 16,
        captured_at=datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC),
    )

    assert review.fingerprint == "f" * 16
    assert review.keep_recent_months == 2
    assert review.first_kept_month == "2026-08"
    assert review.counts.selected == 2
    assert review.counts.protected == 8
    assert review.counts.empty_shards == 1
    assert review.reclaimable_bytes == 3072
    assert [p.project for p in review.projects] == ["sase", "home"]
    assert review.projects[0].runs == 1
    assert review.projects[0].bytes == 2048
    assert review.projects[0].oldest == "20260701000000"
    assert review.unavailable_source_count == 0


def test_review_encode_parse_round_trip() -> None:
    review = build_review(_plan())
    encoded = encode_run_prune_review(review)
    assert "\n" not in encoded and " " not in encoded
    parsed = parse_run_prune_review({"run_prune_review": encoded})
    assert parsed == review
    assert parsed is not None
    assert parsed.to_json_dict()["schema_version"] == RUN_PRUNE_REVIEW_SCHEMA_VERSION


def test_parse_run_prune_review_rejects_bad_payloads() -> None:
    assert parse_run_prune_review(None) is None
    assert parse_run_prune_review({}) is None
    assert parse_run_prune_review({"run_prune_review": ""}) is None
    assert parse_run_prune_review({"run_prune_review": "not json"}) is None
    assert parse_run_prune_review({"run_prune_review": "[]"}) is None
    assert (
        parse_run_prune_review({"run_prune_review": '{"schema_version": 999}'}) is None
    )
    review = build_review(_plan())
    assert isinstance(review, RunPruneReview)
    tampered = dict(review.to_json_dict())
    tampered.pop("fingerprint")

    assert parse_run_prune_review({"run_prune_review": json.dumps(tampered)}) is None
