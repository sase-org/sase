"""Persist unresolved refresh verdicts and skip unchanged evidence lookups."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sase.agents_sync._publication_state_repair_observations_runs import (
    locate_artifact_dirs_for_run,
)
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
    AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
    AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
    AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
    AGENT_RUN_STATE_REASON_UNREADABLE_EVIDENCE,
)

_MARKER_FILENAMES = (
    "agent_meta.json",
    "done.json",
    "waiting.json",
    "pending_question.json",
)
_UNRESOLVED_REASONS = frozenset(
    {
        AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
        AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
        AGENT_RUN_STATE_REASON_UNREADABLE_EVIDENCE,
        AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
        AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
    }
)


@dataclass(frozen=True, slots=True)
class UnresolvedVerdictMemoEntry:
    """Last unresolved verdict and the evidence used to reach it."""

    project: str
    owner: str
    source_run_id: str
    evidence_fingerprint: str
    preflight_fingerprint: str
    verdict: str
    artifact_dirs: tuple[str, ...]
    seen_generation: int
    updated_at_ms: int


def memo_entry_from_json(value: object) -> UnresolvedVerdictMemoEntry | None:
    if not isinstance(value, dict):
        return None
    required_strings = (
        "project",
        "owner",
        "source_run_id",
        "evidence_fingerprint",
        "preflight_fingerprint",
        "verdict",
    )
    if any(not isinstance(value.get(key), str) for key in required_strings):
        return None
    if any(not value[key] for key in ("project", "owner", "source_run_id")):
        return None
    for key in ("evidence_fingerprint", "preflight_fingerprint"):
        if re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            return None
    if value["verdict"] not in _UNRESOLVED_REASONS:
        return None
    artifact_dirs = value.get("artifact_dirs")
    generation = value.get("seen_generation")
    updated = value.get("updated_at_ms")
    if (
        not isinstance(artifact_dirs, list)
        or not all(isinstance(item, str) for item in artifact_dirs)
        or len(artifact_dirs) > 32
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 0
        or not isinstance(updated, int)
        or isinstance(updated, bool)
        or updated < 0
    ):
        return None
    return UnresolvedVerdictMemoEntry(
        project=value["project"],
        owner=value["owner"],
        source_run_id=value["source_run_id"],
        evidence_fingerprint=value["evidence_fingerprint"],
        preflight_fingerprint=value["preflight_fingerprint"],
        verdict=value["verdict"],
        artifact_dirs=tuple(artifact_dirs),
        seen_generation=generation,
        updated_at_ms=updated,
    )


def memo_entry_to_json(entry: UnresolvedVerdictMemoEntry) -> dict[str, Any]:
    return {
        "project": entry.project,
        "owner": entry.owner,
        "source_run_id": entry.source_run_id,
        "evidence_fingerprint": entry.evidence_fingerprint,
        "preflight_fingerprint": entry.preflight_fingerprint,
        "verdict": entry.verdict,
        "artifact_dirs": list(entry.artifact_dirs),
        "seen_generation": entry.seen_generation,
        "updated_at_ms": entry.updated_at_ms,
    }


class AgentStateRefreshVerdictMemo:
    """One project's memo view for a single published-state pass."""

    def __init__(
        self,
        entries: dict[str, UnresolvedVerdictMemoEntry],
        *,
        project: str,
        owner: AgentOwnerIdentity,
        generation: int,
        now_ms: int,
    ) -> None:
        self._entries = entries
        self.project = project
        self.owner_token = f"{owner.username}@{owner.machine_name}"
        self.generation = generation
        self.now_ms = now_ms
        self.unchanged_count = 0

    def _key(self, record: V2RunRecord) -> str:
        return json.dumps(
            [self.project, self.owner_token, record.source_run_id],
            separators=(",", ":"),
        )

    def mark_seen(self, record: V2RunRecord) -> None:
        key = self._key(record)
        entry = self._entries.get(key)
        if entry is not None:
            self._entries[key] = replace(entry, seen_generation=self.generation)

    def should_skip(
        self,
        target: ProjectTarget,
        record: V2RunRecord,
    ) -> bool:
        key = self._key(record)
        entry = self._entries.get(key)
        if entry is None:
            return False
        self.mark_seen(record)
        # The full fingerprint also hashes the dismissed observations returned
        # by the lookup. Its index generation is the cheap preflight identity:
        # unchanged marker stats plus an unchanged index means that result need
        # not be loaded again on this scheduler pass.
        current = _preflight_fingerprint(
            target,
            record,
            entry.artifact_dirs,
        )
        if current != entry.preflight_fingerprint:
            return False
        self.unchanged_count += 1
        return True

    def record_unresolved(
        self,
        target: ProjectTarget,
        record: V2RunRecord,
        owner: AgentOwnerIdentity,
        verdict: str,
        observations: tuple[Any, ...],
    ) -> None:
        if f"{owner.username}@{owner.machine_name}" != self.owner_token:
            return
        artifact_dirs, artifact_error = locate_artifact_dirs_for_run(
            target, record.local_name, record.source_run_id
        )
        if artifact_error is not None:
            self._entries.pop(self._key(record), None)
            return
        project_root = _projects_root()
        artifact_relatives = tuple(
            path.relative_to(project_root).as_posix() for path in artifact_dirs
        )
        preflight = _preflight_fingerprint(
            target,
            record,
            artifact_relatives,
        )
        dismissed_identity = [
            asdict(observation)
            for observation in observations
            if getattr(observation, "source", None) == "dismissed"
        ]
        fingerprint = _digest(
            {
                "preflight": preflight,
                "dismissed_result": dismissed_identity,
            }
        )
        key = self._key(record)
        self._entries[key] = UnresolvedVerdictMemoEntry(
            project=self.project,
            owner=self.owner_token,
            source_run_id=record.source_run_id,
            evidence_fingerprint=fingerprint,
            preflight_fingerprint=preflight,
            verdict=verdict,
            artifact_dirs=artifact_relatives,
            seen_generation=self.generation,
            updated_at_ms=self.now_ms,
        )

    def clear(self, record: V2RunRecord) -> None:
        self._entries.pop(self._key(record), None)

    def prune_completed_pass(self) -> None:
        for key, entry in list(self._entries.items()):
            if (
                entry.project == self.project
                and entry.owner == self.owner_token
                and entry.seen_generation != self.generation
            ):
                del self._entries[key]


