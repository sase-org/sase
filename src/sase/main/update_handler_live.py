"""Live (non-dry-run, non-mode-switch) execution path for ``sase update``."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

# Self-update safety: this handler fast-forwards (editable) or replaces (uv)
# the very code the running process imports, so every module the rest of the
# run needs is imported here at module top level, never lazily after
# execution starts. The renderer and rich imports below are only referenced by
# ``_PRELOADED_FOR_SELF_UPDATE``; that tuple exists to keep them preloaded.
from rich.live import Live as _Live
from rich.spinner import Spinner as _Spinner

from sase.dev_update import DevUpdatePlan, DevUpdateResult
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevCommandRunner
from sase.dev_update.outcomes import failed_result
from sase.completion.install import CompletionRefreshReport
from sase.main.update_handler_completion import (
    completion_refresh_after_update,
    render_completion_refresh,
)
from sase.main.update_handler_support import (
    COMPLETIONS_STEP_ID as _COMPLETIONS_STEP_ID,
    COMPLETIONS_STEP_TITLE as _COMPLETIONS_STEP_TITLE,
    INSPECT_STEP_ID as _INSPECT_STEP_ID,
    INSPECT_STEP_TITLE as _INSPECT_STEP_TITLE,
    RESTART_STEP_ID as _RESTART_STEP_ID,
    RESTART_STEP_TITLE as _RESTART_STEP_TITLE,
    ProgressSessionFactory,
    call_execute_dev_update,
    call_plan_dev_update,
    call_run_uv,
    fail_update,
    finish_completions_step as _finish_completions,
    finish_restart_step as _finish_restart,
    print_interrupted as _print_interrupted,
    session_log_path as _log_path_str,
    tool_python,
)
from sase.main.update_json import combined_result_json
from sase.main.update_render import render_dev_update_result
from sase.main.update_restart import (
    render_restart_info,
    restart_after_update,
    restart_skipped,
)
from sase.main.update_routing import (
    dev_route,
    managed_summary_receipt,
    managed_update_argv,
    managed_update_packages,
    should_run_managed_update,
    try_load_receipt,
    update_mode,
)
from sase.main.update_state import combined_changed, dev_update_succeeded
from sase.main.update_types import (
    ClockFn,
    DevRoute,
    ExecuteDevFn,
    InventoryFn,
    PlanDevFn,
    RestartInfo,
    RestartSchedulerFn,
    RunUvFn,
    SchedulerRunningFn,
    VersionFn,
)
from sase.update_progress import StepSpec, UpdateProgress
from sase.update_progress.render_live import LiveTimelineRenderer as _LiveRenderer
from sase.version._utils import normalize_distribution_name
from sase.update_progress.render_plain import (
    PlainTimelineRenderer as _PlainRenderer,
)
from sase.update_progress.session import UpdateProgressSession
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.render import (
    PlannedPackage,
    UpdateSummary,
    render_update_result,
    summarize_planned_update,
    summarize_update,
)
from sase.uv_tool.runner import match_uv_change_line

_PRELOADED_FOR_SELF_UPDATE: tuple[object, ...] = (
    _LiveRenderer,
    _PlainRenderer,
    _Live,
    _Spinner,
)
"""Modules that must stay imported across the self-update code swap.

