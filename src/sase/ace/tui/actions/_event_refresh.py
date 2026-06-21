"""Refresh, watcher, and daemon event handlers for the ACE TUI."""

from __future__ import annotations

import time
from collections.abc import Callable
from inspect import Parameter, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import ACTIVE_PLAN_HANDOFF_STATUSES
from sase.core.paths import sase_projects_dir, sase_subdir

from ._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ._event_base import EventHandlersBase
from .agents._notification_utils import request_notification_agents_refresh
from .agents._refresh_trace import (
    AgentRefreshFallbackReason,
    record_agents_refresh_trace,
)

if TYPE_CHECKING:
    from ..models import Agent

# Slow sanity-refresh floor: even when the inotify watcher is active and
# every dirty flag is clear we still reconcile every minute as a safety
# net for missed events (NFS, container bind-mount edge cases, etc.).
FULL_SANITY_REFRESH_SECONDS = 60.0
PROMPT_INPUT_DEFER_SECONDS = 0.25
# Minimum spacing between successive ``_load_agents_async`` calls from the
# auto-refresh tick. The loader is the dominant cost on every refresh, so
# this floor caps the worst case to one load per window regardless of how
# often the dirty flag is re-armed by inotify. Sanity refreshes bypass it.
AGENTS_LOAD_MIN_INTERVAL_SECONDS = 5.0
AGENT_ARTIFACT_DELTA_QUEUE_LIMIT = 64

_AGENTS_RELEVANT_ARTIFACT_MARKERS = frozenset(
    {
        "agent_meta.json",
        "done.json",
        "running.json",
        "waiting.json",
        "pending_question.json",
        "workflow_state.json",
        "plan_path.json",
        "retry_state.json",
    }
)

_LIVE_FILE_REFRESH_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "WAITING INPUT",
        "PLAN",
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)


def _artifact_relative_parts(path: Path) -> tuple[str, ...] | None:
    """Return path components below the first ``artifacts`` segment."""
    try:
        artifacts_idx = path.parts.index("artifacts")
    except ValueError:
        return None
    return path.parts[artifacts_idx + 1 :]


