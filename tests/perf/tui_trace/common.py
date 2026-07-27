"""Shared trace-reading and summary helpers for TUI performance benchmarks."""

from __future__ import annotations

import asyncio
import json
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sase.ace.tui.app import AceApp


async def _wait_for_startup(app: AceApp, pilot: object) -> None:
    """Wait for background startup surfaces before timing follow-up actions."""
    deadline = asyncio.get_running_loop().time() + 20.0
    while not (
        app._mount_state_loads_done
        and app._agents_first_load_done
        and app._axe_first_load_done
    ):
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("ACE benchmark startup did not settle within 20s")
        await pilot.pause()  # type: ignore[attr-defined]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _summarize_spans(
    records: Iterable[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    by_span: dict[str, list[float]] = {}
    for record in records:
        by_span.setdefault(str(record.get("span", "")), []).append(
            float(record.get("duration_ms", 0.0))
        )
    return {
        span: _summarize_values(values) for span, values in by_span.items() if values
    }


def _summarize_jk(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_action: dict[str, list[float]] = {}
    for record in records:
        action = str(record.get("action", ""))
        if not action:
            continue
        by_action.setdefault(action, []).append(float(record.get("paint_ms", 0.0)))
    return {
        action: _summarize_values(values)
        for action, values in by_action.items()
        if values
    }


def _summarize_values(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_idx = max(0, int(round(0.95 * (len(ordered) - 1))))
    return {
        "n": float(len(ordered)),
        "p50_ms": float(statistics.median(ordered)),
        "p95_ms": ordered[p95_idx],
        "max_ms": ordered[-1],
    }
