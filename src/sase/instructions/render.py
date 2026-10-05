"""Rich rendering and JSON encoding for ``sase instructions verify``."""

from __future__ import annotations

import json
from typing import Any

from sase.instructions.models import VerifyReport

_COLUMNS = (
    "provider",
    "contract",
    "home",
    "project",
    "directive",
    "native-SASE-full",
    "foreign",
    "helpers",
)


def report_to_json_dict(
    report: VerifyReport, *, include_observations: bool
) -> dict[str, Any]:
    """Return the stable ``-j`` JSON document for *report*."""
    return report.to_json_dict(include_observations=include_observations)


def render_table(report: VerifyReport, *, console: Any | None = None) -> None:
    """Render the scoreboard as a Rich panel and table."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    table = Table(
        "provider",
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


def render_json(report: VerifyReport, *, include_observations: bool) -> str:
    """Return the pretty-printed ``-j`` JSON document."""
    return json.dumps(
        report_to_json_dict(report, include_observations=include_observations),
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
    "render_helper_rows",
    "render_json",
    "render_table",
    "report_to_json_dict",
]