def _is_month_shard(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _is_day_shard(value: str) -> bool:
    return len(value) == 2 and value.isdigit() and 1 <= int(value) <= 31


def _is_artifact_timestamp(value: str) -> bool:
    return len(value) == 14 and value.isdigit()


def _is_sharded_ace_run_dir_path(relative_parts: tuple[str, ...]) -> bool:
    if not relative_parts or relative_parts[0] != "ace-run":
        return False
    if len(relative_parts) == 2:
        return _is_month_shard(relative_parts[1])
    if len(relative_parts) == 3:
        return _is_month_shard(relative_parts[1]) and _is_day_shard(relative_parts[2])
    if len(relative_parts) == 4:
        month, day, timestamp = relative_parts[1:]
        return (
            _is_month_shard(month)
            and _is_day_shard(day)
            and _is_artifact_timestamp(timestamp)
            and timestamp.startswith(f"{month}{day}")
        )
    return False


def _is_prompt_step_marker(path: Path) -> bool:
    name = path.name
    return name.startswith("prompt_step_") and name.endswith(".json")


def _artifact_path_affects_agents(path: Path) -> bool:
    """Return True when an artifact-tree path can change the Agents rows."""
    relative_parts = _artifact_relative_parts(path)
    if relative_parts is None:
        return False
    if not relative_parts:
        return True

    if path.name in _AGENTS_RELEVANT_ARTIFACT_MARKERS:
        return True
    if _is_prompt_step_marker(path):
        return True

    # Watcher callbacks only carry paths, not inotify masks. A shallow,
    # suffixless path is the best signal available for newly-created or
    # deleted agent-root directories such as:
    #   artifacts/<legacy-agent-dir>
    #   artifacts/<workflow>/<timestamp-or-run-dir>
    if len(relative_parts) <= 2 or _is_sharded_ace_run_dir_path(relative_parts):
        try:
            if path.is_dir():
                return True
        except OSError:
            pass
        return path.suffix == ""

    return False


def _artifact_dir_from_known_marker_path(path: Path) -> Path | None:
    """Return the exact artifact dir for loader-visible marker writes."""
    relative_parts = _artifact_relative_parts(path)
    if relative_parts is None or len(relative_parts) < 2:
        return None
    if path.name in _AGENTS_RELEVANT_ARTIFACT_MARKERS:
        return path.parent
    if _is_prompt_step_marker(path):
        return path.parent
    return None


def _agent_has_live_file_panel(agent: Agent) -> bool:
    """Return True when the detail view can live-refresh this row's file panel."""
    if agent.status not in _LIVE_FILE_REFRESH_STATUSES:
        return False
    return not (agent.is_workflow_child and agent.step_type in ("bash", "python"))


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


class EventRefreshMixin(EventHandlersBase):
    """Mixin providing watcher, daemon, and refresh timer callbacks."""

    def _agent_artifact_delta_dir_for_path(
        self, path: Path
    ) -> tuple[Path | None, bool]:
        """Return ``(artifact_dir, affects_agents)`` for one watcher path."""
        notifications_root = sase_subdir("notifications")
        if notifications_root in (path, *path.parents):
            return None, False
        beads_dir = Path.cwd() / "sdd" / "beads"
        if beads_dir in (path, *path.parents):
            return None, False
        if path.suffix in {".sase", ".gp"}:
            return None, False
        if "artifacts" in path.parts:
            if not _artifact_path_affects_agents(path):
                return None, False
            return _artifact_dir_from_known_marker_path(path), True
        projects_root = sase_projects_dir()
        if projects_root in (path, *path.parents):
            return None, True
        return None, True

    def _agent_artifact_delta_dirs_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> tuple[list[Path], AgentRefreshFallbackReason | None]:
        """Classify watcher paths as an exact artifact-dir batch or fallback."""
        if not changed_paths:
            return [], "unknown_watcher_path"

        artifact_dirs: list[Path] = []
        unmapped_agents_path = False
        for path in changed_paths:
            artifact_dir, affects_agents = self._agent_artifact_delta_dir_for_path(path)
            if not affects_agents:
                continue
            if artifact_dir is None:
                unmapped_agents_path = True
                continue
            artifact_dirs.append(artifact_dir)

        if unmapped_agents_path:
            return [], "unknown_watcher_path"
        if not artifact_dirs:
            return [], None
        return artifact_dirs, None

    def _enqueue_agent_artifact_delta_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> None:
        """Store a bounded, deduped set of exact dirty artifact dirs."""
        if getattr(self, "_dirty_agent_artifact_fallback_reason", None) is not None:
            return

        artifact_dirs, fallback_reason = self._agent_artifact_delta_dirs_for_paths(
            changed_paths
        )
        if fallback_reason is not None:
            self._dirty_agent_artifact_dirs = ()
            self._dirty_agent_artifact_fallback_reason = fallback_reason
            return
        if not artifact_dirs:
            return

        queued: list[Path] = list(getattr(self, "_dirty_agent_artifact_dirs", ()))
        seen = {str(path) for path in queued}
        for artifact_dir in artifact_dirs:
            path = Path(artifact_dir).expanduser()
            key = str(path)
            if key in seen:
                continue
            if len(queued) >= AGENT_ARTIFACT_DELTA_QUEUE_LIMIT:
                self._dirty_agent_artifact_dirs = ()
                self._dirty_agent_artifact_fallback_reason = "dirty_queue_overflow"
                return
            seen.add(key)
            queued.append(path)
        self._dirty_agent_artifact_dirs = tuple(queued)

    def _clear_agent_artifact_delta_state(self) -> None:
        self._dirty_agent_artifact_dirs = ()
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
        schedule_delta = getattr(self, "_schedule_agent_artifact_delta_refresh", None)
        if not callable(schedule_delta):
            self._dirty_agent_artifact_fallback_reason = "delta_read_failure"
            self._record_agent_artifact_delta_fallback(
                "delta_read_failure",
                source=source,
            )
            return False
        self._clear_agent_artifact_delta_state()
        schedule_delta(artifact_dirs, source=source)
        return True

    def _on_artifact_change(
        self, changed_paths: tuple[Path, ...] | None = None
    ) -> None:
        """Inotify dispatch: mark dirty surfaces when the user is idle.

        Called on the UI thread by :class:`ArtifactWatcher` after coalescing
        a burst of file-system events.  Defers when the user is mid-burst
        on j/k so any immediate reconcile lands during a pause rather than
        spiking latency in the middle of navigation.

        Agents changes only set ``_dirty_agents``; the tab-switch path,
        auto-refresh gate, debounce floor, and sanity refresh decide when
        the expensive loader actually runs.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            callback = (
                self._on_artifact_change
                if changed_paths is None
                else lambda: self._on_artifact_change(changed_paths)
            )
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                callback,
            )
            return
        targets = self._dirty_surfaces_for_paths(changed_paths)
        if not targets:
            return
        if "changespecs" in targets:
            self._dirty_changespecs = True
        if "agents" in targets:
            self._dirty_agents = True
            self._enqueue_agent_artifact_delta_paths(changed_paths)
        if "axe" in targets:
            self._dirty_axe = True
        if "notifications" in targets:
            self._dirty_notifications = True
        if self._prompt_input_active():
            pending = set(getattr(self, "_artifact_change_deferred_paths", ()))
            pending.update(changed_paths or ())
            self._artifact_change_deferred_paths = tuple(sorted(pending))
            if not self._artifact_change_defer_pending:
                self._artifact_change_defer_pending = True
                self.set_timer(  # type: ignore[attr-defined]
                    PROMPT_INPUT_DEFER_SECONDS,
                    self._on_artifact_change_deferred,
                )
            return
        # ChangeSpec refreshes are cheap enough to keep immediate and already
        # coalesce through their pending/loading guard. Agents reloads are
        # intentionally consumed by the auto-refresh/tab-switch gates above.
        if "changespecs" in targets:
            self._schedule_changespecs_async_refresh()  # type: ignore[attr-defined]

    def _dirty_surfaces_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> set[str]:
        """Map watcher paths to the smallest ACE surface set we can infer."""
        if not changed_paths:
            return {"changespecs", "agents", "axe", "notifications"}

        targets: set[str] = set()
        ignored_artifact_path = False
        projects_root = sase_projects_dir()
        notifications_root = sase_subdir("notifications")
        beads_dir = Path.cwd() / "sdd" / "beads"
        for path in changed_paths:
            parts = path.parts
            if notifications_root in (path, *path.parents):
                targets.add("notifications")
                continue
            if beads_dir in (path, *path.parents):
                targets.add("changespecs")
                continue
            if "artifacts" in parts:
                if _artifact_path_affects_agents(path):
                    targets.add("agents")
                else:
                    ignored_artifact_path = True
                continue
            if path.suffix in {".sase", ".gp"}:
                targets.update({"changespecs", "axe"})
                continue
            if projects_root in (path, *path.parents):
                targets.update({"changespecs", "agents", "axe"})
                continue
            targets.update({"changespecs", "agents", "axe"})
        if targets:
            return targets
        if ignored_artifact_path:
            return set()
        return {"changespecs", "agents", "axe"}

    def _on_artifact_change_deferred(self) -> None:
        """Timer-fired wrapper that clears the dedup flag before reentering.

        Clearing the flag *on entry* means a single fresh defer timer can
        be scheduled if the prompt is still active when ``_on_artifact_change``
        re-runs, while back-to-back watcher events that arrive between
        scheduling and firing collapse into the existing pending timer.
        """
        self._artifact_change_defer_pending = False
        changed_paths = getattr(self, "_artifact_change_deferred_paths", ())
        self._artifact_change_deferred_paths = ()
        self._on_artifact_change(changed_paths or None)

    def _watcher_active(self) -> bool:
        """Return True when the inotify watcher is currently driving refreshes."""
        return getattr(self, "_fs_watcher", None) is not None

    def _refresh_selected_agent_file_panel(self) -> bool:
        """Refresh only the selected agent's file panel when it is safe to do so."""
        if self.current_tab != "agents":
            return False
        if getattr(self, "current_attempt_number", None) is not None:
            return False

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or not _agent_has_live_file_panel(agent):
            return False

        from textual.css.query import NoMatches

        from ..widgets import AgentDetail

        try:
            agent_detail = self.query_one(  # type: ignore[attr-defined]
                "#agent-detail-panel", AgentDetail
            )
        except NoMatches:
            return False

        if getattr(agent_detail, "panel_mode_label", "file") != "file":
            return False

        agent_detail.refresh_current_file(agent)
        return True

    async def _on_auto_refresh(self) -> None:
        """Auto-refresh handler called by timer.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        Phase 7: when the inotify watcher is active each surface's refresh
        is gated on its dirty flag; flags clear after the refresh runs.
        Every ``FULL_SANITY_REFRESH_SECONDS`` we ignore the gate and run
        a full reconcile to recover from any missed events.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._on_auto_refresh)  # type: ignore[attr-defined]
            return

        self._countdown_remaining = self.refresh_interval
        if self._prompt_input_active():
            return

        watcher_active = self._watcher_active()
        now_mono = time.monotonic()
        sanity_due = (
            now_mono - getattr(self, "_last_full_sanity_refresh", 0.0)
            >= FULL_SANITY_REFRESH_SECONDS
        )

        def _should_refresh(flag_name: str) -> bool:
            if not watcher_active or sanity_due:
                return True
            return bool(getattr(self, flag_name, True))

        # Always poll axe status regardless of tab (for STARTING/STOPPING
        # transitions) — but skip the disk poll on idle ticks when the
        # watcher is active and nothing about axe has changed.
        if _should_refresh("_dirty_axe"):
            await self._load_axe_status_async()  # type: ignore[attr-defined]
            self._dirty_axe = False

        queued_agent_artifact_dirs = tuple(
            getattr(self, "_dirty_agent_artifact_dirs", ())
        )
        agent_delta_due = (
            watcher_active
            and bool(queued_agent_artifact_dirs)
            and getattr(self, "_dirty_agent_artifact_fallback_reason", None) is None
        )
        agents_due = _should_refresh("_dirty_agents") or agent_delta_due
        # Tab-gate: when the watcher is the source of truth, only pay
        # for the (expensive) agent load while the user is actually
        # looking at the agents tab. The sanity-floor escape hatch
        # below keeps things converging even if the user lives on a
        # different tab forever and we missed an inotify event.
        if agents_due and not sanity_due and self.current_tab != "agents":
            agents_due = False
        # Debounce: floor the auto-refresh tick to one load per window
        # regardless of how often inotify re-arms ``_dirty_agents``.
        # Leaves the dirty flag set so the next eligible tick retries.
        if agents_due and not sanity_due:
            since_last = now_mono - getattr(self, "_last_agents_load_mono", 0.0)
            if since_last < AGENTS_LOAD_MIN_INTERVAL_SECONDS:
                agents_due = False
        # Notification polling is its own surface so an idle tick (no
        # new notifications) skips the on-disk snapshot read. The
        # gating mirrors the other surfaces: poll on every tick when
        # the watcher is inactive, otherwise wait for inotify to set
        # the dirty flag or the sanity-refresh window to elapse.
        new_agent_notification = False
        if _should_refresh("_dirty_notifications"):
            new_agent_notification = bool(
                await self._poll_agent_completions()  # type: ignore[attr-defined]
            )
            self._dirty_notifications = False

        # Skip changespec/agent refresh if the user is in a transient input
        # mode (hint bar or similar is active).
        if getattr(self, "_hint_mode_active", False):
            return
        if getattr(self, "_entry_jump_mode_active", False):
            return
        if getattr(self, "_accept_mode_active", False):
            return

        # Skip if a background agent load is already in progress
        if self._agents_loading:
            return

        if new_agent_notification and self.current_tab == "agents" and not agents_due:
            request_notification_agents_refresh(self)

        if agents_due:
            fallback_reason = getattr(
                self, "_dirty_agent_artifact_fallback_reason", None
            )
            if (
                watcher_active
                and not sanity_due
                and fallback_reason is None
                and queued_agent_artifact_dirs
                and self._consume_agent_artifact_delta_refresh(source="watcher")
            ):
                self._dirty_agents = False
                self._last_agents_load_mono = time.monotonic()
            else:
                if fallback_reason is not None:
                    self._record_agent_artifact_delta_fallback(
                        fallback_reason,
                        source="auto_refresh",
                    )
                self._agents_loading = True
                try:
                    load_agents_async = self._load_agents_async  # type: ignore[attr-defined]
                    kwargs: dict[str, Any] = {}
                    if _callable_accepts_kwarg(load_agents_async, "source"):
                        kwargs["source"] = "auto_refresh"
                    await load_agents_async(**kwargs)
                finally:
                    self._agents_loading = False
                    self._last_agents_load_mono = time.monotonic()
                    self._clear_agent_artifact_delta_state()
                self._dirty_agents = False
        elif watcher_active and not new_agent_notification:
            self._refresh_selected_agent_file_panel()

        if self.current_tab == "changespecs" and _should_refresh("_dirty_changespecs"):
            await self._reload_and_reposition_async()  # type: ignore[attr-defined]
            self._dirty_changespecs = False

        if sanity_due:
            self._last_full_sanity_refresh = now_mono

        if debug_leaks_enabled():
            log_leak_snapshot(self, source="auto_refresh")

    def action_debug_leak_snapshot(self) -> None:
        """One-shot leak snapshot keybind gated by ``SASE_ACE_DEBUG_LEAKS=1``.

        Logs the snapshot and surfaces the headline counts via the
        Textual notification toast so the snapshot is visible without
        digging through the log file.
        """
        if not debug_leaks_enabled():
            return
        snapshot = log_leak_snapshot(self, source="keybind")
        message = (
            f"artifact_cache={snapshot['artifact_page_cache']} "
            f"watches={snapshot['fs_watcher_watches']} "
            f"dismissed={snapshot['dismissed_agent_objects']} "
            f"agents={snapshot['agents_with_children']} "
            f"tasks={snapshot['pending_asyncio_tasks']} "
            f"fds={snapshot['open_fds']}"
        )
        try:
            self.notify(message, title="leak snapshot", timeout=10)  # type: ignore[attr-defined]
        except Exception:
            pass
