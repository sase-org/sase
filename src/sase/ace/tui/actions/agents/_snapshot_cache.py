"""Per-process cache for the agent loader's repeated disk reads.

Phase 5 of plans/202604/tui_perf_overhaul_1.md (bead sase-w.5). The agent
loader is called on every auto-refresh; most of its disk work is for files
that have not changed (attempt_meta.json under ``attempts/<N>/``,
``retry_state.json``, dismissed bundle JSON files). This module memoizes
those reads by ``(path, mtime_ns, size)`` signature so an idle refresh
performs no JSON parsing for unchanged files.

Each cached value is keyed independently by file signature, so the cache
"invalidates per-agent slot" as a side effect: when one agent's
``retry_state.json`` changes, only that agent's slot misses; every other
agent reuses the cached value. Coarse fs_watcher events therefore do not
need to drop the whole snapshot.
"""

from __future__ import annotations

import os
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.llm_provider.retry_config import RetryState

    from ...models import Agent
    from ...models.agent import AttemptRecord


def _stat_signature(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class AgentSnapshotCache:
    """Memoizes the agent loader's per-file JSON reads."""

    def __init__(self) -> None:
        self._attempt_history: dict[
            str, tuple[tuple[tuple[str, int, int], ...], list[AttemptRecord]]
        ] = {}
        self._retry_state: dict[
            str, tuple[tuple[int, int] | None, RetryState | None]
        ] = {}
        self._dismissed_bundles: (
            tuple[tuple[tuple[str, int, int], ...], list[Agent]] | None
        ) = None
        self._lock = Lock()

    def attempt_history_for(self, artifacts_dir: str | None) -> list[AttemptRecord]:
        """Return ``load_attempt_history`` cached by attempt_meta.json sigs."""
        from ...models.agent import load_attempt_history

        if not artifacts_dir:
            return []

        attempts_dir = os.path.join(artifacts_dir, "attempts")
        sig: tuple[tuple[str, int, int], ...]
        try:
            entries = sorted(os.listdir(attempts_dir))
        except OSError:
            sig = ()
        else:
            parts: list[tuple[str, int, int]] = []
            for entry in entries:
                meta = os.path.join(attempts_dir, entry, "attempt_meta.json")
                stat_sig = _stat_signature(meta)
                if stat_sig is None:
                    continue
                parts.append((meta, stat_sig[0], stat_sig[1]))
            sig = tuple(parts)

        with self._lock:
            cached = self._attempt_history.get(artifacts_dir)
            if cached is not None and cached[0] == sig:
                return list(cached[1])

        records = load_attempt_history(artifacts_dir)
        with self._lock:
            self._attempt_history[artifacts_dir] = (sig, records)
        return list(records)

    def retry_state_for(self, artifacts_dir: str) -> RetryState | None:
        """Return ``RetryState.read_from`` cached by retry_state.json sig."""
        from sase.llm_provider.retry_config import RETRY_STATE_FILENAME, RetryState

        path = os.path.join(artifacts_dir, RETRY_STATE_FILENAME)
        sig = _stat_signature(path)

        with self._lock:
            cached = self._retry_state.get(path)
            if cached is not None and cached[0] == sig:
                return cached[1]

        value: RetryState | None
        if sig is None:
            value = None
        else:
            value = RetryState.read_from(artifacts_dir)

        with self._lock:
            self._retry_state[path] = (sig, value)
        return value

    def dismissed_bundles(self) -> list[Agent]:
        """Return ``load_dismissed_bundles()`` cached by bundle-file sigs.

        Defers re-parsing every bundle JSON file when nothing in the
        bundles directory has changed since the previous call.
        """
        from ....dismissed_agents import _DISMISSED_BUNDLES_DIR, load_dismissed_bundles

        bundles_dir = _DISMISSED_BUNDLES_DIR
        sig: tuple[tuple[str, int, int], ...]
        try:
            paths: list[str] = []
            for root, _, files in os.walk(bundles_dir):
                for fname in files:
                    if fname.endswith(".json"):
                        paths.append(os.path.join(root, fname))
            paths.sort()
            parts: list[tuple[str, int, int]] = []
            for p in paths:
                stat_sig = _stat_signature(p)
                if stat_sig is None:
                    continue
                parts.append((p, stat_sig[0], stat_sig[1]))
            sig = tuple(parts)
        except OSError:
            sig = ()

        with self._lock:
            cached = self._dismissed_bundles
            if cached is not None and cached[0] == sig:
                return list(cached[1])

        bundles = load_dismissed_bundles()
        with self._lock:
            self._dismissed_bundles = (sig, bundles)
        return list(bundles)

    def invalidate(self, artifacts_dir: str | None = None) -> None:
        """Drop a per-agent slot, or clear everything when ``artifacts_dir`` is None."""
        with self._lock:
            if artifacts_dir is None:
                self._attempt_history.clear()
                self._retry_state.clear()
                self._dismissed_bundles = None
                return
            self._attempt_history.pop(artifacts_dir, None)
            from sase.llm_provider.retry_config import RETRY_STATE_FILENAME

            self._retry_state.pop(
                os.path.join(artifacts_dir, RETRY_STATE_FILENAME), None
            )

    def invalidate_dismissed_bundles(self) -> None:
        with self._lock:
            self._dismissed_bundles = None


_GLOBAL_CACHE = AgentSnapshotCache()


def get_global_snapshot_cache() -> AgentSnapshotCache:
    return _GLOBAL_CACHE


__all__ = [
    "AgentSnapshotCache",
    "get_global_snapshot_cache",
]
