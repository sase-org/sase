"""Per-row artifact-file cache and off-thread discovery for the Agents tab."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

# Hard cap on the per-row artifact-file cache. Each cache key folds in the
# agent identity, status, and marker-file mtime/size so status transitions
# create new keys; without a cap the dict grew unbounded over a session.
ARTIFACT_FILE_PAGE_CACHE_MAX = 256

if TYPE_CHECKING:
    from ...models import Agent


log = logging.getLogger(__name__)


class AgentArtifactFileCacheMixin:
    """Mixin providing artifact-file lookup, caching, and background discovery."""

    _artifact_file_discovery_inflight: dict[tuple[Any, ...], asyncio.Task[Any]]
    _artifact_file_page_cache: OrderedDict[tuple[Any, ...], list[Any]]

    def _ensure_artifact_file_page_cache(
        self,
    ) -> OrderedDict[tuple[Any, ...], list[Any]]:
        """Return (and lazily create) the per-row artifact-file cache."""
        cache: OrderedDict[tuple[Any, ...], list[Any]] | None = getattr(
            self, "_artifact_file_page_cache", None
        )
        if cache is None:
            cache = OrderedDict()
            self._artifact_file_page_cache = cache  # type: ignore[attr-defined]
        return cache

    def _artifact_file_cache_put(
        self,
        cache: OrderedDict[tuple[Any, ...], list[Any]],
        key: tuple[Any, ...],
        value: list[Any],
    ) -> None:
        """Write *value* and evict the oldest entry when the cap is exceeded."""
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > ARTIFACT_FILE_PAGE_CACHE_MAX:
            cache.popitem(last=False)

    def _cached_artifact_files(self, agent: Agent | None) -> list[Any] | None:
        """Probe the artifact-file cache without touching the disk.

        Returns ``None`` on cache miss so the caller can choose whether to
        schedule a background discovery; returns a copy of the cached list on
        hit (which may be empty when the agent has no artifact files).
        """
        if agent is None:
            return None
        identity = getattr(agent, "identity", None)
        if identity is None:
            return None
        cache = getattr(self, "_artifact_file_page_cache", None)
        if cache is None:
            return None
        row_key = self._artifact_file_cache_key(agent, identity)
        cached = cache.get(row_key)
        if cached is None:
            return None
        cache.move_to_end(row_key)
        return list(cached)

    def _list_selected_artifact_files(self, agent: Agent | None) -> list[Any]:
        """Return artifact files for *agent* without UI side effects."""
        if agent is None:
            return []
        cache = self._ensure_artifact_file_page_cache()

        identity = getattr(agent, "identity", None)
        if identity is None:
            artifacts_dir = agent.get_artifacts_dir()
            if artifacts_dir is None:
                return []
            from sase.core.artifact_file_facade import list_artifact_files

            try:
                return list_artifact_files(artifacts_dir)
            except Exception:
                return []

        cached = self._cached_artifact_files(agent)
        if cached is not None:
            return cached
        from ._artifact_file_provider import read_artifact_files_for_tui

        try:
            result = read_artifact_files_for_tui(agent)
        except Exception:
            return []
        page = result.value
        request = getattr(page, "request", None)
        generation = getattr(self, "_artifact_file_selection_generation", None)
        if (
            request is not None
            and generation is not None
            and not generation.accepts(request)
        ):
            return []
        artifact_files = list(page.artifact_files)
        row_key = self._artifact_file_cache_key(agent, identity)
        self._artifact_file_cache_put(cache, row_key, artifact_files)
        self._artifact_file_provider_used_daemon = False  # type: ignore[attr-defined]
        self._artifact_file_provider_snapshot = page.shared_snapshot  # type: ignore[attr-defined]
        return artifact_files

    def _schedule_artifact_file_discovery(self, agent: Agent | None) -> None:
        """Schedule artifact-file discovery for *agent* off the UI thread.

        No-op when discovery for the agent's current cache row is already
        in flight. The continuation populates the artifact-file cache and, if the
        selection is unchanged, refreshes only the footer binding state.
        """
        if agent is None:
            return
        identity = getattr(agent, "identity", None)
        if identity is None:
            return
        row_key = self._artifact_file_cache_key(agent, identity)
        inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
            self, "_artifact_file_discovery_inflight", None
        )
        if inflight is None:
            inflight = {}
            self._artifact_file_discovery_inflight = inflight  # type: ignore[attr-defined]
        if row_key in inflight:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        coro = self._run_artifact_file_discovery(agent, row_key)
        task = loop.create_task(coro)
        inflight[row_key] = task

    async def _run_artifact_file_discovery(
        self,
        agent: Agent,
        row_key: tuple[Any, ...],
    ) -> None:
        """Worker body for off-thread artifact-file discovery."""
        from ._artifact_file_provider import read_artifact_files_for_tui

        try:
            try:
                result = await asyncio.to_thread(read_artifact_files_for_tui, agent)
                artifact_files = list(result.value.artifact_files)
            except Exception:
                log.debug("background artifact-file discovery failed", exc_info=True)
                artifact_files = []
            cache = self._ensure_artifact_file_page_cache()
            self._artifact_file_cache_put(cache, row_key, artifact_files)
            current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if current_agent is None:
                return
            current_identity = getattr(current_agent, "identity", None)
            if current_identity is None:
                return
            current_row_key = self._artifact_file_cache_key(
                current_agent, current_identity
            )
            if current_row_key != row_key:
                return
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                try:
                    refresh_footer()
                except Exception:
                    log.debug("post-discovery footer refresh failed", exc_info=True)
        finally:
            inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
                self, "_artifact_file_discovery_inflight", None
            )
            if inflight is not None:
                inflight.pop(row_key, None)

    def _cancel_pending_artifact_file_discovery(self) -> None:
        """Cancel in-flight artifact-file discovery tasks (shutdown hook)."""
        inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
            self, "_artifact_file_discovery_inflight", None
        )
        if not inflight:
            return
        for task in list(inflight.values()):
            if not task.done():
                task.cancel()
        inflight.clear()

    def _artifact_file_cache_key(
        self,
        agent: Agent,
        identity: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        """Return cache-key state that changes when artifact files can change."""
        artifacts_dir = agent.get_artifacts_dir()
        marker_stats: list[tuple[str, int | None, int | None]] = []
        if artifacts_dir is not None:
            for marker in (
                "done.json",
                "agent_meta.json",
                "plan_path.json",
                os.path.join("markdown_pdfs", "index.json"),
            ):
                marker_path = os.path.join(artifacts_dir, marker)
                try:
                    stat = os.stat(marker_path)
                    marker_stats.append((marker, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    marker_stats.append((marker, None, None))

        return (
            *(str(part) for part in identity),
            getattr(agent, "status", None),
            getattr(agent, "diff_path", None),
            getattr(agent, "response_path", None),
            tuple(getattr(agent, "extra_files", ()) or ()),
            artifacts_dir,
            tuple(marker_stats),
        )
