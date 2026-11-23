"""Isolated fixture stores and latency helpers for TUI freshness tests.

These helpers drive the real ArtifactWatcher plus EventHandlersMixin routing
on temporary SASE_HOME/project/bead/notification trees. They never mutate
the host's live beads or agent records.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions._startup_watchers import StartupWatchersMixin
from sase.ace.tui.actions.event_refresh._artifact_paths import (
    artifact_watch_path_is_relevant,
)
from sase.ace.tui.actions.event_refresh._constants import (
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
)
from sase.ace.tui.prompt_catalog import PROMPT_SOURCE_DEBOUNCE_S
from sase.ace.tui.util.fs_watcher import (
    DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S,
    ArtifactWatcher,
)
from sase.core.agent_artifact_shards import live_ace_run_shard_names
from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp
from tests.ace.tui._fs_watcher_helpers import wait
from tests.sdd_policy_helpers import set_sdd_policy

__all__ = [
    "AGENTS_LOAD_MIN_INTERVAL_SECONDS",
    "DEFAULT_COALESCE_S",
    "DEFAULT_DISPATCH_DEADLINE_S",
    "FULL_SANITY_REFRESH_SECONDS",
    "FreshnessApp",
    "IsolatedFreshnessHome",
    "LatencySample",
    "PROMPT_INPUT_DEFER_SECONDS",
    "PROMPT_SOURCE_DEBOUNCE_S",
    "arm_live_agent_dir",
    "artifact_watch_path_is_relevant",
    "format_latency_matrix",
    "isolate_freshness_home",
    "percentile",
    "reset_freshness_observations",
    "saw_callback_path",
    "start_artifact_watcher",
    "wait",
    "watcher_watch_paths",
]


@dataclass(frozen=True, slots=True)
class IsolatedFreshnessHome:
    """Temporary SASE_HOME plus the watched fixture directories."""

    root: Path
    sase_home: Path
    project_dir: Path
    artifacts_dir: Path
    agent_dir: Path
    beads_dir: Path
    notifications_dir: Path
    prompt_dir: Path


@dataclass(slots=True)
class LatencySample:
    """One mutation-to-callback-to-visible observation."""

    case: str
    mutation_mono: float
    callback_mono: float | None
    visible_mono: float | None
    cadence_s: float
    activity_gate_s: float = 0.0
    work: dict[str, int] = field(default_factory=dict)

    @property
    def event_to_callback_s(self) -> float | None:
        if self.callback_mono is None:
            return None
        return max(0.0, self.callback_mono - self.mutation_mono)

    @property
    def event_to_visible_s(self) -> float | None:
        if self.visible_mono is None:
            return None
        return max(0.0, self.visible_mono - self.mutation_mono)


def percentile(values: Sequence[float], p: float) -> float:
    """Return the linear-interpolated percentile of *values*."""
    if not values:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def format_latency_matrix(samples: Sequence[LatencySample]) -> str:
    """Render a compact markdown latency matrix grouped by case."""
    grouped: dict[str, list[LatencySample]] = {}
    for sample in samples:
        grouped.setdefault(sample.case, []).append(sample)
    lines = [
        "| Case | n | Cadence | Gate | p50 cb | p95 cb | max cb | p50 vis | p95 vis | max vis |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case, group in grouped.items():
        callbacks = [
            s.event_to_callback_s for s in group if s.event_to_callback_s is not None
        ]
        visibles = [
            s.event_to_visible_s for s in group if s.event_to_visible_s is not None
        ]
        cadence = group[0].cadence_s
        gate = group[0].activity_gate_s

        def _cell(xs: list[float], pct: float | None) -> str:
            if not xs:
                return "—"
            if pct is None:
                return f"{max(xs):.3f}s"
            return f"{percentile(xs, pct):.3f}s"

        lines.append(
            "| "
            + " | ".join(
                [
                    case,
                    str(len(group)),
                    f"{cadence:.2f}s",
                    f"{gate:.2f}s",
                    _cell(callbacks, 50),
                    _cell(callbacks, 95),
                    _cell(callbacks, None),
                    _cell(visibles, 50),
                    _cell(visibles, 95),
                    _cell(visibles, None),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def isolate_freshness_home(
    tmp_path: Path,
    monkeypatch: Any,
) -> IsolatedFreshnessHome:
    """Point SASE_HOME and the local SDD store at *tmp_path* children.

    Pre-creates the live ACE-run month/day shards so startup installs those
    watches, but leaves the 14-digit agent dir uncreated. ArtifactWatcher
    does not walk existing per-agent dirs at start; tests that write into
    the agent tree call :func:`arm_live_agent_dir` after the watcher starts.
    """
    sase_home = tmp_path / "sase_home"
    project_dir = sase_home / "projects" / "demo"
    artifacts_dir = project_dir / "artifacts"
    month, day = live_ace_run_shard_names()
    shard_dir = artifacts_dir / "ace-run" / month / day
    shard_dir.mkdir(parents=True)
    agent_dir = shard_dir / f"{month}{day}120000"
    notifications_dir = sase_home / "notifications"
    notifications_dir.mkdir(parents=True)
    beads_dir = tmp_path / ".sase" / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    prompt_dir = tmp_path / "macros"
    prompt_dir.mkdir()
    (project_dir / "demo.sase").write_text("name: demo\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    set_sdd_policy(monkeypatch, "local")
    return IsolatedFreshnessHome(
        root=tmp_path,
        sase_home=sase_home,
        project_dir=project_dir,
        artifacts_dir=artifacts_dir,
        agent_dir=agent_dir,
        beads_dir=beads_dir,
        notifications_dir=notifications_dir,
        prompt_dir=prompt_dir,
    )


def watcher_watch_paths(watcher: ArtifactWatcher) -> set[Path]:
    """Return the currently installed inotify watch paths."""
    return set(watcher._watch_paths_by_wd.values())  # noqa: SLF001


def saw_callback_path(app: FreshnessApp, path: Path) -> bool:
    """Return whether *path* has appeared in a watcher UI callback."""
    return any(path in paths for paths in app.callback_paths)


def reset_freshness_observations(app: FreshnessApp) -> None:
    """Clear mutation/callback/visible bookkeeping after fixture setup."""
    app.callback_times.clear()
    app.callback_paths.clear()
    app.visible_times.clear()
    app.refresh_calls.clear()
    app.notification_polls.clear()
    app.live_reply_paths.clear()
    app.prompt_rebuilds.clear()
    app.deferred_calls.clear()
    app._dirty_agents = False
    app._dirty_patches = False
    app._dirty_notifications = False
    app._dirty_axe = False
    app._clear_agent_artifact_delta_state()
    stamps = getattr(app, "_surface_refreshed_mono", None)
    if isinstance(stamps, dict):
        stamps.clear()


def arm_live_agent_dir(app: FreshnessApp, home: IsolatedFreshnessHome) -> Path:
    """Create the live agent dir after start and wait until it is watched.

    Production grows watches when a 14-digit agent dir appears under a
    watched shard, and ``ensure_watches`` covers already-live agents. The
    CREATE dispatch is drained so later mutation timestamps stay clean.
    """
    watcher = app._fs_watcher
    assert isinstance(watcher, ArtifactWatcher)
    home.agent_dir.mkdir(parents=True, exist_ok=True)
    if home.agent_dir not in watcher_watch_paths(watcher):
        watcher.ensure_watches([home.agent_dir])
    assert wait(
        lambda: home.agent_dir in watcher_watch_paths(watcher),
        timeout=3.0,
    )
    wait(lambda: bool(app.callback_times), timeout=DEFAULT_DISPATCH_DEADLINE_S)
    time.sleep(DEFAULT_COALESCE_S + 0.05)  # sase-test-wait: drain CREATE dispatch
    reset_freshness_observations(app)
    return home.agent_dir


class FreshnessApp(StartupWatchersMixin, _FakeApp):
    """EventHandlersMixin stand-in that timestamps watcher and apply points."""

    def __init__(self, *, sdd_beads_dir: Path | None = None) -> None:
        super().__init__(watcher_active=False, sdd_beads_dir=sdd_beads_dir)
        self.callback_times: list[float] = []
        self.callback_paths: list[tuple[Path, ...]] = []
        self.visible_times: list[float] = []
        self.notification_polls: list[str] = []
        self.live_reply_paths: list[tuple[Path, ...]] = []
        self.prompt_rebuilds: list[dict[str, object]] = []
        self._prompt_source_watcher = None
        self._prompt_source_watcher_active = False
        self._prompt_source_watched_projects: set[str | None] = set()
        self._prompt_source_watch_growth_in_flight = False
        self._prompt_source_watch_growth_pending = False
        self._prompt_source_debounce_timer = None
        self._prompt_source_debounce_config_dirty = False
        self._prompt_catalog_projects: list[str | None] = []
        self._prompt_catalog_generation = 1
        self.agent_detail._deck_source_panel = lambda: self.agent_detail
        self.agent_detail.on_live_reply_artifact_change = self._on_live_reply

    def call_from_thread(
        self, callback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        callback(*args, **kwargs)

    def query_one(self, selector: str, _widget_type: object = None) -> Any:
        if selector == "#agent-detail-panel":
            return self.agent_detail
        raise LookupError(selector)

    def set_timer(
        self, delay: float, callback: Callable[[], Any], **kwargs: Any
    ) -> Any:
        del kwargs
        self.deferred_calls.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    def _on_artifact_change(
        self, changed_paths: tuple[Path, ...] | None = None
    ) -> None:
        self.callback_times.append(time.monotonic())
        if changed_paths:
            self.callback_paths.append(tuple(Path(path) for path in changed_paths))
        super()._on_artifact_change(changed_paths)

    def _on_prompt_source_change(self, changed_paths: tuple[Any, ...]) -> None:
        self.callback_times.append(time.monotonic())
        super()._on_prompt_source_change(changed_paths)

    def _schedule_notification_poll(self, *, source: str = "notification") -> None:
        self.notification_polls.append(source)
        self.visible_times.append(time.monotonic())
        self.refresh_calls.append(f"notify:{source}")

    def _on_live_reply(self, paths: tuple[Path, ...]) -> None:
        self.live_reply_paths.append(paths)
        self.visible_times.append(time.monotonic())
        self.refresh_calls.append("live_reply")

    def _schedule_patches_async_refresh(self) -> None:
        self.visible_times.append(time.monotonic())
        super()._schedule_patches_async_refresh()

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> None:
        self.visible_times.append(time.monotonic())
        super()._schedule_agent_artifact_delta_refresh(
            artifact_dirs,
            source=source,
            deleted_artifact_dirs=deleted_artifact_dirs,
        )

    def _schedule_prompt_catalog_rebuild(self, **kwargs: object) -> None:
        self.prompt_rebuilds.append(dict(kwargs))
        self.visible_times.append(time.monotonic())
        self.refresh_calls.append("prompt_catalog")

    def last_callback_mono(self) -> float | None:
        return self.callback_times[-1] if self.callback_times else None

    def last_visible_mono(self) -> float | None:
        stamps = getattr(self, "_surface_refreshed_mono", None)
        stamped = max(stamps.values()) if isinstance(stamps, dict) and stamps else None
        recorded = self.visible_times[-1] if self.visible_times else None
        candidates = [value for value in (stamped, recorded) if value is not None]
        return max(candidates) if candidates else None

    def watcher_work(self) -> dict[str, int]:
        watcher = getattr(self, "_fs_watcher", None)
        stats_method = getattr(watcher, "stats", None)
        if not callable(stats_method):
            watcher = getattr(self, "_prompt_source_watcher", None)
            stats_method = getattr(watcher, "stats", None)
        if not callable(stats_method):
            return {}
        return {
            key: int(value)
            for key, value in stats_method().items()
            if isinstance(value, int) and not isinstance(value, bool)
        }


def start_artifact_watcher(
    app: FreshnessApp, home: IsolatedFreshnessHome
) -> ArtifactWatcher:
    """Start the production artifact-watcher path against *home*."""
    app._sdd_beads_dir = home.beads_dir
    app._start_artifact_watcher()
    watcher = app._fs_watcher
    assert isinstance(watcher, ArtifactWatcher)
    return watcher
