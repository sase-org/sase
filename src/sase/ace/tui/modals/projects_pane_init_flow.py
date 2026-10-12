"""Shared sequencing for Projects-tab ``sase init`` check, preview, and apply.

``ProjectsPaneInitActionsMixin`` (``projects_pane_init_actions.py``) is the
pane host adapter. The New Project wizard (``apply-ready``) reuses
:func:`run_project_init` with its own host instead of copying this flow.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from textual.app import SuspendNotSupported

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.session_proc_reporter import SessionProcReporter

from .init_plan_modal import InitPlanDecision, InitPlanModal
from .projects_pane_init import (
    InitScope,
    apply_timeout,
    check_timeout,
    init_cwd,
    parse_init_summary_line,
    parse_project_heading,
)
from .projects_pane_init_diffs import attach_action_diffs
from .projects_pane_init_payload import (
    InitCheckPayload,
    InitCheckPayloadError,
    bounded_output_tail,
    current_init_toast,
    parse_init_check_payload,
    tty_blocked_projects,
)

_DUPLICATE_MESSAGE = "A project initialization is already running."
_INIT_SCOPE = "sase-init"
_COUNT_RE = re.compile(r"^(\d+)\s+(.+)$")
_InitApplyKind = Literal["success", "current", "partial", "failure"]
_APPLY_SEVERITY: dict[_InitApplyKind, str] = {
    "success": "information",
    "current": "information",
    "partial": "warning",
    "failure": "error",
}


@dataclass(frozen=True, slots=True)
class _InitApplyPayload:
    """Outcome of one streaming ``sase init … --yes`` session worker."""

    kind: _InitApplyKind
    message: str
    returncode: int
    summary: str | None = None


class ProjectsInitHost(Protocol):
    """Capabilities the shared init flow needs from its embedding surface."""

    @property
    def app(self) -> Any:
        """Owning app, used for the session-worker submit lookup."""
        ...

    @property
    def is_mounted(self) -> bool:
        """Whether completion effects may still touch the surface."""
        ...

    def push_screen(self, modal: Any, callback: Any) -> None:
        """Open the init preview modal with its dismissal callback."""
        ...

    def notify(self, message: str, **kwargs: Any) -> None:
        """Surface a toast for check, apply, and terminal outcomes."""
        ...

    def get_status(self) -> str:
        """Return the current status line for save and reload checks."""
        ...

    def set_status(self, message: str) -> None:
        """Replace the status line."""
        ...

    def suspend(self) -> Any:
        """Suspend the app for the interactive terminal valve."""
        ...

    def reload_projects(self) -> None:
        """Reload project records after apply or the terminal valve."""
        ...


class ProjectsInitFlowController:
    """Run init check, preview, apply, and the terminal valve for one host."""

    def __init__(self, host: ProjectsInitHost) -> None:
        self._host = host
        self._scopes: dict[str, InitScope] = {}

    def start_init_check(
        self, scope: InitScope, *, project_count: int | None = None
    ) -> None:
        """Submit the ``sase init … --check --json`` session worker."""
        previous = self._host.get_status()
        self._host.set_status(f"Checking initialization for {scope.label}…")
        submit = getattr(self._host.app, "_submit_session_worker", None)
        if not callable(submit):
            self._host.notify(
                "Could not initialize: proc queue unavailable.",
                severity="error",
            )
            self._host.set_status(previous)
            return
        if project_count is None:
            project_count = len(scope.project_names) if not scope.all_projects else 1
        timeout = check_timeout(project_count)
        argv = scope.check_argv()
        cwd = init_cwd()

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[InitCheckPayload]:
            return _run_init_check(
                reporter,
                argv=argv,
                cwd=cwd,
                timeout=timeout,
                label=scope.label,
            )

        submitted = submit(
            "init-check",
            task,
            display_name=f"plan init · {scope.label}",
            cl_name=scope.cl_name,
            dedup_key=f"sase-init-check:{scope.scope_key}",
            exclusive_scopes=(_INIT_SCOPE,),
            duplicate_message=_DUPLICATE_MESSAGE,
            on_complete=self._on_init_check_complete,
        )
        if submitted is None:
            self._host.set_status(_DUPLICATE_MESSAGE)
            return
        self._scopes[submitted.proc_id] = scope

    def _on_init_check_complete(
        self, completion: TrackedProcCompletion[InitCheckPayload]
    ) -> None:
        scope = self._scopes.pop(completion.proc_info.proc_id, None)
        payload = completion.payload
        if not completion.success or payload is None:
            message = completion.error or completion.message
            self._host.set_status(message)
            self._host.notify(message, severity="error")
            return
        if payload.status == "current":
            message = current_init_toast(payload)
            self._host.set_status(message)
            self._host.notify(message, severity="information")
            return
        if scope is None:
            message = "Initialization plan is missing its scope."
            self._host.set_status(message)
            self._host.notify(message, severity="error")
            return
        modal = InitPlanModal(scope, payload)
        self._host.push_screen(
            modal,
            lambda decision: self._on_init_plan_decision(decision, scope, payload),
        )

    def _on_init_plan_decision(
        self,
        decision: InitPlanDecision | None,
        scope: InitScope,
        payload: InitCheckPayload,
    ) -> None:
        if decision is None:
            self._host.set_status("Initialization cancelled")
            return
        if decision.action == "apply":
            self._submit_init_apply(scope, payload)
        elif decision.action == "terminal":
            self._run_init_in_terminal(payload)

    def _run_init_in_terminal(self, payload: InitCheckPayload) -> None:
        blocked = tty_blocked_projects(payload)
        if not blocked:
            return
        terminal_scope = InitScope.for_projects(
            [project.name for project in blocked],
            [project.display_name or project.name for project in blocked],
        )
        argv = terminal_scope.terminal_argv()
        cwd = init_cwd()
        self._host.set_status(
            f"Running `sase init` in terminal for {terminal_scope.label}…"
        )
        try:
            with self._host.suspend():
                subprocess.run(argv, cwd=cwd, check=False)
        except (OSError, SuspendNotSupported) as exc:
            message = f"Could not run `sase init` in terminal: {exc}"
            self._host.set_status(message)
            self._host.notify(message, severity="error")
            return
        message = f"Returned from terminal init for {terminal_scope.label}"
        self._host.set_status(message)
        if not self._host.is_mounted:
            return
        self._host.reload_projects()
        if self._host.get_status() == "Reloaded":
            self._host.set_status(message)

    def _submit_init_apply(self, scope: InitScope, payload: InitCheckPayload) -> None:
        submit = getattr(self._host.app, "_submit_session_worker", None)
        if not callable(submit):
            self._host.notify(
                "Could not initialize: proc queue unavailable.",
                severity="error",
            )
            return
        self._host.set_status(f"Initializing {scope.label}…")
        argv = scope.apply_argv()
        cwd = init_cwd()
        timeout = apply_timeout(len(payload.projects))
        total = max(len(payload.projects), 1)

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[_InitApplyPayload]:
            return _run_init_apply(
                reporter,
                argv=argv,
                cwd=cwd,
                timeout=timeout,
                label=scope.label,
                total=total,
            )

        submitted = submit(
            "init-apply",
            task,
            display_name=f"init · {scope.label}",
            cl_name=scope.cl_name,
            dedup_key=f"sase-init:{scope.scope_key}",
            exclusive_scopes=(_INIT_SCOPE,),
            duplicate_message=_DUPLICATE_MESSAGE,
            on_complete=self._on_init_apply_complete,
        )
        if submitted is None:
            self._host.set_status(_DUPLICATE_MESSAGE)
            return
        self._scopes[submitted.proc_id] = scope

    def _on_init_apply_complete(
        self, completion: TrackedProcCompletion[_InitApplyPayload]
    ) -> None:
        self._scopes.pop(completion.proc_info.proc_id, None)
        payload = completion.payload
        if payload is not None:
            message = payload.message
            severity = _APPLY_SEVERITY[payload.kind]
        else:
            message = completion.error or completion.message
            severity = "error"
        self._host.notify(message, severity=severity)
        if not self._host.is_mounted:
            return
        self._host.reload_projects()
        if self._host.get_status() == "Reloaded":
            self._host.set_status(message)


def run_project_init(
    host: ProjectsInitHost, scope: InitScope
) -> ProjectsInitFlowController:
    """Start the shared init flow for one project scope on another host.

    The wizard calls this with ``InitScope.for_projects([key])`` after a
    successful durable add; the returned controller owns the in-flight scopes
    until its completion callbacks release them.
    """
    flow = ProjectsInitFlowController(host)
    flow.start_init_check(scope)
    return flow


def _run_init_check(
    reporter: SessionProcReporter,
    *,
    argv: list[str],
    cwd: str | Path | None,
    timeout: float,
    label: str,
) -> TrackedProcResult[InitCheckPayload]:
    reporter.phase(f"Planning {label}")
    try:
        completed = reporter.run(
            argv,
            cwd=cwd,
            timeout=timeout,
            log_lines=False,
            retain="full",
        )
    except subprocess.TimeoutExpired:
        message = f"Initialization check timed out after {timeout:.0f}s"
        return TrackedProcResult(success=False, message=message, error=message)
    except FileNotFoundError as exc:
        message = "Could not run `sase`: binary not found on PATH"
        return TrackedProcResult(success=False, message=message, error=str(exc))
    except OSError as exc:
        message = f"Could not run `sase`: {exc}"
        return TrackedProcResult(success=False, message=message, error=str(exc))
    if completed.returncode not in (0, 1):
        tail = bounded_output_tail(completed.stdout)
        if tail:
            reporter.log(tail, stream="stderr")
        message = f"init check failed (exit {completed.returncode})"
        return TrackedProcResult(success=False, message=message, error=message)
    try:
        payload = attach_action_diffs(parse_init_check_payload(completed.stdout))
    except InitCheckPayloadError as exc:
        message = str(exc)
        if message:
            reporter.log(message, stream="stderr")
        return TrackedProcResult(success=False, message=message, error=message)
    message = f"planned {label}: {payload.status}"
    reporter.log(message)
    return TrackedProcResult(success=True, message=message, payload=payload)


def _run_init_apply(
    reporter: SessionProcReporter,
    *,
    argv: list[str],
    cwd: str | Path | None,
    timeout: float,
    label: str,
    total: int,
) -> TrackedProcResult[_InitApplyPayload]:
    reporter.phase(f"Initializing {label}")
    seen = 0

    def on_line(line: str) -> None:
        nonlocal seen
        ref = parse_project_heading(line)
        if ref is None:
            return
        seen += 1
        reporter.phase(f"Project {seen} of {total} · {ref}")

    try:
        completed = reporter.run(
            argv,
            cwd=cwd,
            timeout=timeout,
            on_line=on_line,
        )
    except subprocess.TimeoutExpired:
        payload = _InitApplyPayload(
            kind="failure",
            message=f"Initialization timed out after {timeout:.0f}s — see Procs",
            returncode=124,
        )
        return TrackedProcResult(
            success=False,
            message=payload.message,
            error=payload.message,
            payload=payload,
        )
    except FileNotFoundError as exc:
        payload = _InitApplyPayload(
            kind="failure",
            message="Could not run `sase`: binary not found on PATH — see Procs",
            returncode=127,
        )
        return TrackedProcResult(
            success=False,
            message=payload.message,
            error=str(exc),
            payload=payload,
        )
    except OSError as exc:
        payload = _InitApplyPayload(
            kind="failure",
            message=f"Could not run `sase`: {exc} — see Procs",
            returncode=1,
        )
        return TrackedProcResult(
            success=False,
            message=payload.message,
            error=str(exc),
            payload=payload,
        )
    payload = _apply_payload_from_output(completed.stdout, completed.returncode)
    return TrackedProcResult(
        success=payload.kind != "failure",
        message=payload.message,
        error=None if payload.kind != "failure" else payload.message,
        payload=payload,
    )


def _apply_payload_from_output(output: str, returncode: int) -> _InitApplyPayload:
    summary = parse_init_summary_line(output)
    counts = _parse_summary_counts(summary)
    initialized = counts.get("initialized", 0)
    if summary is None and returncode != 0:
        return _InitApplyPayload(
            kind="failure",
            message=(
                f"Initialization failed (exit {returncode}; no summary line) "
                "— see Procs"
            ),
            returncode=returncode,
        )
    if returncode == 0 and initialized == 0:
        kind: _InitApplyKind = "current"
    elif returncode == 0:
        kind = "success"
    elif initialized > 0:
        kind = "partial"
    else:
        kind = "failure"
    return _InitApplyPayload(
        kind=kind,
        message=_format_apply_toast(counts, kind=kind, returncode=returncode),
        returncode=returncode,
        summary=summary,
    )


def _parse_summary_counts(summary: str | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not summary:
        return counts
    for raw in summary.split(","):
        part = raw.strip()
        if part == "cancelled":
            counts["cancelled"] = 1
            continue
        if part == "deployment failed":
            counts["deployment failed"] = 1
            continue
        match = _COUNT_RE.match(part)
        if match is None:
            continue
        counts[match.group(2)] = int(match.group(1))
    return counts


def _format_apply_toast(
    counts: dict[str, int],
    *,
    kind: _InitApplyKind,
    returncode: int,
) -> str:
    bits: list[str] = []
    initialized = counts.get("initialized", 0)
    if initialized:
        bits.append(f"Initialized {initialized}")
    current = counts.get("current", 0)
    if current:
        bits.append(f"{current} current")
    needs = counts.get("needs attention", 0)
    if needs:
        bits.append(f"{needs} needs attention")
    unavailable = counts.get("unavailable", 0)
    if unavailable:
        bits.append(f"{unavailable} unavailable")
    failed = counts.get("failed", 0)
    if failed:
        bits.append(f"{failed} failed")
    if counts.get("cancelled"):
        bits.append("cancelled")
    if counts.get("deployment failed"):
        bits.append("deployment failed")
    if bits:
        return " · ".join(bits) + " — see Procs"
    if kind == "current":
        return "Projects are current · nothing to initialize — see Procs"
    if kind == "success":
        return "Initialization finished — see Procs"
    return f"Initialization failed (exit {returncode}) — see Procs"


__all__ = [
    "ProjectsInitFlowController",
    "ProjectsInitHost",
    "run_project_init",
]
