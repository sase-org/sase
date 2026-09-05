"""Shared types and the disk-I/O collector for axe display."""

from __future__ import annotations

import dataclasses
import types
from datetime import datetime
from functools import partial
from typing import Literal

from sase.axe import config as axe_config
from sase.axe.chop_overrun import ChopOverrun, classify_chop_overrun
from sase.axe.chop_script_runner import discover_chop_script
from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    ChopRunEntry,
    LumberjackMetrics,
    LumberjackStatus,
    axe_output_log_path,
    chop_index_path,
    chop_run_log_path,
    chop_run_meta_path,
    lumberjack_log_path,
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
    read_metrics,
    read_output_log_tail,
)
from sase.core.time import get_timezone

from ...bgcmd import (
    BackgroundCommandInfo,
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)
from ...util.trace import trace_event
from ._read_cache import AxeCollectorStats, AxeStatusReadCache

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int

# Lines of run output tail to capture per recorded chop run. Matches the
# 500-line tail used for lumberjack/bgcmd logs so the same bounded reader
# behavior applies on the navigation path.
_CHOP_RUN_TAIL_LINES = 500


@dataclasses.dataclass
class BgCmdSnapshot:
    """Snapshot of a single background command slot."""

    info: BackgroundCommandInfo | None
    running: bool
    output_tail: str


@dataclasses.dataclass
class ChopRunSnapshot:
    """Cached view of a single recorded chop run.

    Pairs the persisted run metadata with the bounded output tail so the
    navigation path can repaint a chop's "Run N/M" view without any
    further disk I/O.
    """

    entry: ChopRunEntry
    output_tail: str


@dataclasses.dataclass
class ChopSnapshot:
    """Cached view of a single configured chop under a lumberjack.

    ``runs`` is newest-first and capped at :data:`MAX_CHOP_RUN_HISTORY`.
    An empty list means no run has been recorded yet for this chop.
    """

    lumberjack_name: str
    chop_name: str
    description: str
    runs: list[ChopRunSnapshot]
    enabled: bool = True
    script: str = ""
    resolved_path: str | None = None
    config_status: Literal["configured", "disabled", "missing"] = "configured"
    generated: bool = False
    base_chop_name: str | None = None
    target_key: str | None = None
    description_summary: str = ""
    description_body: str = ""
    interval_seconds: int | None = None
    interval_source: Literal["runtime", "config"] | None = None
    overrun: ChopOverrun | None = None

    @property
    def base_identity(self) -> tuple[str, str]:
        """Return the immutable config identity edited for this runtime row."""
        return (self.lumberjack_name, self.base_chop_name or self.chop_name)


@dataclasses.dataclass
class LumberjackSnapshot:
    """Cached view of a single lumberjack and its configured chops.

    Bundles per-lumberjack status/metrics/log-tail with per-chop run
    history so the AXE tab can render the lumberjack overview and chop
    detail views from a single in-memory structure.
    """

    name: str
    status: LumberjackStatus | None
    metrics: LumberjackMetrics | None
    log_tail: str
    chops: list[ChopSnapshot]
    description: str = ""
    description_summary: str = ""
    description_body: str = ""
    overrun_chop_count: int = 0
    intermittent_chop_count: int = 0


@dataclasses.dataclass(frozen=True)
class AxeStatusDegradation:
    """A recoverable axe-status collection problem for TUI display."""

    message: str


@dataclasses.dataclass
class AxeCollectedData:
    """Data collected from disk I/O for axe status."""

    axe_running: bool
    axe_status: AxeStatus | None
    axe_metrics: AxeMetrics | None
    axe_output: str
    lumberjack_names: list[str]
    bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    lumberjack_statuses: dict[str, LumberjackStatus | None]
    lumberjack_metrics: dict[str, LumberjackMetrics | None]
    lumberjack_log_tails: dict[str, str]
    bgcmd_details: dict[int, BgCmdSnapshot]
    # Per-lumberjack ordered list of configured chop names. Populated
    # from the axe config so the sidebar can paint chop child rows
    # without re-parsing the config on every render.
    lumberjack_chop_names: dict[str, list[str]]
    # Per-chop snapshot (config metadata + bounded run history with
    # output tails). Keyed by (lumberjack_name, chop_name) so render and
    # targeted-refresh paths can look up a single chop in O(1).
    chop_snapshots: dict[tuple[str, str], ChopSnapshot]
    # Per-lumberjack composite snapshot bundling everything above for
    # any caller that prefers a single per-lumberjack object.
    lumberjack_snapshots: dict[str, LumberjackSnapshot]
    degraded_status: AxeStatusDegradation | None = None
    # False when this payload is a header-only tick (Axe tab not visible
    # and not a sanity reconcile). Apply keeps the previous chop snapshots.
    include_full_snapshots: bool = True
    # Chop keys whose per-run logs were requested this tick.
    tailed_chop_keys: frozenset[tuple[str, str]] = dataclasses.field(
        default_factory=frozenset
    )
    stats: AxeCollectorStats = dataclasses.field(default_factory=AxeCollectorStats)


