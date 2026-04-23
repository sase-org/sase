"""Shared types and the disk-I/O collector for axe display."""

from __future__ import annotations

import dataclasses
import types
from typing import Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    LumberjackMetrics,
    LumberjackStatus,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
    read_metrics,
    read_output_log_tail,
)

from ...bgcmd import (
    BackgroundCommandInfo,
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int


def get_axe_process_module() -> types.ModuleType:
    """Return the axe process module."""
    import importlib

    return importlib.import_module("sase.axe.process")


@dataclasses.dataclass
class BgCmdSnapshot:
    """Snapshot of a single background command slot."""

    info: BackgroundCommandInfo | None
    running: bool
    output_tail: str


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


def collect_axe_status_data() -> AxeCollectedData:
    """Collect axe status data via disk I/O (thread-safe, no app state mutation).

    Returns:
        Collected axe status data ready to be applied to the app.
    """
    proc = get_axe_process_module()
    axe_running = proc.is_axe_running()

    axe_status: AxeStatus | None = None
    axe_metrics: AxeMetrics | None = None
    if axe_running:
        status_dict = proc.get_axe_status()
        if status_dict:
            try:
                axe_fields = {f.name for f in dataclasses.fields(AxeStatus)}
                filtered = {k: v for k, v in status_dict.items() if k in axe_fields}
                axe_status = AxeStatus(**filtered)
            except TypeError:
                pass
        axe_metrics = read_metrics()

    axe_output = read_output_log_tail(500)

    # Load lumberjack names from config
    from sase.axe.config import load_axe_config as load_new_axe_config

    config = load_new_axe_config()
    lumberjack_names = sorted(config.lumberjacks.keys())

    # Load per-lumberjack status/metrics/log-tail off the event loop so
    # navigation can paint from the cache instead of hitting disk per keypress.
    lumberjack_statuses: dict[str, LumberjackStatus | None] = {}
    lumberjack_metrics: dict[str, LumberjackMetrics | None] = {}
    lumberjack_log_tails: dict[str, str] = {}
    for name in lumberjack_names:
        lumberjack_statuses[name] = read_lumberjack_status(name)
        lumberjack_metrics[name] = read_lumberjack_metrics(name)
        lumberjack_log_tails[name] = read_lumberjack_log_tail(name, 500)

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
                    output_tail=read_slot_output_tail(slot, 500),
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
    )
