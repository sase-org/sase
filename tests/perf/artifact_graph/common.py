"""Shared artifact graph benchmark helpers."""

from __future__ import annotations

import importlib
import statistics
from collections.abc import Iterable

from sase.core.artifact_wire import (
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_THOUGHT,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

COMMON_SHOW_KINDS = (
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_THOUGHT,
)


def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def summarize(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(values)
    if not vals:
        return {"count": 0.0}
    return {
        "count": float(len(vals)),
        "min_ms": vals[0],
        "median_ms": statistics.median(vals),
        "p95_ms": percentile(vals, 0.95),
        "max_ms": vals[-1],
    }


def ensure_extension() -> None:
    module = importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_rebuild",
        "artifact_list",
        "artifact_show",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise RuntimeError(f"{RUST_EXTENSION_MODULE_NAME} is missing {missing}")