def _invalid_config_status(
    error: axe_config.AxeConfigError,
) -> AxeStatusDegradation:
    """Render the first config diagnostic as a compact degraded status."""
    diagnostic = (
        error.diagnostics[0].format()
        if error.diagnostics
        else "invalid axe configuration"
    )
    return AxeStatusDegradation(message=f"axe config invalid: {diagnostic}")


def get_axe_process_module() -> types.ModuleType:
    """Return the axe process module."""
    import importlib

    return importlib.import_module("sase.axe.process")


def collect_chop_snapshot(
    lumberjack_name: str,
    chop_name: str,
    description: str = "",
    *,
    description_summary: str = "",
    description_body: str = "",
    enabled: bool = True,
    script: str = "",
    resolved_path: str | None = None,
    config_status: Literal["configured", "disabled", "missing"] = "configured",
    generated: bool = False,
    base_chop_name: str | None = None,
    target_key: str | None = None,
    interval_seconds: int | None = None,
    interval_source: Literal["runtime", "config"] | None = None,
    cache: AxeStatusReadCache | None = None,
    tail_run_logs: bool = True,
) -> ChopSnapshot:
    """Read a chop's bounded run history from disk into a snapshot.

    Returns an empty ``runs`` list when no history has been recorded.
    Run metadata that fails to parse is skipped so a single corrupt file
    cannot break the rest of the cache.

    Run JSON is reused across ticks when ``(path, mtime_ns, size)`` is
    unchanged. Per-run log tails are read only when ``tail_run_logs`` is
    true (or a previous tail is already cached).
    """
    read_cache = cache if cache is not None else AxeStatusReadCache()
    runs: list[ChopRunSnapshot] = []
    run_ids = read_cache.get_or_load_json(
        chop_index_path(lumberjack_name, chop_name),
        lambda: read_chop_run_index(lumberjack_name, chop_name),
        kind="index",
    )
    for run_id in run_ids:
        entry = read_cache.get_or_load_json(
            chop_run_meta_path(lumberjack_name, chop_name, run_id),
            partial(read_chop_run, lumberjack_name, chop_name, run_id),
            kind="run",
        )
        if entry is None:
            continue
        tail = read_cache.get_or_load_tail(
            chop_run_log_path(lumberjack_name, chop_name, run_id),
            partial(
                read_chop_run_log_tail,
                lumberjack_name,
                chop_name,
                run_id,
                _CHOP_RUN_TAIL_LINES,
            ),
            want=tail_run_logs,
        )
        runs.append(ChopRunSnapshot(entry=entry, output_tail=tail))
    overrun: ChopOverrun | None = None
    if enabled and config_status == "configured" and interval_seconds is not None:
        try:
            overrun = classify_chop_overrun(
                now=datetime.now(get_timezone()),
                interval_seconds=interval_seconds,
                runs=[run.entry for run in runs],
            )
        except Exception as exc:
            trace_event(
                "axe.chop_overrun.unavailable",
                lumberjack=lumberjack_name,
                chop=chop_name,
                error_type=type(exc).__name__,
            )
    return ChopSnapshot(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        description=description,
        description_summary=description_summary,
        description_body=description_body,
        runs=runs,
        enabled=enabled,
        script=script,
        resolved_path=resolved_path,
        config_status=config_status,
        generated=generated,
        base_chop_name=base_chop_name,
        target_key=target_key,
        interval_seconds=interval_seconds,
        interval_source=interval_source,
        overrun=overrun,
    )


