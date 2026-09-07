"""Structured timing helpers for agent launch paths."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

log = logging.getLogger(__name__)

_DEFAULT_TIMING_ENV = "SASE_AGENT_LAUNCH_TIMING"
_DEFAULT_SLOW_STAGE_THRESHOLD_SECONDS = 30.0
_TRUTHY = {"1", "true", "yes", "on"}
_ACTIVE_LAUNCH_TIMER: ContextVar[LaunchTimingRecorder | None] = ContextVar(
    "active_launch_timing_recorder",
    default=None,
)


def _timing_info_enabled(
    env_vars: tuple[str, ...] = (_DEFAULT_TIMING_ENV,),
) -> bool:
    return any(os.environ.get(var, "").lower() in _TRUTHY for var in env_vars)


@dataclass
class LaunchTimingRecorder:
    """Collect and log elapsed times for one launch operation.

    Debug logging is always emitted when the logger is configured for it.
    Setting ``SASE_AGENT_LAUNCH_TIMING=1`` promotes the same structured
    records to info-level logs for ad hoc profiling. Callers that want a
    separate profiling switch (for example ``sase bead work``) pass their own
    ``info_env_vars`` so a dedicated env var also promotes the records.
    """

    operation: str
    fields: dict[str, Any] = field(default_factory=dict)
    info_env_vars: tuple[str, ...] = (_DEFAULT_TIMING_ENV,)
    durable: bool = False
    slow_stage_threshold_seconds: float = _DEFAULT_SLOW_STAGE_THRESHOLD_SECONDS
    progress: bool | None = None
    progress_interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        self._start_wall = time.time()
        self._start = time.perf_counter()
        self._stages: list[dict[str, Any]] = []
        self._info_enabled = _timing_info_enabled(self.info_env_vars)
        self._stage_stack: list[tuple[str, int]] = []
        self._stage_counter = 0
        self._last_progress_monotonic = 0.0
        self.fields.setdefault("correlation_id", uuid4().hex)
        self._active_timer_token: Token[LaunchTimingRecorder | None] | None = None

    def __enter__(self) -> LaunchTimingRecorder:
        self._active_timer_token = _ACTIVE_LAUNCH_TIMER.set(self)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        outcome = "error" if exc_type is not None else "ok"
        try:
            self.finish(outcome=outcome)
        finally:
            if self._active_timer_token is not None:
                _ACTIVE_LAUNCH_TIMER.reset(self._active_timer_token)
                self._active_timer_token = None

    @contextmanager
    def stage(self, name: str, **fields: Any) -> Iterator[None]:
        self._stage_counter += 1
        stage_id = self._stage_counter
        parent_stage = self._stage_stack[-1][0] if self._stage_stack else None
        parent_stage_id = self._stage_stack[-1][1] if self._stage_stack else None
        start = time.perf_counter()
        self._stage_stack.append((name, stage_id))
        self._progress(name, fields, force=False)
        try:
            yield
        finally:
            self._stage_stack.pop()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            record = {
                "stage": name,
                "stage_id": stage_id,
                "elapsed_ms": elapsed_ms,
                **fields,
            }
            if parent_stage is not None:
                record["parent_stage"] = parent_stage
                record["parent_stage_id"] = parent_stage_id
            if elapsed_ms >= self.slow_stage_threshold_seconds * 1000.0:
                record["slow_stage"] = True
            self._stages.append(record)
            self._log("stage", record)
            if self.durable:
                self._write_durable_stage(record)
            if record.get("slow_stage"):
                self._warn_slow_stage(record)
            self._progress(name, fields, force=True, completed=True)

    def mark(self, name: str, **fields: Any) -> None:
        self._stage_counter += 1
        record = {
            "stage": name,
            "stage_id": self._stage_counter,
            "elapsed_ms": 0.0,
            **fields,
        }
        if self._stage_stack:
            record["parent_stage"] = self._stage_stack[-1][0]
            record["parent_stage_id"] = self._stage_stack[-1][1]
        self._stages.append(record)
        self._log("stage", record)
        if self.durable:
            self._write_durable_stage(record)

    def add_fields(self, **fields: Any) -> None:
        """Attach stable operation fields discovered after recorder creation."""
        self.fields.update(
            {key: value for key, value in fields.items() if value is not None}
        )

    def finish(self, **fields: Any) -> None:
        if getattr(self, "_finished", False):
            return
        self._finished = True
        total_ms = (time.perf_counter() - self._start) * 1000.0
        record = {
            "total_ms": total_ms,
            "stage_count": len(self._stages),
            "slow_stage_count": sum(
                bool(stage.get("slow_stage")) for stage in self._stages
            ),
            **self.fields,
            **fields,
        }
        self._log("summary", record)
        if self.durable:
            self._write_durable_summary(record)

    def _log(self, event: str, record: dict[str, Any]) -> None:
        payload = {"operation": self.operation, "event": event, **record}
        log.debug("agent_launch_timing %s", payload)
        if self._info_enabled:
            log.info("agent_launch_timing %s", payload)

    def _warn_slow_stage(self, record: dict[str, Any]) -> None:
        try:
            target = (
                self.fields.get("bead_id")
                or self.fields.get("plan_path")
                or self.fields.get("target")
                or "unknown"
            )
            log.warning(
                "slow_launch_stage operation=%s stage=%s elapsed_ms=%.1f target=%s",
                self.operation,
                record["stage"],
                record["elapsed_ms"],
                target,
            )
        except Exception:
            log.debug("slow launch stage warning failed", exc_info=True)

    def _write_durable_stage(self, record: dict[str, Any]) -> None:
        try:
            from sase.logs import log_tui_launch_timing

            log_tui_launch_timing(
                {
                    "ts": time.time(),
                    "event": "launch_timing_stage",
                    "operation": self.operation,
                    **self.fields,
                    **record,
                }
            )
        except Exception:
            log.debug("agent launch timing stage JSONL write failed", exc_info=True)

    def _write_durable_summary(self, record: dict[str, Any]) -> None:
        try:
            from sase.logs import log_tui_launch_timing

            log_tui_launch_timing(
                {
                    "ts": self._start_wall,
                    "event": "launch_timing",
                    "operation": self.operation,
                    **record,
                    "stages": self._stages,
                }
            )
        except Exception:
            log.debug("agent launch timing JSONL write failed", exc_info=True)

    def _progress(
        self,
        stage: str,
        fields: dict[str, Any],
        *,
        force: bool,
        completed: bool = False,
    ) -> None:
        enabled = self.progress if self.progress is not None else self._info_enabled
        if not enabled:
            return
        now = time.monotonic()
        if (
            not force
            and self._last_progress_monotonic
            and now - self._last_progress_monotonic < self.progress_interval_seconds
        ):
            return
        self._last_progress_monotonic = now
        target = (
            self.fields.get("resolved_epic_id")
            or self.fields.get("bead_id")
            or self.fields.get("plan_path")
            or self.fields.get("target")
            or "unknown"
        )
        owner_part = ""
        completed_count = fields.get("completed_owners")
        total_count = fields.get("total_owners")
        if completed_count is not None and total_count is not None:
            owner_part = f" owners={completed_count}/{total_count}"
        state = "completed" if completed else "running"
        print(
            f"launch_timing target={target} stage={stage} {state}{owner_part}",
            file=sys.stderr,
        )


def active_launch_timing_recorder() -> LaunchTimingRecorder | None:
    """Return the recorder bound to the current launch operation, if any."""
    return _ACTIVE_LAUNCH_TIMER.get()
