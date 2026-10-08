"""Rich rendering and JSON encoding for ``sase instructions verify``."""

from __future__ import annotations

import json
from typing import Any

from sase.instructions.models import VerifyReport

_COLUMNS = (
    "provider",
    "manifest",
    "contract",
    "home",
    "project",
    "directive",
    "native-SASE-full",
    "foreign",
    "helpers",
)


def _coverage_block_to_json_dict(block: Any) -> dict[str, Any]:
    """Return the stable ``-c`` top-level ``coverage`` block."""
    rows: list[dict[str, Any]] = []
    errors_total = 0
    for row in block or ():
        rows.append(
            {
                "provider": row.provider,
                "purpose": row.purpose,
                "manifests": row.manifests,
                "sessions": row.sessions,
                "covered": row.covered,
                "uncovered": [
                    {"agent": agent, "session": session}
                    for agent, session in row.uncovered
                ],
                "errors": row.errors,
                "warm_p50_ms": row.warm_p50,
                "warm_p95_ms": row.warm_p95,
                "cold_p50_ms": row.cold_p50,
                "cold_p95_ms": row.cold_p95,
            }
        )
        errors_total += row.errors
    return {"rows": rows, "errors_total": errors_total}


def _section_diff_to_json_dict(diff: Any) -> dict[str, Any] | None:
    """Return the stable per-observation ``section_diff`` document."""
    if diff is None:
        return None
    return {
        "manifest": diff.manifest_path,
        "purpose": diff.purpose,
        "unavailable": diff.unavailable,
        "rows": [
            {
                "id": row.id,
                "layer": row.layer,
                "observed": row.observed,
                "native": row.native,
                "explicit": row.explicit,
            }
            for row in diff.rows
        ],
    }


def _report_to_json_dict(
    report: VerifyReport,
    *,
    include_observations: bool,
    coverage_block: Any | None = None,
    section_diffs: dict[tuple[str, str], Any] | None = None,
) -> dict[str, Any]:
    """Return the stable ``-j`` JSON document for *report*."""
    payload = report.to_json_dict(include_observations=include_observations)
    if coverage_block is not None:
        payload["coverage"] = _coverage_block_to_json_dict(coverage_block)
    if section_diffs:
        observations_json = payload.get("observations")
        if isinstance(observations_json, list):
            for entry in observations_json:
                if not isinstance(entry, dict):
                    continue
                key = (str(entry.get("run")), str(entry.get("session")))
                if key in section_diffs:
                    entry["section_diff"] = _section_diff_to_json_dict(
                        section_diffs[key]
                    )
    return payload


def render_table(report: VerifyReport, *, console: Any | None = None) -> None:
    """Render the scoreboard as a Rich panel and table."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    table = Table(
        "provider",
        "manifest",
        "contract",
        "home",
        "project",
        "directive",
        "native-SASE-full",
        "foreign",
        "helpers",
        title=None,
    )
    for row in report.provider_rows:
        table.add_row(
            row.provider,
            row.coverage,
            row.contract,
            row.home,
            row.project,
            row.directive,
            row.native_full,
            row.foreign,
            row.helpers,
        )
    panel = Panel(
        table,
        title="Instruction delivery (observed)",
        subtitle=f"runs={sum(r.runs for r in report.provider_rows)} "
        f"sessions={sum(r.sessions for r in report.provider_rows)}",
    )
    target = console if console is not None else Console()
    target.print(panel)


def _format_ms(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "—"


def render_coverage(block: Any, *, console: Any | None = None) -> None:
    """Render the ``-c`` per-provider-purpose manifest coverage table."""
    from rich.console import Console
    from rich.table import Table

    table = Table(
        "provider",
        "purpose",
        "manifests",
        "sessions",
        "covered",
        "uncovered",
        "errors",
        "warm p50/p95",
        "cold p50/p95",
        title=None,
    )
    for row in block or ():
        uncovered = ", ".join(f"{agent}/{session}" for agent, session in row.uncovered)
        table.add_row(
            row.provider,
            row.purpose,
            str(row.manifests),
            str(row.sessions),
            str(row.covered),
            uncovered or "—",
            str(row.errors),
            f"{_format_ms(row.warm_p50)}/{_format_ms(row.warm_p95)}",
            f"{_format_ms(row.cold_p50)}/{_format_ms(row.cold_p95)}",
        )
    target = console if console is not None else Console()
    target.print(table)


def render_section_diffs(diffs: list[Any], *, console: Any | None = None) -> None:
    """Render the ``-a`` intended-vs-observed section tables."""
    from rich.console import Console
    from rich.table import Table

    target = console if console is not None else Console()
    for diff in diffs:
        if diff.unavailable and not diff.rows:
            target.print(
                f"{diff.run_name}/{diff.session_id}: "
                "◌ no matching manifest or unverifiable session"
            )
            continue
        manifest = diff.manifest_path or "no matching manifest"
        status = "◌ partial" if diff.unavailable else (diff.purpose or "")
        target.print(f"{diff.run_name}/{diff.session_id}: {manifest} {status}")
        table = Table("id", "layer", "observed", "native", "explicit", title=None)
        for row in diff.rows:
            marker = "◌" if diff.unavailable else str(row.observed)
            table.add_row(
                row.id,
                row.layer,
                marker,
                "◌" if diff.unavailable else str(row.native),
                "◌" if diff.unavailable else str(row.explicit),
            )
        target.print(table)


def render_json(
    report: VerifyReport,
    *,
    include_observations: bool,
    coverage_block: Any | None = None,
    section_diffs: dict[tuple[str, str], Any] | None = None,
) -> str:
    """Return the pretty-printed ``-j`` JSON document."""
    return json.dumps(
        _report_to_json_dict(
            report,
            include_observations=include_observations,
            coverage_block=coverage_block,
            section_diffs=section_diffs,
        ),
        indent=2,
        sort_keys=True,
    )


def render_helper_rows(report: VerifyReport, *, console: Any | None = None) -> None:
    """Render per-helper rows for ``-H``."""
    from rich.console import Console
    from rich.table import Table

    table = Table("provider", "session", "type", "template", "attempts", "accepted")
    for obs in report.observations:
        if not obs.helper_type:
            continue
        table.add_row(
            obs.provider,
            obs.session_id,
            str(obs.helper_type),
            "✓" if obs.has_helper_template else "✗",
            str(obs.final_attempts),
            str(obs.final_accepted),
        )
    target = console if console is not None else Console()
    target.print(table)


__all__ = [
    "_coverage_block_to_json_dict",
    "render_coverage",
    "render_helper_rows",
    "render_json",
    "render_section_diffs",
    "render_table",
    "_report_to_json_dict",
    "_section_diff_to_json_dict",
]
