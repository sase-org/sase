"""Artifact-delta queueing for event-driven Agents refreshes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir

from .._event_base import EventHandlersBase
from ..agents._refresh_trace import (
    AgentRefreshFallbackReason,
    record_agents_refresh_trace,
)
from ._artifact_paths import (
    artifact_dir_from_directory_path,
    artifact_dir_from_known_marker_path,
    artifact_path_affects_agents,
)
from ._constants import (
    AGENT_ARTIFACT_DELTA_QUEUE_LIMIT,
    EXPECTED_AGENT_ARTIFACT_DELETION_TTL_SECONDS,
)
from ._helpers import callable_accepts_kwarg
from ._sdd_paths import cached_sdd_beads_dir


class EventArtifactDeltaMixin(EventHandlersBase):
    """Mixin for exact artifact-dir delta refresh state."""

    def _agent_artifact_delta_dir_for_path(
        self, path: Path
    ) -> tuple[Path | None, bool, bool]:
        """Return ``(artifact_dir, affects_agents, deleted_dir)`` for a path."""
        notifications_root = sase_subdir("notifications")
        if notifications_root in (path, *path.parents):
            return None, False, False
        beads_dir = cached_sdd_beads_dir(self)
        if beads_dir in (path, *path.parents):
            return None, False, False
        if path.suffix in {".sase", ".gp"}:
            return None, False, False
        if "artifacts" in path.parts:
            if not artifact_path_affects_agents(path):
                return None, False, False
            marker_dir = artifact_dir_from_known_marker_path(path)
            if marker_dir is not None:
                return marker_dir, True, False
            directory_dir = artifact_dir_from_directory_path(path)
            if directory_dir is None:
                return None, True, False
            deleted_dir = not path.exists()
            return directory_dir, True, deleted_dir
        return None, False, False

    def _agent_artifact_delta_dirs_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> tuple[list[Path], list[Path], AgentRefreshFallbackReason | None]:
        """Classify watcher paths as an exact artifact-dir batch or fallback."""
        if not changed_paths:
            return [], [], "unknown_watcher_path"

        artifact_dirs: list[Path] = []
        deleted_artifact_dirs: list[Path] = []
        unmapped_agents_path = False
        for path in changed_paths:
            artifact_dir, affects_agents, deleted_dir = (
                self._agent_artifact_delta_dir_for_path(path)
            )
            if not affects_agents:
                continue
            if artifact_dir is None:
                unmapped_agents_path = True
                continue
            artifact_dirs.append(artifact_dir)
            if deleted_dir:
                deleted_artifact_dirs.append(artifact_dir)

        if unmapped_agents_path and not artifact_dirs:
            return [], [], "unknown_watcher_path"
        if not artifact_dirs:
            return [], [], None
        return artifact_dirs, deleted_artifact_dirs, None

    def _enqueue_agent_artifact_delta_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> None:
        """Store a bounded, deduped set of exact dirty artifact dirs."""
        if getattr(self, "_dirty_agent_artifact_fallback_reason", None) is not None:
            return

        artifact_dirs, deleted_dirs, fallback_reason = (
            self._agent_artifact_delta_dirs_for_paths(changed_paths)
        )
        if fallback_reason is not None:
            self._dirty_agent_artifact_dirs = ()
            self._dirty_deleted_agent_artifact_dirs = ()
            self._dirty_agent_artifact_fallback_reason = fallback_reason
            return
        if not artifact_dirs:
            return

        queued: list[Path] = list(getattr(self, "_dirty_agent_artifact_dirs", ()))
        queued_deleted: list[Path] = list(
            getattr(self, "_dirty_deleted_agent_artifact_dirs", ())
        )
        seen = {str(path) for path in queued}
        deleted_seen = {str(path) for path in queued_deleted}
        deleted_keys = {str(Path(path).expanduser()) for path in deleted_dirs}
        for artifact_dir in artifact_dirs:
            path = Path(artifact_dir).expanduser()
            key = str(path)
            if key in seen:
                if key in deleted_keys and key not in deleted_seen:
                    queued_deleted.append(path)
                    deleted_seen.add(key)
                continue
            if len(queued) >= AGENT_ARTIFACT_DELTA_QUEUE_LIMIT:
                self._dirty_agent_artifact_dirs = ()
                self._dirty_deleted_agent_artifact_dirs = ()
                self._dirty_agent_artifact_fallback_reason = "dirty_queue_overflow"
                return
            seen.add(key)
            queued.append(path)
            if key in deleted_keys and key not in deleted_seen:
                queued_deleted.append(path)
                deleted_seen.add(key)
        self._dirty_agent_artifact_dirs = tuple(queued)
        self._dirty_deleted_agent_artifact_dirs = tuple(queued_deleted)

    def _clear_agent_artifact_delta_state(self) -> None:
        self._dirty_agent_artifact_dirs = ()
        self._dirty_deleted_agent_artifact_dirs = ()
        self._dirty_agent_artifact_fallback_reason = None

    def _record_agent_artifact_delta_fallback(
        self,
        reason: AgentRefreshFallbackReason,
        *,
        source: str = "auto_refresh",
    ) -> None:
        record_agents_refresh_trace(
            self,
            stage="fallback",
            source=source,
            data_cost="tier1_broad_load",
            fallback_reason=reason,
        )

    def _consume_agent_artifact_delta_refresh(self, *, source: str) -> bool:
        """Schedule the queued exact artifact-dir delta, if available."""
        artifact_dirs = list(getattr(self, "_dirty_agent_artifact_dirs", ()))
        if not artifact_dirs:
            return False
        deleted_artifact_dirs = list(
            getattr(self, "_dirty_deleted_agent_artifact_dirs", ())
        )
        schedule_delta = getattr(self, "_schedule_agent_artifact_delta_refresh", None)
        if not callable(schedule_delta):
            self._dirty_agent_artifact_fallback_reason = "delta_read_failure"
            self._record_agent_artifact_delta_fallback(
                "delta_read_failure",
                source=source,
            )
            return False
        self._clear_agent_artifact_delta_state()
        kwargs: dict[str, Any] = {"source": source}
        if deleted_artifact_dirs and callable_accepts_kwarg(
            schedule_delta, "deleted_artifact_dirs"
        ):
            kwargs["deleted_artifact_dirs"] = deleted_artifact_dirs
        schedule_delta(artifact_dirs, **kwargs)
        return True

    def _register_expected_agent_artifact_deletion(
        self, artifacts_dir: str | Path | None
    ) -> None:
        """Record an artifact dir the TUI cleanup worker is about to delete."""
        if not artifacts_dir:
            return
        registry = getattr(self, "_expected_agent_artifact_deletions", None)
        lock = getattr(self, "_expected_agent_artifact_deletions_lock", None)
        if registry is None or lock is None:
            return

        now = time.monotonic()
        key = str(Path(artifacts_dir).expanduser())
        with lock:
            self._prune_expected_agent_artifact_deletions_locked(now)
            registry[key] = now + EXPECTED_AGENT_ARTIFACT_DELETION_TTL_SECONDS

    def _prune_expected_agent_artifact_deletions_locked(self, now_mono: float) -> None:
        registry = getattr(self, "_expected_agent_artifact_deletions", None)
        if not registry:
            return
        expired = [
            key for key, expires_at in registry.items() if expires_at <= now_mono
        ]
        for key in expired:
            registry.pop(key, None)

    def _registered_self_deletion_key_for_path(self, path: Path) -> str | None:
        registry = getattr(self, "_expected_agent_artifact_deletions", None)
        if not registry:
            return None
        candidate = Path(path).expanduser()
        for key in registry:
            registered = Path(key)
            if candidate == registered or registered in candidate.parents:
                return key
        return None

    def _filter_expected_self_deletion_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> tuple[Path, ...] | None:
        if not changed_paths:
            return changed_paths
        registry = getattr(self, "_expected_agent_artifact_deletions", None)
        lock = getattr(self, "_expected_agent_artifact_deletions_lock", None)
        if registry is None or lock is None:
            return changed_paths

        remaining: list[Path] = []
        consumed: set[str] = set()
        now = time.monotonic()
        with lock:
            self._prune_expected_agent_artifact_deletions_locked(now)
            for path in changed_paths:
                key = self._registered_self_deletion_key_for_path(path)
                if key is None:
                    remaining.append(path)
                    continue
                if Path(path).expanduser() == Path(key):
                    consumed.add(key)
            for key in consumed:
                registry.pop(key, None)
        return tuple(remaining)
