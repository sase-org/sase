"""Reusable single-chop run service shared by the scheduler, CLI, and TUI.

The scheduled lumberjack tick, ``sase axe chop run``, and the AXE TUI manual
run all execute one configured chop end-to-end the same way (context build,
env propagation, timeout, streaming run history, and live-run dedupe). This
module owns the public entry point and compatibility surface; focused
implementation modules own the type/lookup, context, and script responsibilities.

:func:`run_configured_chop_once` is the public entry point. It dispatches by
chop type, performs live-run dedupe, and returns a typed
:class:`ChopRunOutcome` — callers translate the outcome into UX (CLI exit
code, TUI notification, scheduler bookkeeping).
"""

from __future__ import annotations

from sase.ace.patch import Patch, find_all_patches
from sase.ace.hooks.processes import is_process_running
from sase.agent.launcher import launch_agent_from_cwd, launch_agents_from_cwd
from sase.core.query_facade import evaluate_query_many

from .chop_runner_context import (
    ONESHOT_LUMBERJACK_NAME,
    build_oneshot_context,
)
from .chop_runner_script import (
    PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS,
    active_script_chop_run,
    run_script_chop_once,
)
from .chop_runner_trace import (
    NO_PYTHON_TRACEBACK,
    PROMPT_PREVIEW_CHARS,
    TRACEBACK_UNAVAILABLE,
    capture_traceback,
    compact_preview,
)
from .chop_runner_types import (
    AmbiguousChopError,
    ChopMatch,
    ChopNotFoundError,
    ChopRunOutcome,
    ChopRunOutcomeStatus,
    find_configured_chop,
)
from .chop_script_runner import discover_chop_script, stream_chop_script
from .config import AxeConfig, ChopConfig
from .state import ChopRunEntry, ChopRunSource


def _capture_traceback() -> str:
    return capture_traceback()


def _compact_preview(value: str, *, limit: int = PROMPT_PREVIEW_CHARS) -> str:
    return compact_preview(value, limit=limit)


def _build_oneshot_context(lumberjack_name: str, axe_config: AxeConfig) -> str:
    return build_oneshot_context(
        lumberjack_name,
        axe_config,
        find_all_patches_fn=find_all_patches,
        evaluate_query_many_fn=_evaluate_query_many_compat,
    )


def _evaluate_query_many_compat(query: str, patches: list[Patch]) -> list[bool]:
    return evaluate_query_many(query, patches)


def _active_script_chop_run(
    lumberjack_name: str,
    chop_name: str,
    *,
    pidless_stale_after_seconds: int | None = None,
) -> ChopRunEntry | None:
    return active_script_chop_run(
        lumberjack_name,
        chop_name,
        pidless_stale_after_seconds=pidless_stale_after_seconds,
        is_process_running_fn=is_process_running,
    )


def _run_script_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None,
    wait_runners_default: int | None,
    context_file: str | None,
    source: ChopRunSource,
    started_by: str | None,
    dry_run: bool,
    chop_verbose: bool,
    force: bool,
) -> ChopRunOutcome:
    return run_script_chop_once(
        lumberjack_name=lumberjack_name,
        chop=chop,
        axe_config=axe_config,
        chop_timeout_default=chop_timeout_default,
        wait_runners_default=wait_runners_default,
        context_file=context_file,
        source=source,
        started_by=started_by,
        dry_run=dry_run,
        chop_verbose=chop_verbose,
        force=force,
        discover_chop_script_fn=discover_chop_script,
        stream_chop_script_fn=stream_chop_script,
        build_context_fn=_build_oneshot_context,
        is_process_running_fn=is_process_running,
        launch_agent_from_cwd_fn=launch_agent_from_cwd,
        launch_agents_from_cwd_fn=launch_agents_from_cwd,
    )


def run_configured_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None = None,
    wait_runners_default: int | None = None,
    context_file: str | None = None,
    source: ChopRunSource = "manual",
    started_by: str | None = None,
    dry_run: bool = False,
    chop_verbose: bool = False,
    force: bool = False,
) -> ChopRunOutcome:
    """Execute one configured chop once, sharing logic across all callers.

    Dedupes against any live script process before preflight.  For a prior
    launched action, declarative guards run first so their skip reason remains
    visible; an accepted non-forced run is still deduped, while ``force`` may
    dispatch another action.  Accepted runs execute the configured script in
    the foreground via :func:`stream_chop_script`, opening a streaming
    run-history entry before the subprocess starts and finalizing the same entry
    on success/failure/timeout.

    ``source`` is persisted on the run entry so consumers (TUI, CLI) can
    distinguish scheduled, manual, and CLI one-shot runs without parsing logs.
    ``context_file`` lets the scheduler reuse its per-tick context; when
    ``None`` a fresh context.json is built under the lumberjack's tick dir.
    """
    return _run_script_chop_once(
        lumberjack_name=lumberjack_name,
        chop=chop,
        axe_config=axe_config,
        chop_timeout_default=chop_timeout_default,
        wait_runners_default=wait_runners_default,
        context_file=context_file,
        source=source,
        started_by=started_by,
        dry_run=dry_run,
        chop_verbose=chop_verbose,
        force=force,
    )


_ChopMatch = ChopMatch

__all__ = [
    "AmbiguousChopError",
    "ChopNotFoundError",
    "ChopRunOutcome",
    "ChopRunOutcomeStatus",
    "NO_PYTHON_TRACEBACK",
    "ONESHOT_LUMBERJACK_NAME",
    "PIDLESS_SCRIPT_CHOP_STALE_FALLBACK_SECONDS",
    "PROMPT_PREVIEW_CHARS",
    "TRACEBACK_UNAVAILABLE",
    "_ChopMatch",
    "_active_script_chop_run",
    "_build_oneshot_context",
    "_capture_traceback",
    "_compact_preview",
    "_run_script_chop_once",
    "discover_chop_script",
    "find_all_patches",
    "find_configured_chop",
    "is_process_running",
    "launch_agent_from_cwd",
    "run_configured_chop_once",
    "stream_chop_script",
]