def _projects_root() -> Path:
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir().resolve(strict=False)


def _dismissed_root() -> Path:
    from sase.core.dismissed_agents_facade import dismissed_bundles_dir

    return dismissed_bundles_dir().resolve(strict=False)


def _relative_child(root: Path, relative: str) -> Path | None:
    try:
        candidate = (root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_relative_to(root) else None


def _file_signature(path: Path) -> tuple[str, int | None, int | None]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return (str(path), None, None)
    except OSError:
        return (str(path), -1, -1)
    return (str(path), info.st_size, info.st_mtime_ns)


def _index_signature(index_path: Path) -> str:
    return _digest(
        [
            _file_signature(index_path),
            _file_signature(Path(f"{index_path}-wal")),
        ]
    )


def _preflight_fingerprint(
    target: ProjectTarget,
    record: V2RunRecord,
    artifact_relatives: tuple[str, ...],
) -> str:
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    projects_root = _projects_root()
    dismissed_root = _dismissed_root()
    artifact_dirs = [
        path
        for relative in artifact_relatives
        if (path := _relative_child(projects_root, relative)) is not None
    ]
    marker_stats = [
        _file_signature(artifact / filename)
        for artifact in artifact_dirs
        for filename in _MARKER_FILENAMES
    ]
    artifact_index = default_agent_artifact_index_path()
    dismissed_index = dismissed_root / "index.sqlite"
    return _digest(
        {
            "project": target.project_key,
            "source_run_id": record.source_run_id,
            "local_name": record.local_name,
            "published_state": record.state,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "marker_stats": marker_stats,
            "artifact_index": _index_signature(artifact_index),
            "dismissed_index": _index_signature(dismissed_index),
        }
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AgentStateRefreshVerdictMemo",
    "UnresolvedVerdictMemoEntry",
    "memo_entry_from_json",
    "memo_entry_to_json",
]