``sase update`` replaces its own code mid-run; anything imported lazily after
that point could load half-written modules. These names are otherwise unused
here (the session builds its own renderers), so the tuple keeps them alive.
"""

_MANAGED_STEP_ID = "managed"
_MANAGED_STEP_TITLE = "Upgrade sase + plugins via uv"


def _default_progress_session(
    *,
    err: Console,
    as_json: bool,
    quiet: bool,
    verbose: bool,
) -> UpdateProgressSession:
    """Build a real progress session on the default clock and log directory.

    The session owns its own monotonic clock rather than sharing the
    handler's injected ``clock``: handler clocks in tests are often finite
    iterators sized for the elapsed-time computation, and session timestamps
    must never consume them.
    """
    return UpdateProgressSession(
        err, argv=sys.argv, as_json=as_json, quiet=quiet, verbose=verbose
    )


class _ManagedPackageWatcher:
    """Turn streamed ``+/- name==ver`` uv lines into ``managed:<pkg>`` rows.

    Every line is forwarded to the ``managed`` tail first (live tail,
    failure expansion, ``-v``, and the log), then ``+/- name==ver`` lines
    become parented child rows. A ``- name==old`` line followed by
    ``+ name==new`` pairs into one child row (``old → new``); unpaired lines
    still get a row with whatever side was seen. Rows the stream never
    touched are filled in from the parsed :class:`UpdateSummary`.
    """

    def __init__(self, progress: UpdateProgress) -> None:
        """Bind to the session progress sink."""
        self._progress = progress
        self._declared: set[str] = set()
        self._old_versions: dict[str, str] = {}

    def sink(self, stream: str, line: str) -> None:
        """Consume one streamed output line, creating child rows as needed."""
        self._progress.output(_MANAGED_STEP_ID, stream, line)
        matched = match_uv_change_line(line)
        if matched is None:
            return
        sign, name, version = matched
        key = normalize_distribution_name(name)
        child_id = f"{_MANAGED_STEP_ID}:{key}"
        self._ensure_child(child_id, name)
        if sign == "-":
            self._old_versions[key] = version
            self._progress.start(child_id, title=name, detail=version)
        else:
            old = self._old_versions.get(key)
            detail = f"{old} → {version}" if old else version
            self._progress.start(child_id, title=name)
            self._progress.finish(child_id, "done", detail=detail)

    def _ensure_child(self, child_id: str, title: str) -> None:
        """Declare a transitive package row under ``managed`` once."""
        if child_id in self._declared:
            return
        self._declared.add(child_id)
        self._progress.declare((StepSpec(child_id, title, parent_id=_MANAGED_STEP_ID),))

    def finish_all(self, summary: UpdateSummary) -> None:
        """Finish one child row per summary outcome from the final summary."""
        for outcome in summary.outcomes:
            key = normalize_distribution_name(outcome.name)
            child_id = f"{_MANAGED_STEP_ID}:{key}"
            self._ensure_child(child_id, outcome.name)
            self._progress.finish(child_id, "done", detail=_outcome_detail(outcome))


def _outcome_detail(outcome: object) -> str | None:
    """Format a summary outcome as a child-row detail line."""
    name = getattr(outcome, "name", "")
    kind = getattr(getattr(outcome, "kind", None), "value", None)
    old = getattr(outcome, "old_version", None)
    new = getattr(outcome, "new_version", None)
    if kind == "upgraded" and old and new:
        return f"{old} → {new}"
    if kind == "added" and new:
        return str(new)
    if kind == "removed" and old:
        return f"removed {old}"
    if new:
        return str(new)
    return str(name) if name else None


def _journal_interrupted(run_ref: _RunRef) -> None:
    """Journal an interrupted run wherever a dev plan exists."""
    if run_ref.plan is None or run_ref.journal_appended:
        return
    result = run_ref.result
    if result is None:
        result = failed_result(run_ref.plan, "interrupted", [], changed=False)
    try:
        append_dev_update_journal(
            run_ref.plan,
            result,
            restart=RestartInfo(
                attempted=False,
                status="skipped_no_change",
                reason="interrupted",
            ),
        )
    except Exception:  # noqa: BLE001 - interrupt path must stay clean.
        pass


@dataclass(frozen=True)
class _LiveReady:
    """Routing resolved before the renderer enters (so it knows the mode)."""

    receipt: ToolReceipt | None
    route: DevRoute | None
    mode: str
    argv: list[str]
    managed_packages: tuple[PlannedPackage, ...]
    has_dev: bool
    has_managed: bool


def _prepare_live_update(
    session: UpdateProgressSession,
    install: UvToolInstall,
    *,
    inventory_fn: InventoryFn,
    version_fn: VersionFn,
    as_json: bool,
    err: Console,
) -> _LiveReady | int:
    """Run receipt load, routing, and preflight under the inspect step.

    Returns the resolved routing, or an exit code when a failure line (plus
    the final frame) was already printed. The renderer has not entered yet,
    so the plain header printed on entry already carries the install mode.
    """
    progress = session.progress
    progress.start(_INSPECT_STEP_ID, title=_INSPECT_STEP_TITLE)
    receipt = try_load_receipt(install)
    route = dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        progress.finish(_INSPECT_STEP_ID, "failed", detail=str(route))
        session.print_final()
        return fail_update(
            route, as_json=as_json, err=err, log_path=_log_path_str(session)
        )

    has_dev = route is not None and bool(route.records)
    has_managed = should_run_managed_update(receipt, route)
    if has_managed and receipt is not None:
        if (
            error := missing_local_requirements_error(receipt.reconstruct())
        ) is not None:
            progress.finish(_INSPECT_STEP_ID, "failed", detail=str(error))
            session.print_final()
            return fail_update(
                error, as_json=as_json, err=err, log_path=_log_path_str(session)
            )
    mode = update_mode(has_dev=has_dev, has_managed=has_managed)
    session.set_header(f"{mode} install")
    argv = managed_update_argv(receipt, route, color="never") if has_managed else []
    managed_packages = (
        managed_update_packages(receipt, route, version_fn=version_fn)
        if has_managed
        else ()
    )

    if route is not None:
        n_editable = len(route.records)
        n_managed = len(route.managed_requirements) + (
            1 if route.managed_core_record is not None else 0
        )
        inspect_detail = f"uv tool · {n_editable} editable · {n_managed} managed"
    elif receipt is None:
        inspect_detail = "uv tool upgrade"
    else:
        inspect_detail = f"uv tool · 0 editable · {len(managed_packages)} managed"

    # Trailing rows sort after every dev row (check/merge/reconcile) declared
    # later, so the timeline renders in execution order.
    specs = [
        StepSpec(_RESTART_STEP_ID, _RESTART_STEP_TITLE, trailing=True),
        StepSpec(_COMPLETIONS_STEP_ID, _COMPLETIONS_STEP_TITLE, trailing=True),
    ]
    if has_managed:
        specs.insert(0, StepSpec(_MANAGED_STEP_ID, _MANAGED_STEP_TITLE, trailing=True))
        for package in managed_packages:
            specs.append(
                StepSpec(
                    f"{_MANAGED_STEP_ID}:{normalize_distribution_name(package.name)}",
                    package.name,
                    parent_id=_MANAGED_STEP_ID,
                )
            )
    progress.declare(tuple(specs))
    progress.finish(_INSPECT_STEP_ID, "done", detail=inspect_detail)
    return _LiveReady(
        receipt=receipt,
        route=route,
        mode=mode,
        argv=argv,
        managed_packages=managed_packages,
        has_dev=has_dev,
        has_managed=has_managed,
    )


def handle_live_update(
    install: UvToolInstall,
    *,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    run_fn: RunUvFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: PlanDevFn,
    execute_dev_update_fn: ExecuteDevFn,
    run_dev_update_fn: DevCommandRunner,
    scheduler_running_fn: SchedulerRunningFn,
    restart_scheduler_fn: RestartSchedulerFn,
    version_fn: VersionFn,
    clock: ClockFn,
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None = None,
    verbose: bool = False,
    progress_session_factory: ProgressSessionFactory | None = None,
) -> int:
    """Run the live update flow inside a progress session; return exit code."""
    factory = progress_session_factory or _default_progress_session
    session = factory(err=err, as_json=as_json, quiet=quiet, verbose=verbose)
    run_ref = _RunRef()
    try:
        ready = _prepare_live_update(
            session,
            install,
            inventory_fn=inventory_fn,
            version_fn=version_fn,
            as_json=as_json,
            err=err,
        )
    except KeyboardInterrupt:
        session.interrupt()
        session.print_final()
        _journal_interrupted(run_ref)
        _print_interrupted(err, _log_path_str(session))
        return 130
    if isinstance(ready, int):
        return ready
    with session:
        try:
            return _run_live_update(
                install,
                session=session,
                ready=ready,
                as_json=as_json,
                quiet=quiet,
                out=out,
                err=err,
                run_fn=run_fn,
                inventory_fn=inventory_fn,
                plan_dev_update_fn=plan_dev_update_fn,
                execute_dev_update_fn=execute_dev_update_fn,
                run_dev_update_fn=run_dev_update_fn,
                scheduler_running_fn=scheduler_running_fn,
                restart_scheduler_fn=restart_scheduler_fn,
                version_fn=version_fn,
                clock=clock,
                refresh_completions_fn=refresh_completions_fn,
                run_ref=run_ref,
            )
        except KeyboardInterrupt:
            session.interrupt()
            session.print_final()
            _journal_interrupted(run_ref)
            _print_interrupted(err, _log_path_str(session))
            return 130


class _RunRef:
    """Share the dev plan and result with the interrupt handler."""

    def __init__(self) -> None:
        """Start empty; the live body fills these in as they become known."""
        self.plan: DevUpdatePlan | None = None
        self.result: DevUpdateResult | None = None
        self.journal_appended = False


def _run_live_update(
    install: UvToolInstall,
    *,
    session: UpdateProgressSession,
    ready: _LiveReady,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    run_fn: RunUvFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: PlanDevFn,
    execute_dev_update_fn: ExecuteDevFn,
    run_dev_update_fn: DevCommandRunner,
    scheduler_running_fn: SchedulerRunningFn,
    restart_scheduler_fn: RestartSchedulerFn,
    version_fn: VersionFn,
    clock: ClockFn,
    refresh_completions_fn: Callable[[], CompletionRefreshReport] | None,
    run_ref: _RunRef,
) -> int:
    progress = session.progress
    receipt = ready.receipt
    route = ready.route
    mode = ready.mode
    argv = ready.argv
    managed_packages = ready.managed_packages
    has_managed = ready.has_managed

    start = clock()
    dev_plan: DevUpdatePlan | None = None
    dev_result: DevUpdateResult | None = None

    if route is not None and route.records:
        try:
            dev_plan = call_plan_dev_update(
                plan_dev_update_fn,
                route.records,
                host_record=route.host_record,
                receipt=receipt,
                tool_python=tool_python(install),
                stale_core_record=route.stale_core_record,
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 - surface planning failures cleanly.
            progress.finish("check", "failed", detail=str(exc))
            session.print_final()
            return fail_update(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
                log_path=_log_path_str(session),
            )
        run_ref.plan = dev_plan
        dev_result = call_execute_dev_update(
            execute_dev_update_fn,
            dev_plan,
            run=run_dev_update_fn,
            progress=progress,
        )
        run_ref.result = dev_result
        if not dev_update_succeeded(dev_result):
            append_dev_update_journal(
                dev_plan,
                dev_result,
                restart=RestartInfo(
                    attempted=False,
                    status="skipped_no_change",
                    reason="update failed before scheduler restart",
                ),
            )
            run_ref.journal_appended = True
            elapsed = max(0.0, clock() - start)
            log_path = _log_path_str(session)
            session.print_final()
            if as_json:
                print(
                    json.dumps(
                        combined_result_json(
                            mode=mode,
                            managed_argv=argv,
                            managed_summary=None,
                            dev_plan=dev_plan,
                            dev_result=dev_result,
                            elapsed=elapsed,
                            restart=restart_skipped(changed=False),
                            log_path=log_path,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                render_dev_update_result(
                    dev_result,
                    elapsed=elapsed,
                    quiet=quiet,
                    console=err,
                    failed=True,
                    timeline_shown=session.shown,
                )
                if log_path is not None:
                    err.print(f"Full log: {log_path}", style="dim")
            return 1

    managed_summary: UpdateSummary | None = None
    if has_managed:
        progress.start(_MANAGED_STEP_ID, title=_MANAGED_STEP_TITLE)
        watcher = _ManagedPackageWatcher(progress)
        progress.command(_MANAGED_STEP_ID, argv)
        try:
            change_set = call_run_uv(run_fn, argv, on_output=watcher.sink)
        except UvToolError as exc:
            progress.finish(_MANAGED_STEP_ID, "failed", detail=str(exc))
            if dev_plan is not None and dev_result is not None:
                append_dev_update_journal(
                    dev_plan,
                    dev_result,
                    restart=RestartInfo(
                        attempted=False,
                        status="skipped_no_change",
                        reason="managed update failed before scheduler restart",
                    ),
                )
                run_ref.journal_appended = True
            session.print_final()
            return fail_update(
                exc, as_json=as_json, err=err, log_path=_log_path_str(session)
            )
        if route is not None:
            managed_summary = summarize_planned_update(change_set, managed_packages)
        else:
            managed_summary = summarize_update(
                change_set,
                managed_summary_receipt(receipt),
                current_version=version_fn,
            )
        watcher.finish_all(managed_summary)
        progress.finish(
            _MANAGED_STEP_ID,
            "done",
            detail=(
                f"{len(managed_summary.updated)} upgraded · "
                f"{len(managed_summary.already_current)} current"
            ),
        )

    elapsed = max(0.0, clock() - start)
    changed = combined_changed(dev_result, managed_summary)
    progress.start(_RESTART_STEP_ID, title=_RESTART_STEP_TITLE)
    restart = restart_after_update(
        changed=changed,
        scheduler_running_fn=scheduler_running_fn,
        restart_scheduler_fn=restart_scheduler_fn,
        source="sase update",
    )
    _finish_restart(progress, restart)
    if dev_plan is not None and dev_result is not None:
        append_dev_update_journal(
            dev_plan,
            dev_result,
            restart=restart,
        )
        run_ref.journal_appended = True

    progress.start(_COMPLETIONS_STEP_ID, title=_COMPLETIONS_STEP_TITLE)
    refresh = completion_refresh_after_update(install, refresh_completions_fn)
    _finish_completions(progress, refresh)

    log_path = _log_path_str(session)
    session.print_final()

    if as_json:
        payload = combined_result_json(
            mode=mode,
            managed_argv=argv,
            managed_summary=managed_summary,
            dev_plan=dev_plan,
            dev_result=dev_result,
            elapsed=elapsed,
            restart=restart,
            log_path=log_path,
        )
        if refresh.attempted:
            payload["completion_refresh"] = refresh.to_json()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if dev_result is not None:
        render_dev_update_result(
            dev_result,
            elapsed=elapsed,
            quiet=quiet,
            console=out,
            failed=False,
            timeline_shown=session.shown,
        )
    if managed_summary is not None:
        render_update_result(managed_summary, elapsed=elapsed, quiet=quiet, console=out)
    if changed:
        render_restart_info(restart, console=out, quiet=quiet)
    render_completion_refresh(refresh, console=out, quiet=quiet)
    return 0
