"""Summary-artifact writer and Git-workloads merger for Phase 7B (sase-1e.2).

Split out of :mod:`tests.perf.phase7.run_phase7b` to keep that module focused
on the CLI driver. The functions here turn per-harness adaptor output into
the on-disk ``rust_backend_phase7_<surface>_summary.json`` artifacts that
Phase 7D/7E consume.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.perf.phase7.metadata import (
    BackendChoice,
    artifact_path,
    build_metadata,
)
from tests.perf.phase7.summary import summarize_report


def _write_summary_artifact(
    *,
    surface: str,
    tool: str,
    workloads: Sequence[Mapping[str, Any]],
    runs: int,
    warmup: int,
    extra: Mapping[str, Any],
    artifact_dir: Path,
) -> Path:
    """Write a ``rust_backend_phase7_<surface>_summary.json`` artifact."""
    workload_label = workloads[0]["label"] if workloads else f"{surface}_no_workloads"
    metadata = build_metadata(
        tool=tool,
        surface=surface,
        workload=workload_label,
        # ``BackendChoice("summary")`` instead of ``BackendChoice.SUMMARY``
        # so static checkers infer ``BackendChoice`` rather than the
        # ``Literal["summary"]`` value type.
        backend=BackendChoice("summary"),
        runs=runs,
        warmup=warmup,
        extra=extra,
    )

    rendered_workloads: list[dict[str, Any]] = []
    for w in workloads:
        rendered: dict[str, Any] = {
            "label": w["label"],
            "size": w.get("size", {}),
        }
        if "baseline" in w and "candidate" in w:
            comparisons = summarize_report(
                surface=surface,
                workload=w["label"],
                baseline_scenarios=w["baseline"],
                candidate_scenarios=w["candidate"],
                baseline_label="explicit_python",
                candidate_label="default_rust",
            )
            rendered["baseline"] = w["baseline"]
            rendered["candidate"] = w["candidate"]
            rendered["comparisons"] = [c.as_dict() for c in comparisons]
            for raw_key in ("raw_python_scenarios", "raw_rust_scenarios"):
                if raw_key in w:
                    rendered[raw_key] = w[raw_key]
        elif "summary" in w:
            # Single-summary workload (one row, one backend per call).
            rendered["summary"] = w["summary"]
            rendered["backend_label"] = w.get("backend_label")
        elif "scenarios" in w:
            rendered["scenarios"] = w["scenarios"]
            rendered["backend_label"] = w.get("backend_label")
        rendered_workloads.append(rendered)

    report = {
        "metadata": metadata.as_dict(),
        "workloads": rendered_workloads,
    }
    out = artifact_path(
        surface=surface,
        backend_or_summary=BackendChoice.SUMMARY,
        artifact_dir=artifact_dir,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    return out


def _merge_git_workloads(
    *,
    python_run: Mapping[str, Mapping[str, Any]],
    rust_run: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Pair python-backend / rust-backend git query ops runs by workload label.

    The Git query ops harness does not flip the backend per scenario, so
    we run it twice and pair the workloads here. Returns
    ``surface -> {tool, extra, workloads}`` with each workload carrying a
    ``baseline`` and ``candidate`` map that ``_write_summary_artifact``
    can feed straight into ``summarize_report``.
    """
    merged: dict[str, dict[str, Any]] = {}
    for surface, py_payload in python_run.items():
        rust_payload = rust_run.get(surface, {"workloads": []})
        py_workloads = {w["label"]: w for w in py_payload["workloads"]}
        rust_workloads = {w["label"]: w for w in rust_payload["workloads"]}

        labels = list(py_workloads.keys())
        for label in rust_workloads:
            if label not in labels:
                labels.append(label)

        merged_workloads: list[dict[str, Any]] = []
        for label in labels:
            py_w = py_workloads.get(label, {})
            rust_w = rust_workloads.get(label, {})
            if "summary" in py_w or "summary" in rust_w:
                # Normalizer workloads — single scenario per backend.
                merged_workloads.append(
                    {
                        "label": label,
                        "size": (py_w.get("size") or rust_w.get("size") or {}),
                        "baseline": {surface: py_w.get("summary", {})},
                        "candidate": {surface: rust_w.get("summary", {})},
                    }
                )
            else:
                merged_workloads.append(
                    {
                        "label": label,
                        "size": (py_w.get("size") or rust_w.get("size") or {}),
                        "baseline": {
                            surface: (py_w.get("scenarios") or {}).get(surface, {}),
                        },
                        "candidate": {
                            surface: (rust_w.get("scenarios") or {}).get(surface, {}),
                        },
                    }
                )
        merged[surface] = {
            "tool": py_payload.get("tool") or rust_payload.get("tool"),
            "extra": {
                "python_run_extra": py_payload.get("extra", {}),
                "rust_run_extra": rust_payload.get("extra", {}),
            },
            "workloads": merged_workloads,
        }
    return merged
