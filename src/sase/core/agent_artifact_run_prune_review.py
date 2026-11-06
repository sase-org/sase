"""Review snapshots and notification payloads for ACE-run prune reviews.

Single owner of the prune-review fingerprint, the on-disk snapshot files the
TUI review renders without re-planning, and the compact ``RunPruneReview``
payload carried under ``action_data["run_prune_review"]``.

Snapshots live at ``<sase_home>/artifact_retention/run_prune_snapshots/`` and
are written atomically. The payload carries project **keys**; surfaces resolve
display names when they render.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_run_retention import recent_month_names
from sase.core.agent_artifact_run_retention_models import AceRunRetentionPlan
from sase.core.agent_artifact_run_trash import ReviewedRunSet
from sase.core.paths import sase_home
from sase.core.time import get_timezone


RUN_PRUNE_REVIEW_SCHEMA_VERSION = 1
RUN_PRUNE_SNAPSHOT_SCHEMA_VERSION = 1
RUN_PRUNE_REVIEW_ACTION_DATA_KEY = "run_prune_review"
_MAX_SNAPSHOTS_KEPT = 8
_MAX_UNAVAILABLE_SOURCES_IN_PAYLOAD = 12


def preview_fingerprint(plan: AceRunRetentionPlan) -> str:
    """Stable dedup fingerprint for a retention plan.

    Moved verbatim from the artifact-run-prune chop so existing dedup keys
    stay stable.
    """

    payload = {
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
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _snapshot_dir() -> Path:
    """Return the directory holding run-prune snapshot files."""

    return sase_home() / "artifact_retention" / "run_prune_snapshots"


def _snapshot_path(fingerprint: str) -> Path:
    if len(fingerprint) != 16 or any(
        c not in "0123456789abcdef" for c in fingerprint.lower()
    ):
        raise ValueError(f"invalid run-prune snapshot fingerprint: {fingerprint!r}")
    return _snapshot_dir() / f"{fingerprint.lower()}.json"


@dataclass(frozen=True)
class RunPruneSnapshotItem:
    """One selected run recorded in a snapshot."""

    project: str
    timestamp: str
    artifact_dir: str
    size_bytes: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "timestamp": self.timestamp,
            "artifact_dir": self.artifact_dir,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> RunPruneSnapshotItem:
        project = payload.get("project")
        timestamp = payload.get("timestamp")
        artifact_dir = payload.get("artifact_dir")
        size_bytes = payload.get("size_bytes")
        if (
            not isinstance(project, str)
            or not isinstance(timestamp, str)
            or not isinstance(artifact_dir, str)
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
        ):
            raise ValueError("invalid run-prune snapshot item")
        return cls(
            project=project,
            timestamp=timestamp,
            artifact_dir=artifact_dir,
            size_bytes=size_bytes,
        )


@dataclass(frozen=True)
class RunPruneSnapshot:
    """An immutable prune-review snapshot written by the preview pass."""

    fingerprint: str
    captured_at: str
    keep_recent_months: int
    items: tuple[RunPruneSnapshotItem, ...]
    empty_shard_count: int
    sources_unavailable: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_PRUNE_SNAPSHOT_SCHEMA_VERSION,
            "fingerprint": self.fingerprint,
            "captured_at": self.captured_at,
            "keep_recent_months": self.keep_recent_months,
            "items": [item.to_json_dict() for item in self.items],
            "empty_shard_count": self.empty_shard_count,
            "sources_unavailable": list(self.sources_unavailable),
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> RunPruneSnapshot:
        if not isinstance(payload, Mapping):
            raise ValueError("invalid run-prune snapshot envelope")
        if payload.get("schema_version") != RUN_PRUNE_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unknown run-prune snapshot schema")
        fingerprint = payload.get("fingerprint")
        captured_at = payload.get("captured_at")
        keep_recent_months = payload.get("keep_recent_months")
        items = payload.get("items")
        empty_shard_count = payload.get("empty_shard_count")
        sources_unavailable = payload.get("sources_unavailable")
        if (
            not isinstance(fingerprint, str)
            or not isinstance(captured_at, str)
            or isinstance(keep_recent_months, bool)
            or not isinstance(keep_recent_months, int)
            or not isinstance(items, list)
            or isinstance(empty_shard_count, bool)
            or not isinstance(empty_shard_count, int)
            or not isinstance(sources_unavailable, list)
            or not all(isinstance(s, str) for s in sources_unavailable)
        ):
            raise ValueError("invalid run-prune snapshot envelope")
        try:
            parsed_at = datetime.fromisoformat(captured_at)
        except ValueError as exc:
            raise ValueError("invalid run-prune snapshot captured_at") from exc
        if parsed_at.tzinfo is None:
            raise ValueError("run-prune snapshot captured_at must be aware")
        return cls(
            fingerprint=fingerprint,
            captured_at=captured_at,
            keep_recent_months=keep_recent_months,
            items=tuple(RunPruneSnapshotItem.from_json_dict(i) for i in items),
            empty_shard_count=empty_shard_count,
            sources_unavailable=tuple(sources_unavailable),
        )

    def to_reviewed(self) -> ReviewedRunSet:
        """Return the reviewed dir set the apply intersection consumes."""

        return ReviewedRunSet(
            fingerprint=self.fingerprint,
            dirs=frozenset(
                str(Path(item.artifact_dir).expanduser().resolve(strict=False))
                for item in self.items
            ),
        )


def write_snapshot(
    plan: AceRunRetentionPlan,
    *,
    captured_at: datetime | None = None,
) -> tuple[str, Path]:
    """Write the plan's snapshot atomically and GC old snapshots.

    Returns the fingerprint and path. GC keeps the newest snapshots and never
    deletes the one just written.
    """

    fingerprint = preview_fingerprint(plan)
    moment = captured_at or datetime.now(get_timezone())
    if moment.tzinfo is None:
        raise ValueError("run-prune snapshot captured_at must be aware")
    snapshot = RunPruneSnapshot(
        fingerprint=fingerprint,
        captured_at=moment.isoformat(),
        keep_recent_months=plan.policy.keep_recent_months,
        items=tuple(
            RunPruneSnapshotItem(
                project=item.project,
                timestamp=item.timestamp,
                artifact_dir=item.artifact_dir,
                size_bytes=item.size_bytes,
            )
            for item in plan.selected
        ),
        empty_shard_count=plan.counts.empty_out_of_range_shards,
        sources_unavailable=tuple(plan.sources_unavailable),
    )
    target = _snapshot_path(fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(snapshot.to_json_dict(), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _gc_snapshots(keep=target)
    return fingerprint, target


def _gc_snapshots(*, keep: Path) -> None:
    """Keep the newest snapshots; never delete the one just written."""

    directory = _snapshot_dir()
    try:
        candidates = sorted(directory.glob("*.json"))
    except OSError:
        return
    stamped: list[tuple[str, Path]] = []
    for path in candidates:
        if path == keep:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            captured = payload.get("captured_at") if isinstance(payload, dict) else None
        except (OSError, ValueError):
            continue
        if not isinstance(captured, str):
            continue
        stamped.append((captured, path))
    stamped.sort(key=lambda entry: entry[0], reverse=True)
    for _, path in stamped[_MAX_SNAPSHOTS_KEPT - 1 :]:
        try:
            path.unlink()
        except OSError:
            continue


def load_snapshot(fingerprint: str) -> RunPruneSnapshot | None:
    """Return the snapshot for *fingerprint*, or ``None`` when missing/invalid."""

    try:
        path = _snapshot_path(fingerprint)
    except ValueError:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        snapshot = RunPruneSnapshot.from_json_dict(payload)
    except (ValueError, AttributeError, TypeError):
        return None
    if snapshot.fingerprint.lower() != fingerprint.lower():
        return None
    return snapshot


@dataclass(frozen=True)
class RunPruneProjectAggregate:
    """Per-project rollup carried in the review payload (project keys)."""

    project: str
    runs: int
    bytes: int
    oldest: str
    newest: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "runs": self.runs,
            "bytes": self.bytes,
            "oldest": self.oldest,
            "newest": self.newest,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> RunPruneProjectAggregate:
        project = payload.get("project")
        runs = payload.get("runs")
        size = payload.get("bytes")
        oldest = payload.get("oldest")
        newest = payload.get("newest")
        if (
            not isinstance(project, str)
            or isinstance(runs, bool)
            or not isinstance(runs, int)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not isinstance(oldest, str)
            or not isinstance(newest, str)
        ):
            raise ValueError("invalid run-prune project aggregate")
        return cls(project=project, runs=runs, bytes=size, oldest=oldest, newest=newest)


@dataclass(frozen=True)
class RunPruneReviewCounts:
    """Plan counts carried in the review payload."""

    candidates: int
    selected: int
    protected: int
    empty_shards: int

    def to_json_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "selected": self.selected,
            "protected": self.protected,
            "empty_shards": self.empty_shards,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> RunPruneReviewCounts:
        values: dict[str, int] = {}
        for key in ("candidates", "selected", "protected", "empty_shards"):
            value = payload.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("invalid run-prune review counts")
            values[key] = value
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RunPruneReview:
    """Compact review payload stored under ``action_data``."""

    fingerprint: str
    captured_at: str
    keep_recent_months: int
    first_kept_month: str
    counts: RunPruneReviewCounts
    reclaimable_bytes: int
    projects: tuple[RunPruneProjectAggregate, ...]
    unavailable_sources: tuple[str, ...]
    unavailable_source_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_PRUNE_REVIEW_SCHEMA_VERSION,
            "fingerprint": self.fingerprint,
            "captured_at": self.captured_at,
            "keep_recent_months": self.keep_recent_months,
            "first_kept_month": self.first_kept_month,
            "counts": self.counts.to_json_dict(),
            "reclaimable_bytes": self.reclaimable_bytes,
            "projects": [p.to_json_dict() for p in self.projects],
            "unavailable_sources": list(self.unavailable_sources),
            "unavailable_source_count": self.unavailable_source_count,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> RunPruneReview:
        if not isinstance(payload, Mapping):
            raise ValueError("invalid run-prune review envelope")
        if payload.get("schema_version") != RUN_PRUNE_REVIEW_SCHEMA_VERSION:
            raise ValueError("unknown run-prune review schema")
        fingerprint = payload.get("fingerprint")
        captured_at = payload.get("captured_at")
        keep_recent_months = payload.get("keep_recent_months")
        first_kept_month = payload.get("first_kept_month")
        counts = payload.get("counts")
        reclaimable_bytes = payload.get("reclaimable_bytes")
        projects = payload.get("projects")
        unavailable_sources = payload.get("unavailable_sources")
        unavailable_source_count = payload.get("unavailable_source_count")
        if (
            not isinstance(fingerprint, str)
            or not isinstance(captured_at, str)
            or isinstance(keep_recent_months, bool)
            or not isinstance(keep_recent_months, int)
            or not isinstance(first_kept_month, str)
            or not isinstance(counts, Mapping)
            or isinstance(reclaimable_bytes, bool)
            or not isinstance(reclaimable_bytes, int)
            or not isinstance(projects, list)
            or not isinstance(unavailable_sources, list)
            or not all(isinstance(s, str) for s in unavailable_sources)
            or isinstance(unavailable_source_count, bool)
            or not isinstance(unavailable_source_count, int)
        ):
            raise ValueError("invalid run-prune review envelope")
        return cls(
            fingerprint=fingerprint,
            captured_at=captured_at,
            keep_recent_months=keep_recent_months,
            first_kept_month=first_kept_month,
            counts=RunPruneReviewCounts.from_json_dict(counts),
            reclaimable_bytes=reclaimable_bytes,
            projects=tuple(
                RunPruneProjectAggregate.from_json_dict(p) for p in projects
            ),
            unavailable_sources=tuple(unavailable_sources),
            unavailable_source_count=unavailable_source_count,
        )


def build_review(
    plan: AceRunRetentionPlan,
    *,
    fingerprint: str | None = None,
    captured_at: datetime | None = None,
) -> RunPruneReview:
    """Build the notification payload for a freshly planned preview."""

    moment = captured_at or datetime.now(get_timezone())
    kept_months = recent_month_names(moment, plan.policy.keep_recent_months)
    first_kept = kept_months[0] if kept_months else moment.strftime("%Y%m")
    by_project: dict[str, dict[str, Any]] = {}
    for item in plan.selected:
        rollup = by_project.setdefault(
            item.project,
            {"runs": 0, "bytes": 0, "oldest": item.timestamp, "newest": item.timestamp},
        )
        rollup["runs"] += 1
        rollup["bytes"] += item.size_bytes
        rollup["oldest"] = min(str(rollup["oldest"]), item.timestamp)
        rollup["newest"] = max(str(rollup["newest"]), item.timestamp)
    projects = tuple(
        RunPruneProjectAggregate(
            project=project,
            runs=int(rollup["runs"]),
            bytes=int(rollup["bytes"]),
            oldest=str(rollup["oldest"]),
            newest=str(rollup["newest"]),
        )
        for project, rollup in sorted(
            by_project.items(), key=lambda kv: (-int(kv[1]["bytes"]), kv[0])
        )
    )
    return RunPruneReview(
        fingerprint=fingerprint or preview_fingerprint(plan),
        captured_at=moment.isoformat(),
        keep_recent_months=plan.policy.keep_recent_months,
        first_kept_month=f"{first_kept[:4]}-{first_kept[4:6]}",
        counts=RunPruneReviewCounts(
            candidates=plan.counts.candidates,
            selected=plan.counts.selected,
            protected=plan.counts.protected,
            empty_shards=plan.counts.empty_out_of_range_shards,
        ),
        reclaimable_bytes=plan.reclaimable_bytes,
        projects=projects,
        unavailable_sources=tuple(
            plan.sources_unavailable[:_MAX_UNAVAILABLE_SOURCES_IN_PAYLOAD]
        ),
        unavailable_source_count=len(plan.sources_unavailable),
    )


def encode_run_prune_review(review: RunPruneReview) -> str:
    """Encode a review payload as compact JSON for ``action_data``."""

    return json.dumps(review.to_json_dict(), sort_keys=True, separators=(",", ":"))


def parse_run_prune_review(
    action_data: Mapping[str, str] | None,
) -> RunPruneReview | None:
    """Parse the review payload from notification ``action_data``.

    Returns ``None`` for absent, malformed, or unknown-schema payloads and
    never raises.
    """

    try:
        if not isinstance(action_data, Mapping):
            return None
        raw = action_data.get(RUN_PRUNE_REVIEW_ACTION_DATA_KEY)
        if not isinstance(raw, str) or not raw:
            return None
        payload = json.loads(raw)
        return RunPruneReview.from_json_dict(payload)
    except Exception:
        return None


__all__ = [
    "RUN_PRUNE_REVIEW_ACTION_DATA_KEY",
    "RUN_PRUNE_REVIEW_SCHEMA_VERSION",
    "RUN_PRUNE_SNAPSHOT_SCHEMA_VERSION",
    "RunPruneProjectAggregate",
    "RunPruneReview",
    "RunPruneReviewCounts",
    "RunPruneSnapshot",
    "RunPruneSnapshotItem",
    "build_review",
    "encode_run_prune_review",
    "load_snapshot",
    "parse_run_prune_review",
    "preview_fingerprint",
    "write_snapshot",
]
