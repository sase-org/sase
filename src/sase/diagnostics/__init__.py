"""Shared diagnostics primitives for SASE doctor-style commands."""

from sase.diagnostics.models import (
    CheckStatus,
    DiagnosticCheck,
    DiagnosticReport,
    aggregate_check_status,
    count_check_statuses,
    diagnostic_check_to_dict,
    diagnostic_exit_code,
    diagnostic_report_to_dict,
    redact_string,
    redact_value,
)
from sase.diagnostics.registry import (
    CheckRunner,
    CheckSpec,
    DiagnosticRegistry,
    UnknownCheckSelection,
    run_check_spec_safely,
)
from sase.diagnostics.render import (
    diagnostic_report_to_json,
    render_diagnostic_report,
)

__all__ = [
    "CheckRunner",
    "CheckSpec",
    "CheckStatus",
    "DiagnosticCheck",
    "DiagnosticRegistry",
    "DiagnosticReport",
    "UnknownCheckSelection",
    "aggregate_check_status",
    "count_check_statuses",
    "diagnostic_check_to_dict",
    "diagnostic_exit_code",
    "diagnostic_report_to_dict",
    "diagnostic_report_to_json",
    "redact_string",
    "redact_value",
    "render_diagnostic_report",
    "run_check_spec_safely",
]