def _effective_interval(
    status: LumberjackStatus | None,
    config_interval: int,
) -> tuple[int | None, Literal["runtime", "config"] | None]:
    """Return the interval actually used for chop-overrun classification."""
    if status is not None and _positive_int(status.interval):
        return status.interval, "runtime"
    if _positive_int(config_interval):
        return config_interval, "config"
    return None, None


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def collect_axe_status_data(
    *,
    cache: AxeStatusReadCache | None = None,
    include_full_snapshots: bool = True,
    tail_chop_keys: frozenset[tuple[str, str]] | None = None,
) -> AxeCollectedData:
    """Collect axe status data via disk I/O (thread-safe, no app state mutation).

    ``include_full_snapshots`` is the Axe-tab / sanity path: chop run
    history, lumberjack log tails, and axe/bgcmd output. Other tabs pass
    False and receive header fields only (running flag, status, metrics,
    lumberjack/chop names, bgcmd slot info).

    ``tail_chop_keys`` limits per-run log tails to the chops currently
    rendered. None tails every recorded run (tests and sanity reconcile).

    Returns:
        Collected axe status data ready to be applied to the app.
    """
    read_cache = cache if cache is not None else AxeStatusReadCache()
    read_cache.begin_tick()

    proc = get_axe_process_module()
    axe_running = proc.is_axe_running()

    axe_status: AxeStatus | None = None
    axe_metrics: AxeMetrics | None = None
    degraded_status: AxeStatusDegradation | None = None
    if axe_running:
        try:
            status_dict = proc.get_axe_status()
        except axe_config.AxeConfigError as error:
            status_dict = None
            degraded_status = _invalid_config_status(error)
        if status_dict:
            try:
                axe_fields = {f.name for f in dataclasses.fields(AxeStatus)}
                filtered = {k: v for k, v in status_dict.items() if k in axe_fields}
                axe_status = AxeStatus(**filtered)
            except TypeError:
                pass
        axe_metrics = read_metrics()

    if include_full_snapshots:
        axe_output = read_cache.get_or_load_tail(
            axe_output_log_path(),
            lambda: read_output_log_tail(500),
            want=True,
        )
    else:
        axe_output = ""

    # Load lumberjack config so we can iterate configured chops per
    # lumberjack — not just the lumberjack names — and populate the
    # chop run-history cache the navigation path renders from.
    if degraded_status is None:
        try:
            config = axe_config.load_axe_config()
        except axe_config.AxeConfigError as error:
            degraded_status = _invalid_config_status(error)
            config = axe_config.AxeConfig()
    else:
        config = axe_config.AxeConfig()
    lumberjack_names = sorted(config.lumberjacks.keys())

    # Load per-lumberjack status/metrics/log-tail off the event loop so
    # navigation can paint from the cache instead of hitting disk per keypress.
    lumberjack_statuses: dict[str, LumberjackStatus | None] = {}
    lumberjack_metrics: dict[str, LumberjackMetrics | None] = {}
    lumberjack_log_tails: dict[str, str] = {}
    lumberjack_chop_names: dict[str, list[str]] = {}
    chop_snapshots: dict[tuple[str, str], ChopSnapshot] = {}
    lumberjack_snapshots: dict[str, LumberjackSnapshot] = {}
    tailed_chop_keys: frozenset[tuple[str, str]] = frozenset()
    for name in lumberjack_names:
        status = read_lumberjack_status(name)
        metrics = read_lumberjack_metrics(name)
        if include_full_snapshots:
            log_tail = read_cache.get_or_load_tail(
                lumberjack_log_path(name),
                partial(read_lumberjack_log_tail, name, 500),
                want=True,
            )
        else:
            log_tail = ""
        interval_seconds, interval_source = _effective_interval(
            status, config.lumberjacks[name].interval
        )
        lumberjack_statuses[name] = status
        lumberjack_metrics[name] = metrics
        lumberjack_log_tails[name] = log_tail

        # Iterate the configured chops (not the run-directory listing) so
        # newly-added chops with no recorded runs still appear in the UI
        # tree as empty entries rather than missing entries.
        chops_cfg = list(config.lumberjacks[name].chops)
        chop_names: list[str] = []
        chops_for_jack: list[ChopSnapshot] = []
        for chop_cfg in chops_cfg:
            chop_names.append(chop_cfg.name)
            if not include_full_snapshots:
                continue
            script = chop_cfg.script_name
            resolved = (
                discover_chop_script(
                    script, list(getattr(config, "chop_script_dirs", ()))
                )
                if chop_cfg.enabled
                else None
            )
            config_status: Literal["configured", "disabled", "missing"] = (
                "disabled"
                if not chop_cfg.enabled
                else "configured"
                if resolved is not None
                else "missing"
            )
            chop_key = (name, chop_cfg.name)
            snap = collect_chop_snapshot(
                name,
                chop_cfg.name,
                description=chop_cfg.description,
                description_summary=chop_cfg.description_summary,
                description_body=chop_cfg.description_body,
                enabled=chop_cfg.enabled,
                script=script,
                resolved_path=str(resolved) if resolved is not None else None,
                config_status=config_status,
                generated=chop_cfg.parent_name is not None,
                base_chop_name=chop_cfg.parent_name,
                target_key=chop_cfg.target_key or None,
                interval_seconds=interval_seconds,
                interval_source=interval_source,
                cache=read_cache,
                tail_run_logs=(
                    True if tail_chop_keys is None else chop_key in tail_chop_keys
                ),
            )
            chop_snapshots[chop_key] = snap
            chops_for_jack.append(snap)
        overrun_chop_count = sum(
            1
            for snap in chops_for_jack
            if snap.overrun is not None and snap.overrun.level == "over"
        )
        intermittent_chop_count = sum(
            1
            for snap in chops_for_jack
            if snap.overrun is not None and snap.overrun.level == "intermittent"
        )
        lumberjack_chop_names[name] = chop_names
        lumberjack_snapshots[name] = LumberjackSnapshot(
            name=name,
            description=config.lumberjacks[name].description,
            description_summary=config.lumberjacks[name].description_summary,
            description_body=config.lumberjacks[name].description_body,
            status=status,
            metrics=metrics,
            log_tail=log_tail,
            chops=chops_for_jack,
            overrun_chop_count=overrun_chop_count,
            intermittent_chop_count=intermittent_chop_count,
        )

    if include_full_snapshots:
        tailed_chop_keys = (
            frozenset(chop_snapshots)
            if tail_chop_keys is None
            else frozenset(tail_chop_keys)
        )

    # Load bgcmd state
    active_slots = get_active_slots()
    bgcmd_slots: list[tuple[int, BackgroundCommandInfo]] = []
    bgcmd_details: dict[int, BgCmdSnapshot] = {}
    for slot in active_slots:
        info = get_slot_info(slot)
        if info is not None:
            running = is_slot_running(slot)
            if not running and info.finished_at is None:
                mark_slot_finished(slot)
                info = get_slot_info(slot)
            if info is not None:
                bgcmd_slots.append((slot, info))
                bgcmd_details[slot] = BgCmdSnapshot(
                    info=info,
                    running=running,
                    output_tail=(
                        read_slot_output_tail(slot, 500)
                        if include_full_snapshots
                        else ""
                    ),
                )

    stats = read_cache.snapshot_stats()
    trace_event(
        "axe.collect",
        include_full_snapshots=include_full_snapshots,
        run_json_parses=stats.run_json_parses,
        run_index_reads=stats.run_index_reads,
        log_tail_reads=stats.log_tail_reads,
        file_opens=stats.file_opens,
    )
    return AxeCollectedData(
        axe_running=axe_running,
        axe_status=axe_status,
        axe_metrics=axe_metrics,
        axe_output=axe_output,
        lumberjack_names=lumberjack_names,
        bgcmd_slots=bgcmd_slots,
        lumberjack_statuses=lumberjack_statuses,
        lumberjack_metrics=lumberjack_metrics,
        lumberjack_log_tails=lumberjack_log_tails,
        bgcmd_details=bgcmd_details,
        lumberjack_chop_names=lumberjack_chop_names,
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
        degraded_status=degraded_status,
        include_full_snapshots=include_full_snapshots,
        tailed_chop_keys=tailed_chop_keys,
        stats=stats,
    )
