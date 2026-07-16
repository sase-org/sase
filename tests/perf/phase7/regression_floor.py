"""Baseline loading and anchor evaluation for the Phase 7 floor check."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.perf.phase7.summary import scenario_median


@dataclass(frozen=True)
class _AnchorSpec:
    """One row from the baseline file (immutable input)."""

    anchor_id: str
    surface: str
    workload: str
    scenario: str
    phase7b_python_median_s: float
    phase7b_rust_median_s: float
    must_beat_python: bool
    rationale: str
    rust_slowdown_factor_override: float | None = None
    rust_slowdown_factor_reason: str = ""


@dataclass(frozen=True)
class AnchorResult:
    """Per-anchor outcome of the floor check."""

    spec: _AnchorSpec
    current_rust_median_s: float | None
    current_python_median_s: float | None
    rust_ceiling_s: float
    rust_slowdown_factor_used: float
    confirmation_performed: bool = False
    confirmation_rust_median_s: float | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.spec.anchor_id,
            "surface": self.spec.surface,
            "workload": self.spec.workload,
            "scenario": self.spec.scenario,
            "must_beat_python": self.spec.must_beat_python,
            "phase7b_rust_median_s": self.spec.phase7b_rust_median_s,
            "phase7b_python_median_s": self.spec.phase7b_python_median_s,
            "current_rust_median_s": self.current_rust_median_s,
            "current_python_median_s": self.current_python_median_s,
            "rust_ceiling_s": self.rust_ceiling_s,
            "rust_slowdown_factor_used": self.rust_slowdown_factor_used,
            "confirmation_performed": self.confirmation_performed,
            "confirmation_rust_median_s": self.confirmation_rust_median_s,
            "measurements": {
                "initial_rust_median_s": self.current_rust_median_s,
                "confirmation_rust_median_s": (
                    self.confirmation_rust_median_s
                    if self.confirmation_performed
                    else None
                ),
            },
            "passed": self.passed,
            "failures": list(self.failures),
            "notes": list(self.notes),
        }


def load_baseline(path: Path) -> tuple[float, list[_AnchorSpec], dict[str, Any]]:
    """Read the baseline file and return (slowdown_factor, anchors, raw)."""
    raw = json.loads(path.read_text())
    if raw.get("schema_version") != 1:
        raise ValueError(
            f"Unsupported baseline schema_version "
            f"{raw.get('schema_version')!r} in {path}"
        )
    tolerance = raw["tolerance"]
    factor = float(tolerance["rust_slowdown_factor"])
    raw_overrides = tolerance.get("per_anchor_rust_slowdown_factors", {})
    if not isinstance(raw_overrides, Mapping):
        raise ValueError(
            f"tolerance.per_anchor_rust_slowdown_factors must be an object in {path}"
        )
    anchor_ids = {str(a["id"]) for a in raw["anchors"]}
    unknown_overrides = sorted(set(raw_overrides) - anchor_ids)
    if unknown_overrides:
        raise ValueError(
            "tolerance.per_anchor_rust_slowdown_factors references unknown "
            f"anchor id(s) in {path}: {unknown_overrides}"
        )
    anchors = [
        _AnchorSpec(
            anchor_id=a["id"],
            surface=a["surface"],
            workload=a["workload"],
            scenario=a["scenario"],
            phase7b_python_median_s=float(a["phase7b_python_median_s"]),
            phase7b_rust_median_s=float(a["phase7b_rust_median_s"]),
            must_beat_python=bool(a["must_beat_python"]),
            rationale=str(a.get("rationale", "")),
            rust_slowdown_factor_override=_anchor_slowdown_override(
                raw_overrides, str(a["id"])
            ),
            rust_slowdown_factor_reason=_anchor_slowdown_reason(
                raw_overrides, str(a["id"])
            ),
        )
        for a in raw["anchors"]
    ]
    return factor, anchors, raw


def _anchor_slowdown_override(
    raw_overrides: Mapping[str, Any], anchor_id: str
) -> float | None:
    raw = raw_overrides.get(anchor_id)
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return float(raw["rust_slowdown_factor"])
    return float(raw)


def _anchor_slowdown_reason(raw_overrides: Mapping[str, Any], anchor_id: str) -> str:
    raw = raw_overrides.get(anchor_id)
    if isinstance(raw, Mapping):
        return str(raw.get("comment", ""))
    return ""


def _find_workload(
    payload: Mapping[str, Any] | None, label: str
) -> Mapping[str, Any] | None:
    if not payload:
        return None
    for w in payload.get("workloads", []):
        if w.get("label") == label:
            return w
    return None


def _baseline_scenario_for_anchor(spec: _AnchorSpec) -> str:
    """Return the Python scenario row to compare against this anchor.

    Most anchors use the same backend-neutral scenario name on both sides.
    The persistent query-corpus product row is different: the Rust candidate
    is named for the shipped persistent route, while the comparable Python
    baseline remains the reference batch row exposed as ``facade`` by the
    harness adaptor.
    """
    if (
        spec.surface == "evaluate_query_many"
        and spec.scenario == "persistent_query_keystroke"
    ):
        return "facade"
    return spec.scenario


def _extract_medians(
    *,
    by_surface: Mapping[str, Mapping[str, Any]],
    spec: _AnchorSpec,
) -> tuple[float | None, float | None, list[str]]:
    """Return ``(rust_median_s, python_median_s, notes)`` for one anchor."""
    notes: list[str] = []
    payload = by_surface.get(spec.surface)
    if payload is None:
        notes.append(f"surface {spec.surface!r} not produced by any harness")
        return None, None, notes
    workload = _find_workload(payload, spec.workload)
    if workload is None:
        notes.append(
            f"workload {spec.workload!r} not present in surface {spec.surface!r}"
        )
        return None, None, notes
    baseline = workload.get("baseline") or {}
    candidate = workload.get("candidate") or {}
    baseline_scenario = _baseline_scenario_for_anchor(spec)
    py_summary = baseline.get(baseline_scenario)
    rust_summary = candidate.get(spec.scenario)
    if not py_summary:
        notes.append(
            f"scenario {baseline_scenario!r} missing from baseline (python) summaries"
        )
    if not rust_summary:
        notes.append(
            f"scenario {spec.scenario!r} missing from candidate (rust) summaries"
        )
    py_med = scenario_median(py_summary) if py_summary else None
    rust_med = scenario_median(rust_summary) if rust_summary else None
    return rust_med, py_med, notes


def _check_anchor(
    *,
    spec: _AnchorSpec,
    rust_med: float | None,
    py_med: float | None,
    rust_slowdown_factor: float,
    notes: list[str],
) -> AnchorResult:
    factor_used = spec.rust_slowdown_factor_override or rust_slowdown_factor
    rust_ceiling = spec.phase7b_rust_median_s * factor_used
    failures: list[str] = []
    result_notes = list(notes)
    if spec.rust_slowdown_factor_override is not None:
        reason = (
            f": {spec.rust_slowdown_factor_reason}"
            if spec.rust_slowdown_factor_reason
            else ""
        )
        result_notes.append(
            "absolute floor uses per-anchor rust_slowdown_factor "
            f"{factor_used:.2f}x instead of global {rust_slowdown_factor:.2f}x"
            f"{reason}"
        )

    if rust_med is None:
        failures.append("rust median unavailable (scenario missing or count=0)")
    elif rust_med > rust_ceiling:
        failures.append(
            f"absolute floor: rust median {rust_med * 1e6:.2f}us "
            f"exceeds ceiling {rust_ceiling * 1e6:.2f}us "
            f"(={factor_used:.2f}x phase7b rust median "
            f"{spec.phase7b_rust_median_s * 1e6:.2f}us)"
        )

    if spec.must_beat_python:
        if py_med is None:
            failures.append("must_beat_python: python median unavailable for this run")
        elif rust_med is not None and rust_med >= py_med:
            failures.append(
                f"must_beat_python: rust median {rust_med * 1e6:.2f}us "
                f">= python median {py_med * 1e6:.2f}us"
            )

    return AnchorResult(
        spec=spec,
        current_rust_median_s=rust_med,
        current_python_median_s=py_med,
        rust_ceiling_s=rust_ceiling,
        rust_slowdown_factor_used=factor_used,
        failures=tuple(failures),
        notes=tuple(result_notes),
    )


def _needs_notification_confirmation(result: AnchorResult) -> bool:
    """Return whether *result* is eligible for the one bounded retry."""
    return (
        result.spec.surface == "notification_store"
        and not result.spec.must_beat_python
        and result.current_rust_median_s is not None
        and any(failure.startswith("absolute floor:") for failure in result.failures)
    )


def _apply_notification_confirmation(
    result: AnchorResult,
    *,
    confirmation_rust_med: float | None,
    confirmation_notes: Sequence[str] = (),
) -> AnchorResult:
    """Resolve an initial notification floor failure with one confirmation."""
    if not _needs_notification_confirmation(result):
        raise ValueError(
            f"anchor {result.spec.anchor_id!r} is not eligible for confirmation"
        )

    failures = [
        failure
        for failure in result.failures
        if not failure.startswith("absolute floor:")
    ]
    notes = list(result.notes)
    notes.extend(confirmation_notes)
    initial_us = result.current_rust_median_s * 1e6
    ceiling_us = result.rust_ceiling_s * 1e6
    if confirmation_rust_med is None:
        failures.append(
            "absolute floor confirmation: rust median unavailable "
            "(scenario missing or count=0)"
        )
        notes.append(
            f"initial notification median {initial_us:.2f}us exceeded "
            f"the {ceiling_us:.2f}us ceiling; confirmation was unavailable"
        )
    elif confirmation_rust_med > result.rust_ceiling_s:
        confirmation_us = confirmation_rust_med * 1e6
        failures.append(
            f"absolute floor confirmed: initial rust median {initial_us:.2f}us "
            f"and confirmation {confirmation_us:.2f}us exceed ceiling "
            f"{ceiling_us:.2f}us"
        )
        notes.append(
            "bounded notification confirmation reproduced the absolute-floor regression"
        )
    else:
        confirmation_us = confirmation_rust_med * 1e6
        notes.append(
            f"initial notification median {initial_us:.2f}us exceeded the "
            f"{ceiling_us:.2f}us ceiling; bounded confirmation recovered at "
            f"{confirmation_us:.2f}us"
        )

    return AnchorResult(
        spec=result.spec,
        current_rust_median_s=result.current_rust_median_s,
        current_python_median_s=result.current_python_median_s,
        rust_ceiling_s=result.rust_ceiling_s,
        rust_slowdown_factor_used=result.rust_slowdown_factor_used,
        confirmation_performed=True,
        confirmation_rust_median_s=confirmation_rust_med,
        failures=tuple(failures),
        notes=tuple(notes),
    )
