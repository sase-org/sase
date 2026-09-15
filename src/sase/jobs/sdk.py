"""Public SDK facade for authoring axe job scripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any

from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.sdk import (
    CHOP_RESULT_SCHEMA_VERSION,
    ChopArguments,
    ChopInvocation,
    ChopLogger,
    ChopResultBuilder,
    ChopResultStatus,
    ChopSummary,
    emit_summary,
    launch_proposal,
    parse_chop_arguments,
    parse_summary,
    resolve_chop_result_file,
    validate_chop_report,
    write_chop_result,
)

from .report import JobReport, Tone

JOB_RESULT_SCHEMA_VERSION = CHOP_RESULT_SCHEMA_VERSION
JobArguments = ChopArguments
JobInvocation = ChopInvocation
JobLogger = ChopLogger
JobResultBuilder = ChopResultBuilder
JobResultStatus = ChopResultStatus
JobSummary = ChopSummary


def parse_job_arguments(
    argv: Sequence[str] | None = None,
    *,
    description: str | None = None,
) -> JobArguments:
    """Parse the common ``--context`` and verbose arguments for a job."""

    return parse_chop_arguments(argv, description=description, surface="job")


def load_job_invocation(
    argv: Sequence[str] | None = None,
    *,
    description: str | None = None,
) -> JobInvocation:
    """Parse common arguments, load context, and construct the shared logger."""

    from sase.chops.sdk import load_chop_invocation

    return load_chop_invocation(argv, description=description, surface="job")


def resolve_job_result_file(
    context: ChopScriptContext | None = None,
    *,
    required: bool = True,
) -> Path | None:
    """Resolve the runner-provided result file from job or legacy chop env."""

    return resolve_chop_result_file(context, required=required)


def write_job_result(
    result: JobResultBuilder | Mapping[str, Any],
    path: str | PathLike[str] | None = None,
    *,
    context: ChopScriptContext | None = None,
) -> dict[str, Any]:
    """Validate and atomically write a structured job result document."""

    return write_chop_result(result, path, context=context)


validate_job_report = validate_chop_report

__all__ = [
    "JOB_RESULT_SCHEMA_VERSION",
    "JobArguments",
    "JobInvocation",
    "JobLogger",
    "JobReport",
    "JobResultBuilder",
    "JobResultStatus",
    "JobSummary",
    "Tone",
    "emit_summary",
    "launch_proposal",
    "load_job_invocation",
    "parse_job_arguments",
    "parse_summary",
    "resolve_job_result_file",
    "validate_job_report",
    "write_job_result",
]
