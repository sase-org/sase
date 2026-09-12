"""Compatibility shim for the continuation capture package."""

from __future__ import annotations

from sase.continuation_capture.monitor import (
    persist_monitor_result as _persist_monitor_result,
    persist_monitor_result_best_effort,
    persist_monitor_start_intent,
    persist_monitor_start_intent_best_effort,
)

__all__ = [
    "_persist_monitor_result",
    "persist_monitor_result_best_effort",
    "persist_monitor_start_intent",
    "persist_monitor_start_intent_best_effort",
]
