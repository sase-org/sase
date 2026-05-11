"""Reusable single-chop run service shared by the scheduler, CLI, and TUI.

The scheduled lumberjack tick, ``sase axe chop run``, and the AXE TUI manual
run all execute one configured chop end-to-end the same way (context build,
env propagation, timeout, streaming run history, agent dedupe). This module
owns that single code path so the three surfaces cannot drift.

:func:`run_configured_chop_once` is the public entry point. It dispatches by
chop type, performs live-run dedupe, and returns a typed
:class:`ChopRunOutcome` — callers translate the outcome into UX (CLI exit
code, TUI notification, scheduler bookkeeping).
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.ace.changespec import find_all_changespecs
from sase.core.query_facade import evaluate_query_many
from sase.core.time import get_timezone

from .chop_agents import (
    build_chop_launch_env,
    get_live_chop_agent_records,
    prompt_hash,
    record_chop_agent_launch_result,
)
from .chop_script_context import (
    ChopScriptContext,
    serialize_changespecs,
    write_chop_context,
)
from .chop_script_runner import (
    discover_chop_script,
    stream_chop_script,
)
from .config import AxeConfig, ChopConfig, LumberjackConfig
from .state import (
    ChopRunEntry,
    ChopRunSource,
    chop_run_log_path,
    ensure_lumberjack_dirs,
    finish_chop_run,
    generate_chop_run_id,
    read_chop_run,
    read_chop_run_index,
    start_chop_run,
    update_chop_run_pid,
    write_chop_run,
)

NO_PYTHON_TRACEBACK = "<no python traceback: subprocess error>"
TRACEBACK_UNAVAILABLE = "<traceback unavailable>"

# Synthetic lumberjack name used by ``sase axe chop run <name>`` when the
# chop is not configured under any real lumberjack. Matches the legacy CLI
# fallback so unconfigured scripts continue to work.
ONESHOT_LUMBERJACK_NAME = "_oneshot"


def _capture_traceback() -> str:
    """Capture the active exception traceback, with a placeholder for empty."""
    formatted = traceback.format_exc().rstrip("\n")
    if formatted == "NoneType: None" or not formatted:
        return TRACEBACK_UNAVAILABLE
    return formatted


ChopRunOutcomeStatus = Literal[
    "success",
    "failure",
    "timeout",
    "missing_script",
    "agent_launched",
    "agent_failed",
    "already_running",
]


@dataclass
class ChopRunOutcome:
    """Result of running one configured chop once.

    ``run_id`` is set whenever an entry was opened in the chop run history,
    including dedupe skips (where it points at the already-running entry).
    ``error``/``traceback`` are populated for failure-shaped outcomes so
    callers can surface diagnostics without re-reading the on-disk metadata.
    """

    lumberjack_name: str
    chop_name: str
    status: ChopRunOutcomeStatus
    run_id: str | None = None
    exit_code: int | None = None
    agent_pid: int | None = None
    output_bytes: int = 0
    error: Exception | None = None
    traceback: str | None = None


class ChopNotFoundError(LookupError):
    """Raised when a chop name does not match any configured chop."""

    def __init__(self, chop_name: str, lumberjack_name: str | None = None) -> None:
        if lumberjack_name is None:
            super().__init__(f"chop '{chop_name}' is not configured")
        else:
            super().__init__(
                f"chop '{chop_name}' is not configured under lumberjack "
                f"'{lumberjack_name}'"
            )
        self.chop_name = chop_name
        self.lumberjack_name = lumberjack_name


class AmbiguousChopError(LookupError):
    """Raised when a chop name appears under multiple lumberjacks and none was given."""

    def __init__(self, chop_name: str, candidates: list[str]) -> None:
        joined = ", ".join(sorted(candidates))
        super().__init__(
            f"chop '{chop_name}' is configured in multiple lumberjacks: {joined}"
            " — pass --lumberjack to disambiguate"
        )
        self.chop_name = chop_name
        self.candidates = sorted(candidates)


@dataclass
class _ChopMatch:
    lumberjack_name: str
    lumberjack: LumberjackConfig
    chop: ChopConfig


def find_configured_chop(
    config: AxeConfig,
    chop_name: str,
    lumberjack_name: str | None = None,
) -> _ChopMatch:
    """Resolve a chop name to its configured lumberjack and chop config.

    ``lumberjack_name`` constrains the search; without it, a chop name that
    appears under more than one lumberjack raises :class:`AmbiguousChopError`.
    """
    matches: list[_ChopMatch] = []
    for jack_name, jack in config.lumberjacks.items():
        if lumberjack_name is not None and jack_name != lumberjack_name:
            continue
        for chop in jack.chops:
            if chop.name == chop_name:
                matches.append(_ChopMatch(jack_name, jack, chop))

    if not matches:
        raise ChopNotFoundError(chop_name=chop_name, lumberjack_name=lumberjack_name)
    if len(matches) > 1 and lumberjack_name is None:
        raise AmbiguousChopError(
            chop_name=chop_name,
            candidates=[m.lumberjack_name for m in matches],
        )
    return matches[0]


def _active_script_chop_run(
    lumberjack_name: str, chop_name: str
) -> ChopRunEntry | None:
    """Return the newest chop run entry if it is still in ``running`` state.

    Only the head of the index is inspected: pruning keeps active runs at the
    front, and a finalized newest entry means there is no live run to dedupe
    against. Stale ``running`` rows from a crashed prior process are still
    treated as live for safety — the user can intervene before relaunching.
    """
    index = read_chop_run_index(lumberjack_name, chop_name)
    if not index:
        return None
    head_id = index[0]
    head = read_chop_run(lumberjack_name, chop_name, head_id)
    if head is None:
        return None
    if head.status == "running":
        return head
    return None


def _build_oneshot_context(lumberjack_name: str, axe_config: AxeConfig) -> str:
    """Serialize a single-chop context.json under the lumberjack's tick dir.

    Mirrors what :class:`Lumberjack` writes once per tick so chop scripts see
    identical context regardless of whether the run was scheduled, kicked off
    by the CLI, or triggered from the TUI.
    """
    state_dir = ensure_lumberjack_dirs(lumberjack_name)
    tick_dir = state_dir / "tick"
    tick_dir.mkdir(parents=True, exist_ok=True)

    all_cs_file = str(tick_dir / "all_changespecs.json")
    filtered_cs_file = str(tick_dir / "filtered_changespecs.json")
    context_file = str(tick_dir / "context.json")

    all_changespecs = find_all_changespecs()
    filtered_changespecs = all_changespecs
    if axe_config.query:
        mask = evaluate_query_many(axe_config.query, all_changespecs)
        filtered_changespecs = [
            cs for cs, keep in zip(all_changespecs, mask, strict=True) if keep
        ]

    serialize_changespecs(all_changespecs, all_cs_file)
    serialize_changespecs(filtered_changespecs, filtered_cs_file)

    ctx = ChopScriptContext(
        max_hook_runners=axe_config.max_hook_runners,
        max_agent_runners=axe_config.max_agent_runners,
        zombie_timeout_seconds=axe_config.zombie_timeout_seconds,
        query=axe_config.query,
        lumberjack_name=lumberjack_name,
        state_dir=str(state_dir),
        all_changespecs_file=all_cs_file,
        filtered_changespecs_file=filtered_cs_file,
    )
    write_chop_context(ctx, context_file)
    return context_file


def run_configured_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None = None,
    context_file: str | None = None,
    source: ChopRunSource = "manual",
    started_by: str | None = None,
) -> ChopRunOutcome:
    """Execute one configured chop once, sharing logic across all callers.

    Dispatches by chop type:

    - Agent chop: dedupes against the live registry, then routes through
      :func:`launch_agent_from_cwd`. A successful launch is recorded as
      ``agent_launched``; a launch exception is recorded as ``agent_failed``.
    - Script chop: dedupes against any live ``running`` run-history entry,
      then runs in the foreground via :func:`stream_chop_script`, opening a
      streaming run-history entry before the subprocess starts and finalizing
      the same entry on success/failure/timeout.

    ``source`` is persisted on the run entry so consumers (TUI, CLI) can
    distinguish scheduled, manual, and CLI one-shot runs without parsing logs.
    ``context_file`` lets the scheduler reuse its per-tick context; when
    ``None`` a fresh context.json is built under the lumberjack's tick dir.
    """
    if chop.agent is not None:
        return _run_agent_chop_once(
            lumberjack_name=lumberjack_name,
            chop=chop,
            source=source,
            started_by=started_by,
        )

    return _run_script_chop_once(
        lumberjack_name=lumberjack_name,
        chop=chop,
        axe_config=axe_config,
        chop_timeout_default=chop_timeout_default,
        context_file=context_file,
        source=source,
        started_by=started_by,
    )


def _run_agent_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    source: ChopRunSource,
    started_by: str | None,
) -> ChopRunOutcome:
    assert chop.agent is not None
    started_at = datetime.now(get_timezone())
    run_id = generate_chop_run_id(started_at)

    prompt_hash_value = prompt_hash(chop.agent)
    live = get_live_chop_agent_records(
        lumberjack_name,
        chop_name=chop.name,
        prompt_hash_value=prompt_hash_value,
    )
    if live:
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="already_running",
            agent_pid=next(iter(record.pid for record in live), None),
        )

    extra_env = build_chop_launch_env(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        prompt=chop.agent,
    )
    try:
        from sase.agent.launcher import launch_agent_from_cwd

        result = launch_agent_from_cwd(chop.agent, extra_env=extra_env)
    except Exception as e:
        tb = _capture_traceback()
        finished_at = datetime.now(get_timezone())
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        try:
            write_chop_run(
                ChopRunEntry(
                    run_id=run_id,
                    lumberjack_name=lumberjack_name,
                    chop_name=chop.name,
                    started_at=started_at.isoformat(),
                    finished_at=finished_at.isoformat(),
                    duration_ms=duration_ms,
                    status="failure",
                    error=str(e),
                    traceback=tb,
                    source=source,
                    started_by=started_by,
                )
            )
        except OSError:
            pass
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="agent_failed",
            run_id=run_id,
            error=e,
            traceback=tb,
        )

    record_chop_agent_launch_result(result=result, prompt=chop.agent, env=extra_env)

    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    launch_line = f"Launched agent chop '{chop.name}' (PID {result.pid})\n"
    try:
        write_chop_run(
            ChopRunEntry(
                run_id=run_id,
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_ms=duration_ms,
                status="agent_launched",
                agent_pid=result.pid,
                source=source,
                started_by=started_by,
            ),
            output=launch_line,
        )
    except OSError:
        pass

    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        status="agent_launched",
        run_id=run_id,
        agent_pid=result.pid,
    )


def _run_script_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    axe_config: AxeConfig,
    chop_timeout_default: int | None,
    context_file: str | None,
    source: ChopRunSource,
    started_by: str | None,
) -> ChopRunOutcome:
    live = _active_script_chop_run(lumberjack_name, chop.name)
    if live is not None:
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="already_running",
            run_id=live.run_id,
        )

    started_at = datetime.now(get_timezone())
    resolved_timeout = chop.timeout or chop_timeout_default
    run_id = generate_chop_run_id(started_at)

    script = discover_chop_script(chop.name, axe_config.chop_script_dirs)
    if script is None:
        error = RuntimeError(f"Chop script not found: {chop.name}")
        finished_at = datetime.now(get_timezone())
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        try:
            write_chop_run(
                ChopRunEntry(
                    run_id=run_id,
                    lumberjack_name=lumberjack_name,
                    chop_name=chop.name,
                    started_at=started_at.isoformat(),
                    finished_at=finished_at.isoformat(),
                    duration_ms=duration_ms,
                    status="missing_script",
                    error=str(error),
                    traceback=NO_PYTHON_TRACEBACK,
                    source=source,
                    started_by=started_by,
                )
            )
        except OSError:
            pass
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="missing_script",
            run_id=run_id,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
        )

    env = dict(chop.env)
    env.update(
        build_chop_launch_env(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            prompt=chop.agent,
        )
    )

    state_dir = ensure_lumberjack_dirs(lumberjack_name)
    if context_file is None:
        context_file = _build_oneshot_context(lumberjack_name, axe_config)

    start_entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        source=source,
        started_by=started_by,
    )
    try:
        start_chop_run(start_entry)
    except OSError:
        pass

    log_path = chop_run_log_path(lumberjack_name, chop.name, run_id)

    def _record_pid(pid: int) -> None:
        try:
            update_chop_run_pid(lumberjack_name, chop.name, run_id, pid)
        except OSError:
            pass

    try:
        result = stream_chop_script(
            script,
            context_file,
            log_path=log_path,
            timeout=resolved_timeout,
            env=env,
            cwd=str(state_dir),
            on_pid=_record_pid,
        )
    except Exception as e:
        tb = _capture_traceback()
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="failure",
            exit_code=None,
            error=e,
            tb=tb,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="failure",
            run_id=run_id,
            error=e,
            traceback=tb,
        )

    if result.timed_out:
        error = RuntimeError(f"timed out after {resolved_timeout}s")
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="timeout",
            exit_code=None,
            error=error,
            tb=NO_PYTHON_TRACEBACK,
            output_bytes=result.output_bytes,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="timeout",
            run_id=run_id,
            output_bytes=result.output_bytes,
            error=error,
            traceback=NO_PYTHON_TRACEBACK,
        )

    if result.returncode == 0:
        _finalize(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            run_id=run_id,
            started_at=started_at,
            status="success",
            exit_code=0,
            output_bytes=result.output_bytes,
        )
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="success",
            run_id=run_id,
            exit_code=0,
            output_bytes=result.output_bytes,
        )

    error = RuntimeError(f"exit code {result.returncode}")
    _finalize(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        run_id=run_id,
        started_at=started_at,
        status="failure",
        exit_code=result.returncode,
        error=error,
        tb=NO_PYTHON_TRACEBACK,
        output_bytes=result.output_bytes,
    )
    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        status="failure",
        run_id=run_id,
        exit_code=result.returncode,
        output_bytes=result.output_bytes,
        error=error,
        traceback=NO_PYTHON_TRACEBACK,
    )


def _finalize(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    started_at: datetime,
    status: str,
    exit_code: int | None = None,
    error: Exception | None = None,
    tb: str | None = None,
    output_bytes: int | None = None,
) -> None:
    """Stamp terminal state onto a previously-opened streaming run entry."""
    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    try:
        finish_chop_run(
            lumberjack_name,
            chop_name,
            run_id,
            status=status,  # type: ignore[arg-type]
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            exit_code=exit_code,
            error=str(error) if error is not None else None,
            traceback=tb,
            output_bytes=output_bytes,
        )
    except OSError:
        pass
