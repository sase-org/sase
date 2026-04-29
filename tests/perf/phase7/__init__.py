"""Phase 7 measurement helpers (sase-1e.1).

Common metadata, artifact-naming, and ratio helpers shared by every
Phase 7 measurement (`plans/202604/rust_backend_phase7.md`). Phase 7B/7C
agents call into this package so every artifact under
`plans/202604/perf_artifacts/` carries the same envelope and Phase 7D/7E
can compare them apples-to-apples.

Public API
==========

- :func:`build_metadata` — common envelope (git SHA + dirty flag,
  platform, ``sase_core_rs`` import path/version, default-vs-explicit
  backend, run/warmup counts, workload label, timestamp).
- :func:`artifact_path` — canonical
  ``rust_backend_phase7_<surface>_<backend_or_summary>.json`` naming.
- :func:`compute_speedup` — ratio + speedup + percent-delta from any two
  scenario summaries that share a ``median_ms`` / ``median_us`` key.
- :func:`scenario_median` — extract the median in seconds from a
  scenario summary regardless of whether it is reported in ms or µs.
"""

from __future__ import annotations

from .metadata import (
    BackendChoice,
    PHASE7_ARTIFACT_DIR,
    PHASE7_PHASE_TAG,
    Phase7Metadata,
    artifact_path,
    build_metadata,
)
from .summary import (
    ScenarioComparison,
    compute_speedup,
    scenario_median,
    summarize_report,
)


__all__ = [
    "PHASE7_ARTIFACT_DIR",
    "PHASE7_PHASE_TAG",
    "BackendChoice",
    "Phase7Metadata",
    "ScenarioComparison",
    "artifact_path",
    "build_metadata",
    "compute_speedup",
    "scenario_median",
    "summarize_report",
]
