"""Shared records used by the proc action mixins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..proc_observer import ObservedProc

if TYPE_CHECKING:
    from ..durable_submit import DurableSubmitHandle


@dataclass(frozen=True)
class TrackedProcResult[T]:
    """Result returned by durable result decoding or session-local work."""

    success: bool
    message: str
    payload: T | None = None
    error: str | None = None
    collision: bool = False


@dataclass(frozen=True)
class TrackedProcCompletion[T]:
    """UI-thread completion record for a background operation."""

    proc_info: ObservedProc
    success: bool
    message: str
    output: str
    payload: T | None = None
    error: str | None = None
    collision: bool = False


@dataclass(frozen=True)
class SessionWorkerResult[T]:
    proc_id: str
    result: TrackedProcResult[T]
    output: str


@dataclass(frozen=True)
class DurableSubmitWorkerResult:
    placeholder_id: str
    handle: DurableSubmitHandle | None = None
    result: TrackedProcResult[Any] | None = None


@dataclass(frozen=True)
class ProcCallbackConfig:
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None
    reload_on_complete: bool
    notify_on_complete: bool
    on_settled: Callable[[], None] | None = None
    workspace_claim: Mapping[str, Any] | None = None
