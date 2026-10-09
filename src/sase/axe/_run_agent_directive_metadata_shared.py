"""Shared helpers for run-agent directive metadata."""

from __future__ import annotations

from sase.core.runner_slots import QUEUE_WEIGHT_ERROR


def invalid_queue_weight_message(source: str, value: object) -> str:
    return f"Invalid queue_weight in {source}: {QUEUE_WEIGHT_ERROR}; got {value!r}."
