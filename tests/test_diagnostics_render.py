"""Tests for shared diagnostics rendering."""

from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

from sase.diagnostics.models import DiagnosticCheck, DiagnosticReport
from sase.diagnostics.render import diagnostic_report_to_json, render_diagnostic_report


def _report() -> DiagnosticReport:
    return DiagnosticReport(
        generated_at="2026-06-09T16:00:00Z",
        cwd="/workspace",
        project="sase",
        sase_home="/home/user/.sase",
        checks=(
            DiagnosticCheck(
                id="runtime.version",
                group="runtime",
                status="OK",
                title="Runtime version",
                summary="runtime inventory loaded",
                details=("host editable install",),
                duration_ms=2,
            ),
            DiagnosticCheck(
                id="runtime.environment",
                group="runtime",
                status="OK",
                title="Runtime environment",
                summary="python version supported",
                details=("python 3.12",),
                duration_ms=3,
            ),
            DiagnosticCheck(
                id="providers.default",
                group="providers",
                status="WARN",
                title="Default provider",
                summary="codex executable was not found",
                next_steps=("install codex or update provider config",),
                details=("PATH=/bin",),
                duration_ms=4,
            ),
            DiagnosticCheck(
                id="ops.telemetry_status",
                group="ops",
                status="SKIP",
                title="Telemetry status",
                summary="telemetry is disabled",
                duration_ms=1,
            ),
        ),
    )


def _render(report: DiagnosticReport, *, verbose: bool = False) -> str:
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=160)
    render_diagnostic_report(report, verbose=verbose, console=console)
    return buf.getvalue()


def test_compact_human_rendering_groups_checks_and_hides_extra_ok_rows() -> None:
    output = _render(_report())

    assert "SASE Doctor WARN" in output
    assert "Runtime" in output
    assert "Providers" in output
    assert "Ops" in output
    assert output.index("Runtime") < output.index("Providers") < output.index("Ops")
    assert "runtime.version" in output
    assert "runtime.environment" not in output
    assert "providers.default" in output
    assert "install codex or update provider config" in output
    assert "ops.telemetry_status" in output
    assert "Summary: OK: 2, WARN: 1, ERROR: 0, SKIP: 1" in output


def test_verbose_human_rendering_includes_all_ok_rows_details_and_durations() -> None:
    output = _render(_report(), verbose=True)

    assert "runtime.environment" in output
    assert "python 3.12" in output
    assert "host editable install" in output
    assert "ms" in output


def test_json_rendering_is_plain_json_without_rich_markup() -> None:
    output = diagnostic_report_to_json(_report())
    payload = json.loads(output)

    assert payload["status"] == "WARN"
    assert payload["counts"] == {"OK": 2, "WARN": 1, "ERROR": 0, "SKIP": 1}
    assert payload["checks"][0]["id"] == "runtime.version"
    assert "\x1b[" not in output
    assert "[green]" not in output
    assert "[yellow]" not in output
