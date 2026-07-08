"""Deep agent artifact index verification for ``sase doctor``."""

from __future__ import annotations

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    verify_agent_artifact_index,
)
from sase.core.paths import sase_projects_dir
from sase.diagnostics import CheckStatus, DiagnosticCheck


def check_agent_index_verify() -> DiagnosticCheck:
    """Run the full read-only agent artifact index verifier."""
    result = verify_agent_artifact_index(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
    )
    problem_count_values = {
        "stale_rows": result.stale_rows,
        "missing_rows": result.missing_rows,
        "extra_rows": result.extra_rows,
        "corrupt_rows": result.corrupt_rows,
    }
    data = {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "index_path": result.index_path,
        "projects_root": result.projects_root,
        "indexed_rows": result.indexed_rows,
        "source_rows": result.source_rows,
        **problem_count_values,
    }
    problem_counts = {
        key: value for key, value in problem_count_values.items() if value
    }
    status: CheckStatus = "OK" if result.ok else "WARN"
    summary = (
        f"agent artifact index matches {result.source_rows} source row(s)"
        if result.ok
        else f"agent artifact index drift found: {_format_counts(problem_counts)}"
    )
    details = tuple(f"{key}: {value}" for key, value in problem_counts.items())

    return DiagnosticCheck(
        id="state.agent_index_verify",
        group="state",
        status=status,
        title="Agent artifact index verify",
        summary=summary,
        details=details,
        next_steps=("Run `sase agent index gc`.",) if not result.ok else (),
        data=data,
    )


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())
