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
        if "candidate" in w:
            baseline = w.get("baseline") or {}
            comparisons = summarize_report(
                surface=surface,
                workload=w["label"],
                baseline_scenarios=baseline,
                candidate_scenarios=w["candidate"],
                baseline_label="explicit_python",
                candidate_label="default_rust",
            )
            if baseline:
                rendered["baseline"] = baseline
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
    rust_run: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Project the rust-backend git query ops run into summary shape.

    Returns ``surface -> {tool, extra, workloads}`` with each workload
    carrying a ``candidate`` map that ``_write_summary_artifact`` feeds
    straight into ``summarize_report``. Post-Phase-8 there is no
    Python-backend pass to pair against, so ``baseline`` is empty.
    """
    merged: dict[str, dict[str, Any]] = {}
    for surface, rust_payload in rust_run.items():
        merged_workloads: list[dict[str, Any]] = []
        for rust_w in rust_payload.get("workloads", []):
            label = rust_w["label"]
            if "summary" in rust_w:
                merged_workloads.append(
                    {
                        "label": label,
                        "size": rust_w.get("size") or {},
                        "candidate": {surface: rust_w.get("summary", {})},
                    }
                )
            else:
                merged_workloads.append(
                    {
                        "label": label,
                        "size": rust_w.get("size") or {},
                        "candidate": {
                            surface: (rust_w.get("scenarios") or {}).get(surface, {}),
                        },
                    }
                )
        merged[surface] = {
            "tool": rust_payload.get("tool"),
            "extra": {"rust_run_extra": rust_payload.get("extra", {})},
            "workloads": merged_workloads,
        }
    return merged
