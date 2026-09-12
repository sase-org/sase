"""Post-update shell-completion refresh helpers for ``sase update``."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.completion.install import (
    CompletionRefreshReport,
    RefreshShellOutcome,
    maybe_refresh_installed_completions,
)
from sase.uv_tool.detect import UvToolInstall

COMPLETION_REFRESH_TIMEOUT_SECONDS = 60.0


def completion_refresh_after_update(
    install: UvToolInstall,
    refresh_fn: Callable[[], CompletionRefreshReport] | None,
) -> CompletionRefreshReport:
    if refresh_fn is not None:
        return maybe_refresh_installed_completions(refresh_fn)
    return _refresh_completions_in_child(install)


def _refresh_completions_in_child(
    install: UvToolInstall,
    *,
    timeout: float = COMPLETION_REFRESH_TIMEOUT_SECONDS,
) -> CompletionRefreshReport:
    executable = _tool_sase_executable(install)
    if not executable.is_file():
        return _child_refresh_failure(
            f"completion refresh executable is unavailable: {executable}"
        )
    argv = [str(executable), "completion", "refresh", "--json"]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _child_refresh_failure(
            f"completion refresh timed out after {timeout:.0f}s: {' '.join(argv)}"
        )
    except OSError as exc:
        return _child_refresh_failure(f"completion refresh could not start: {exc}")

    try:
        report = _completion_refresh_report_from_json(
            json.loads(completed.stdout or "{}")
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return _child_refresh_failure(
            _child_refresh_error_detail(
                completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                prefix=f"completion refresh returned malformed JSON: {exc}",
            )
        )
    if completed.returncode != 0 and all(outcome.ok for outcome in report.outcomes):
        return CompletionRefreshReport(
            attempted=True,
            outcomes=(
                *report.outcomes,
                RefreshShellOutcome(
                    shell="*",
                    ok=False,
                    detail=_child_refresh_error_detail(
                        completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        prefix="completion refresh failed",
                    ),
                    target=None,
                ),
            ),
        )
    return report


def _tool_sase_executable(install: UvToolInstall) -> Path:
    filename = "sase.exe" if os.name == "nt" else "sase"
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    return install.sase_dir / scripts_dir / filename


def _completion_refresh_report_from_json(payload: Any) -> CompletionRefreshReport:
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    shells = payload.get("shells")
    if not isinstance(shells, list):
        raise ValueError("payload.shells is not a list")
    outcomes: list[RefreshShellOutcome] = []
    for item in shells:
        if not isinstance(item, dict):
            raise ValueError("payload.shells contains a non-object")
        outcomes.append(
            RefreshShellOutcome(
                shell=str(item["shell"]),
                ok=bool(item["ok"]),
                detail=str(item["detail"]),
                target=None if item.get("target") is None else str(item["target"]),
            )
        )
    return CompletionRefreshReport(
        attempted=bool(payload.get("attempted", True)),
        outcomes=tuple(outcomes),
    )


def _child_refresh_failure(detail: str) -> CompletionRefreshReport:
    return CompletionRefreshReport(
        attempted=True,
        outcomes=(
            RefreshShellOutcome(shell="*", ok=False, detail=detail, target=None),
        ),
    )


def _child_refresh_error_detail(
    returncode: int,
    *,
    stdout: str,
    stderr: str,
    prefix: str,
) -> str:
    detail = f"{prefix} (exit {returncode})"
    stream = (stderr or stdout).strip()
    if stream:
        detail = f"{detail}: {stream}"
    return detail


def render_completion_refresh(
    report: CompletionRefreshReport,
    *,
    console: Console,
    quiet: bool,
) -> None:
    if quiet or not report.attempted:
        return
    if not report.outcomes:
        console.print("Completion refresh: no stamped shells")
        return
    console.print("Refreshing installed shell completions…")
    for outcome in report.outcomes:
        console.print(
            _refresh_outcome_line(outcome), style=_refresh_outcome_style(outcome)
        )


def _refresh_outcome_line(outcome: RefreshShellOutcome) -> str:
    return f"  {outcome.shell}: {outcome.detail}"


def _refresh_outcome_style(outcome: RefreshShellOutcome) -> str:
    return "green" if outcome.ok else "yellow"
