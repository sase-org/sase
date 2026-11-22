"""Shared types and base state for the lumberjack split.

``sase.axe.lumberjack`` is a facade; the implementation lives in
:mod:`sase.axe._lumberjack_core`, :mod:`sase.axe._lumberjack_tick`, and
:mod:`sase.axe._lumberjack_chop`. This module holds the pieces more than
one of those implementation modules needs, using public names so no
``_``-prefixed symbol is imported across the new modules.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import schedule
from rich.console import Console

from .check_cycles import CheckCycleRunner
from .chop_runner import ChopRunOutcome
from .chop_script_context import ChopScriptContext
from .chop_stop_signal import ChopStopSignal
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .state import AxeMetrics, LumberjackMetrics
from .tick_context import TickContextWriter

LogCallback = Callable[[str, str | None], None]


@dataclass
class LumberjackChopResult:
    """Result of running a single chop in a thread."""

    chop_name: str
    executed: bool  # True if the chop actually ran (not skipped)
    success: bool
    update_timestamp: bool  # Whether to update run_every timestamp
    log_lines: list[str] = field(default_factory=list)
    error: Exception | None = None
    # Captured ``traceback.format_exc()`` output. Must be recorded inside the
    # ``except`` block — by the time ``_handle_error`` runs we are no longer in
    # the active exception context, so a deferred ``format_exc()`` would
    # produce ``"NoneType: None"``.  When the chop failed without a Python
    # traceback (e.g. a subprocess exited nonzero), set this to a constant
    # placeholder rather than leaving it ``None``.
    traceback: str | None = None
    subprocess_diagnostic: dict[str, object] | None = None
    skip_reason: str | None = None
    no_op: bool = False
    #: Wall seconds spent in the job's dispatch; ``None`` when it never ran.
    duration_seconds: float | None = None


class LumberjackBase:
    """Instance state shared by the lumberjack mixins.

    Exists so the mixins type-check without importing private names from
    each other; the concrete :class:`Lumberjack` is assembled in
    :mod:`sase.axe._lumberjack_core`.
    """

    name: str
    config: LumberjackConfig
    axe_config: AxeConfig
    console: Console
    scheduler: schedule.Scheduler
    _state_dir: Path
    _start_time: datetime
    _running: bool
    _swap_guard: Callable[[], bool] | None
    _swap_hold_logged: bool
    swap_restart_requested: bool
    _stop_signal: ChopStopSignal
    _metrics: LumberjackMetrics
    _axe_metrics: AxeMetrics
    _check_runner: CheckCycleRunner
    _tick_context: TickContextWriter
    _chop_durations: dict[str, float]
    _chop_durations_seeded: bool
    _chop_timestamps: dict[str, datetime]

    def _log(self, message: str, style: str | None = None) -> None: ...

    def _flush_log_to_file(self) -> None: ...

    def _held_for_code_swap(self) -> bool:
        raise NotImplementedError

    def _run_tick(self) -> None: ...

    def _dispatch_order(self, chops: list[ChopConfig]) -> list[ChopConfig]:
        raise NotImplementedError

    def _build_chop_context(
        self, all_patches_file: str, filtered_patches_file: str
    ) -> ChopScriptContext:
        raise NotImplementedError

    def _recover_pending_batches(self) -> list[Any]:
        raise NotImplementedError

    def _run_single_chop(
        self, chop: ChopConfig, context_file: str
    ) -> LumberjackChopResult:
        raise NotImplementedError

    def _outcome_to_result(
        self, chop: ChopConfig, outcome: ChopRunOutcome
    ) -> LumberjackChopResult:
        raise NotImplementedError

    def _append_log_tail(
        self, chop_name: str, run_id: str | None, log_lines: list[str]
    ) -> None: ...

    def _handle_error(
        self,
        job_name: str,
        error: Exception,
        tb: str | None = None,
        subprocess_diagnostic: dict[str, object] | None = None,
    ) -> None: ...

    def _update_status(self) -> None: ...

    def _record_tick_load(
        self,
        *,
        spawns: int,
        skipped: int,
        no_ops: int,
        now: float | None = None,
    ) -> None: ...

    def _update_metrics(self) -> None: ...

    def _first_tick_delay(self) -> float:
        raise NotImplementedError

    def _handle_shutdown(self, _signum: int, _frame: object) -> None: ...
