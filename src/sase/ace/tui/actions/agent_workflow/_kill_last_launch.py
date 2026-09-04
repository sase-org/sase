"""``,X`` — kill and edit the most recently launched agent this session."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

from ._entry_relaunch import (
    prepare_kill_edit_agent_prompt,
    resolve_agent_identity,
    schedule_relaunch_prompt_resolution,
)
from ._launch_delta import artifact_dir_from_launch_result
from ._launch_records import (
    LaunchRecord,
    LaunchRecordState,
    begin_resolved_launch_action,
    consume_launch_record,
    latest_live_launch_record,
    launch_record_for_proc_id,
    record_procs_are_terminal,
    release_resolved_launch_action,
    release_kill_pending_launch_record,
)
from ._relaunch_barrier import (
    PENDING_LAUNCH_KILL_TIMEOUT_SECONDS,
    open_relaunch_cleanup_barrier,
    release_relaunch_holds_if_idle,
    settle_relaunch_cleanup_barrier,
)
from ..navigation._agent_reveal import (
    AgentIdentity,
    prepare_agent_navigation_target,
    reveal_agent_navigation_target,
)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from ...models import Agent

log = logging.getLogger(__name__)

_ADMISSION_DEFERRED_STATUSES = frozenset({"WAITING", "QUEUED"})


def _agent_for_launch_result(
    agents: Sequence[Agent], result: AgentLaunchResult
) -> Agent | None:
    """Return the loaded row this session's own launch produced, if any."""
    target = artifact_dir_from_launch_result(result)
    if target is None:
        return None
    target_str = str(target)
    for agent in agents:
        found = agent.get_artifacts_dir()
        if found == target_str:
            return agent
        raw = getattr(agent, "artifacts_dir", None)
        if raw is not None and str(raw) == target_str:
            return agent
    return None


def _matched_agents_for_record(
    record: LaunchRecord, agents: Sequence[Agent]
) -> list[Agent]:
    """Join a resolved record's launch results to currently loaded rows.

    Iterates in ``record.proc_ids`` order (launch/mark order); a result with
    no loaded row (already killed or dismissed by hand since launch) is
    skipped rather than treated as an error.
    """
    matched: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for proc_id in record.proc_ids:
        for result in record.results.get(proc_id, ()):
            agent = _agent_for_launch_result(agents, result)
            if agent is None or agent.identity in seen:
                continue
            seen.add(agent.identity)
            matched.append(agent)
    return matched


def _is_gate_dismissable(agent: Agent) -> bool:
    if not getattr(agent, "is_gate", False):
        return False
    from sase.gate_shell.state import gate_state_is_terminal

    return bool(gate_state_is_terminal(agent.gate_state) or agent.stop_time)


class KillAndEditLastLaunchMixin:
    """``,X`` entry point: kill and edit this session's last accepted launch."""

    # Declared to match AceApp so reveal assignments do not invent a None-only type.
    _current_group_key: tuple[str, ...] | None
    current_idx: int
    current_attempt_number: int | None

    def _kill_and_edit_last_launch(self) -> None:
        """Kill and edit the newest launch record this session can still target.

        Marks are ignored by design: ``,X`` always targets the most recently
        accepted launch, never the focused or marked row(s). A record whose
        rows were already killed/dismissed by hand is skipped in favor of the
        next live record. An in-flight launch restores the prompt immediately
        and kills the concrete results from the launch-completion callback.
        """
        record = latest_live_launch_record(self)
        while record is not None:
            if record.state is LaunchRecordState.KILL_PENDING:
                self._refocus_kill_pending_launch_prompt(record)
                return
            if record.state is LaunchRecordState.RESOLVED_ACTION_PENDING:
                self._refocus_resolved_launch_action(record)
                return
            if record.state is LaunchRecordState.IN_FLIGHT:
                self._begin_inflight_deferred_kill(record)
                return
            if record.state is not LaunchRecordState.RESOLVED:
                self.notify(  # type: ignore[attr-defined]
                    f'"{record.display_name}" is still launching; '
                    "press ,X again when it appears"
                )
                return

            agents = tuple(
                getattr(self, "_agents_with_children", None)
                or getattr(self, "_agents", None)
                or ()
            )
            matched = _matched_agents_for_record(record, agents)
            if not matched:
                consume_launch_record(record)
                record = latest_live_launch_record(self)
                continue

            self._reveal_last_launch_target(matched[0].identity)
            begin_resolved_launch_action(record)

            def finish(initiated: bool, target_record: LaunchRecord = record) -> None:
                self._finish_resolved_launch_action(target_record, initiated=initiated)

            if len(matched) == 1:
                self._kill_and_edit_agent(  # type: ignore[attr-defined]
                    target=matched[0],
                    on_initiated=finish,
                )
            else:
                self._kill_and_edit_last_launch_set(
                    matched,
                    on_initiated=finish,
                )
            return

        self.notify(  # type: ignore[attr-defined]
            "No recent launch to kill and edit", severity="warning"
        )

    def _begin_inflight_deferred_kill(self, record: LaunchRecord) -> None:
        """Restore the prompt now and kill the launch when its proc completes."""
        self._mount_inflight_launch_prompt(record)
        _register_pending_launch_kill(self, record)
        self.notify(  # type: ignore[attr-defined]
            f'Will kill "{record.display_name}" when its launch finishes'
        )

    def _refocus_kill_pending_launch_prompt(self, record: LaunchRecord) -> None:
        """Re-focus the restored prompt; never advance to an older record."""
        mounted = getattr(self, "_mounted_prompt_bar", None)
        bar = mounted() if callable(mounted) else None
        if bar is not None:
            focus = getattr(bar, "focus", None)
            if callable(focus):
                focus()
            return
        self._mount_inflight_launch_prompt(record)

    def _refocus_resolved_launch_action(self, _record: LaunchRecord) -> None:
        """Keep a pending resolved action pinned to its launch record."""
        screen = getattr(self, "screen", None)
        focus = getattr(screen, "focus", None)
        if callable(focus):
            focus()

    def _finish_resolved_launch_action(
        self, record: LaunchRecord, *, initiated: bool
    ) -> None:
        """Consume only resolved records whose kill/dismiss action started."""
        if record.state is not LaunchRecordState.RESOLVED_ACTION_PENDING:
            return
        if initiated:
            consume_launch_record(record)
            return
        release_resolved_launch_action(record)

    def _mount_inflight_launch_prompt(self, record: LaunchRecord) -> None:
        """Seed the edit/relaunch prompt from the in-flight record's snapshot."""
        ctx = record.context
        if len(record.proc_ids) > 1:
            prompts = [
                record.submitted_prompts.get(proc_id, record.prompt)
                for proc_id in record.proc_ids
            ]
            self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                prompts,
                ctx.project_file,
                ctx.cl_name,
                ctx.is_project_agent,
            )
            return
        self._edit_and_relaunch_agent(  # type: ignore[attr-defined]
            record.prompt,
            ctx.project_file,
            ctx.cl_name,
            ctx.is_project_agent,
        )

    def _reveal_last_launch_target(self, target_identity: AgentIdentity) -> None:
        """Best-effort reveal of the first kill-and-edit target row.

        A missed reveal (ambiguous/filtered/gone target, or any error from
        the navigation machinery) only means the row does not scroll into
        view before the kill/dismiss + prompt-bar flow runs; it is not fatal
        to the action itself, so failures are swallowed rather than raised.
        """
        try:
            plan, _failure = prepare_agent_navigation_target(
                self, target_identity, require_current=False
            )
            if plan is None:
                return
            outcome = reveal_agent_navigation_target(self, plan)
            reveal = outcome.result
            if reveal is None:
                return
            panel_group = getattr(self, "_panel_group", None)
            if panel_group is not None:
                panel_group.focused_idx = reveal.panel_idx
            self._current_group_key = None
            self.current_idx = reveal.target_idx
            if hasattr(self, "current_attempt_number"):
                self.current_attempt_number = None
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh()
        except Exception:
            log.debug("Failed to reveal ,X last-launch target", exc_info=True)

    def _kill_and_edit_last_launch_set(
        self,
        agents: list[Agent],
        *,
        on_initiated: Callable[[bool], None] | None = None,
    ) -> None:
        """Kill/dismiss a resolved record's rows after one confirmation, then edit.

        Mirrors :meth:`AgentMarkedKillMixin._bulk_kill_marked_agents_and_edit`
        (same prompt resolution, confirmation rule, and relaunch-barrier
        machinery) but sources its agent set from a launch record's joined
        rows instead of the marked set.
        """
        identities = tuple(agent.identity for agent in agents)
        agents_snapshot = tuple(
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or ()
        )
        finished = False

        def finish(initiated: bool) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            if on_initiated is not None:
                on_initiated(initiated)

        def resolve_prompts() -> list[str | None]:
            return [
                prepare_kill_edit_agent_prompt(agent, agents_snapshot)
                for agent in agents
            ]

        def on_prompts_resolved(resolved: list[str | None]) -> None:
            current_agents = [
                resolve_agent_identity(self, identity) for identity in identities
            ]
            if any(agent is None for agent in current_agents):
                self.notify(  # type: ignore[attr-defined]
                    "A launched agent is no longer available; nothing killed",
                    severity="warning",
                )
                finish(False)
                return
            missing = sum(prompt is None for prompt in resolved)
            if missing:
                suffix = "s" if missing != 1 else ""
                self.notify(  # type: ignore[attr-defined]
                    f"{missing} launched agent{suffix} missing a prompt; "
                    "nothing killed",
                    severity="warning",
                )
                finish(False)
                return

            prompts = [prompt for prompt in resolved if prompt is not None]
            present_agents = [agent for agent in current_agents if agent is not None]
            first = present_agents[0]

            def on_confirm(
                _killable: list[Agent],
                _dismissable: list[Agent],
            ) -> None:
                confirmed_agents = [
                    resolve_agent_identity(self, identity) for identity in identities
                ]
                if any(agent is None for agent in confirmed_agents):
                    self.notify(  # type: ignore[attr-defined]
                        "A launched agent is no longer available; nothing killed",
                        severity="warning",
                    )
                    finish(False)
                    return
                from ..agents._core import DISMISSABLE_STATUSES

                exact_agents = [
                    agent for agent in confirmed_agents if agent is not None
                ]
                killable = [
                    agent
                    for agent in exact_agents
                    if not getattr(agent, "is_gate", False)
                    and agent.pid is not None
                    and agent.status not in DISMISSABLE_STATUSES
                ]
                dismissable = [
                    agent
                    for agent in exact_agents
                    if agent.status in DISMISSABLE_STATUSES
                    or (agent.pid is None and not getattr(agent, "is_gate", False))
                    or _is_gate_dismissable(agent)
                ]

                def mount_prompt_stack() -> None:
                    self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                        prompts,
                        first.project_file,
                        first.cl_name,
                        first.is_project_agent,
                    )

                from ._relaunch_barrier import (
                    open_relaunch_cleanup_barrier,
                    settle_relaunch_cleanup_barrier,
                )

                barrier = open_relaunch_cleanup_barrier(
                    self, f"kill-and-edit last launch ({len(exact_agents)} agent(s))"
                )
                settle: Callable[[], None] = lambda: settle_relaunch_cleanup_barrier(  # noqa: E731
                    self, barrier
                )
                if not self._do_bulk_kill_agents(  # type: ignore[attr-defined]
                    killable, dismissable, on_settled=settle
                ):
                    settle()
                    finish(False)
                    return
                finish(True)
                mount_prompt_stack()

            self._present_bulk_kill_modal(  # type: ignore[attr-defined]
                present_agents,
                on_confirm=on_confirm,
                on_cancel=lambda: finish(False),
            )

        schedule_relaunch_prompt_resolution(
            self,
            resolve_prompts,
            on_prompts_resolved,
            worker_name="last-launch-relaunch-prompts",
            failure_message="Unable to prepare last-launch relaunch prompts",
            on_error=lambda: finish(False),
        )


def apply_deferred_launch_kill_on_completion(
    app: object,
    proc_id: str,
    results: Sequence[AgentLaunchResult | None],
    *,
    failed: bool,
    admission_complete: bool = True,
) -> None:
    """Kill or abandon a ``KILL_PENDING`` record when *proc_id* becomes terminal.

    Called from the launch-completion callback after record stamping. A
    successful payload kills every returned result through the ordinary
    kill/dismiss path; a failure with no results discards the pending
    intent. The replacement-launch hold stays up until every proc on the
    record is terminal and any cleanup barrier opened here settles.
    """
    record = launch_record_for_proc_id(app, proc_id)
    if record is None or record.state is not LaunchRecordState.KILL_PENDING:
        return

    present = tuple(result for result in results if result is not None)
    if present:
        _execute_deferred_kill_for_results(
            app,
            record,
            present,
            admission_complete=admission_complete,
        )
    elif failed:
        _notify(
            app,
            f'Launch of "{record.display_name}" failed; kill-on-finish was cancelled',
            severity="warning",
        )

    if record_procs_are_terminal(record):
        _finish_pending_launch_kill(app, record)


def _register_pending_launch_kill(app: object, record: LaunchRecord) -> None:
    """Mark *record* ``KILL_PENDING`` and start its warn-and-release timer."""
    if record.state is LaunchRecordState.KILL_PENDING:
        return
    record.state = LaunchRecordState.KILL_PENDING
    timers = getattr(app, "_pending_launch_kill_timers", None)
    if timers is None:
        timers = {}
        cast(Any, app)._pending_launch_kill_timers = timers
    if record.proc_ids in timers:
        return
    set_timer = getattr(app, "set_timer", None)
    timer = None
    proc_ids = record.proc_ids
    if callable(set_timer):
        timer = set_timer(
            PENDING_LAUNCH_KILL_TIMEOUT_SECONDS,
            lambda: _pending_launch_kill_timed_out(app, proc_ids),
            name="pending-launch-kill-timeout",
        )
    timers[proc_ids] = timer


def _pending_launch_kill_timed_out(app: object, proc_ids: tuple[str, ...]) -> None:
    """Abandon auto-kill after the in-flight budget and release parked launches."""
    if not proc_ids:
        return
    record = launch_record_for_proc_id(app, proc_ids[0])
    if record is None or record.proc_ids != proc_ids:
        return
    if record.state is not LaunchRecordState.KILL_PENDING:
        return
    _stop_pending_kill_timer(app, record)
    release_kill_pending_launch_record(record)
    _notify(
        app,
        f'"{record.display_name}" took too long to finish launching; '
        "it will appear and can be killed with ,x",
        severity="warning",
    )
    release_relaunch_holds_if_idle(app)


def _finish_pending_launch_kill(app: object, record: LaunchRecord) -> None:
    """Clear pending-kill bookkeeping once every proc on *record* is terminal."""
    _stop_pending_kill_timer(app, record)
    if record.state is LaunchRecordState.KILL_PENDING:
        if record.results:
            consume_launch_record(record)
        else:
            release_kill_pending_launch_record(record)
    release_relaunch_holds_if_idle(app)


def _stop_pending_kill_timer(app: object, record: LaunchRecord) -> None:
    timers = getattr(app, "_pending_launch_kill_timers", None)
    if not timers:
        return
    timer = timers.pop(record.proc_ids, None)
    if timer is None:
        return
    stop = getattr(timer, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:
            pass


def _execute_deferred_kill_for_results(
    app: object,
    record: LaunchRecord,
    results: Sequence[AgentLaunchResult],
    *,
    admission_complete: bool,
) -> None:
    agents = _agents_for_deferred_kill(app, results)
    if not agents:
        _notify(
            app,
            f'Could not find launched agent(s) of "{record.display_name}" to kill',
            severity="warning",
        )
        return

    killable, dismissable = _split_deferred_kill_targets(agents)
    barrier = open_relaunch_cleanup_barrier(app, f"deferred kill {record.display_name}")
    settle: Callable[[], None] = lambda: settle_relaunch_cleanup_barrier(  # noqa: E731
        app, barrier
    )
    initiated = _initiate_deferred_kill(app, killable, dismissable, settle)
    if not initiated:
        settle()
    if not admission_complete:
        _notify(
            app,
            f'Killed launched units of "{record.display_name}"; '
            "gated units continue in the background",
            severity="warning",
        )


def _initiate_deferred_kill(
    app: object,
    killable: list[Agent],
    dismissable: list[Agent],
    settle: Callable[[], None],
) -> bool:
    """Start the ordinary kill/dismiss path. Return whether *settle* will fire."""
    if len(killable) + len(dismissable) == 1 and len(dismissable) == 1:
        dismiss = getattr(app, "_dismiss_done_agent", None)
        if callable(dismiss):
            return bool(dismiss(dismissable[0], on_settled=settle))
        return False
    if len(killable) + len(dismissable) == 1 and len(killable) == 1:
        kill = getattr(app, "_do_kill_agent", None)
        if callable(kill):
            return bool(kill(killable[0], on_settled=settle))
        return False
    bulk = getattr(app, "_do_bulk_kill_agents", None)
    if callable(bulk):
        return bool(bulk(killable, dismissable, on_settled=settle))
    return False


def _agents_for_deferred_kill(
    app: object, results: Sequence[AgentLaunchResult]
) -> list[Agent]:
    loaded = tuple(
        getattr(app, "_agents_with_children", None)
        or getattr(app, "_agents", None)
        or ()
    )
    matched: list[Agent] = []
    seen: set[object] = set()
    for result in results:
        agent = _agent_for_launch_result(loaded, result)
        if agent is None:
            agent = _synthetic_agent_from_launch_result(result)
            if agent is not None:
                _ensure_agent_visible(app, agent)
                loaded = tuple(
                    getattr(app, "_agents_with_children", None)
                    or getattr(app, "_agents", None)
                    or ()
                )
        if agent is None:
            continue
        identity = getattr(agent, "identity", id(agent))
        if identity in seen:
            continue
        seen.add(identity)
        matched.append(agent)
    return matched


def _ensure_agent_visible(app: object, agent: Agent) -> None:
    """Inject *agent* so bulk/single kill can see it in ``_agents_with_children``."""
    children = getattr(app, "_agents_with_children", None)
    if not isinstance(children, list):
        cast(Any, app)._agents_with_children = [agent]
        children = app._agents_with_children  # type: ignore[attr-defined]
    identity = getattr(agent, "identity", None)
    if identity is not None and any(
        getattr(existing, "identity", None) == identity for existing in children
    ):
        return
    children.append(agent)
    agents = getattr(app, "_agents", None)
    if isinstance(agents, list) and agent not in agents:
        agents.append(agent)


def _synthetic_agent_from_launch_result(result: AgentLaunchResult) -> Agent | None:
    """Build a killable row from a launch result when the Agents tab has none yet."""
    from sase.ace.tui.models._timestamps import normalize_to_14_digit
    from sase.ace.tui.models.agent import Agent, AgentType

    artifact_dir = artifact_dir_from_launch_result(result)
    artifacts_dir = (
        str(artifact_dir)
        if artifact_dir is not None
        else (result.artifacts_dir or None)
    )
    raw_suffix = normalize_to_14_digit(result.timestamp)
    if raw_suffix is None and artifacts_dir:
        from pathlib import Path

        raw_suffix = normalize_to_14_digit(Path(artifacts_dir).name)
    pid = result.pid if result.pid else None
    cl_name = result.cl_name or result.agent_name or "agent"
    status = "WAITING" if pid is None else "RUNNING"
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=result.project_file or "",
        status=status,
        start_time=None,
        pid=pid,
        raw_suffix=raw_suffix,
        artifacts_dir=artifacts_dir,
        agent_name=result.agent_name or cl_name,
        workspace_num=result.workspace_num or None,
        workflow=result.workflow_name or None,
    )


def _split_deferred_kill_targets(
    agents: Sequence[Agent],
) -> tuple[list[Agent], list[Agent]]:
    from ..agents._core import DISMISSABLE_STATUSES

    killable: list[Agent] = []
    dismissable: list[Agent] = []
    for agent in agents:
        status = getattr(agent, "status", "")
        if (
            status in _ADMISSION_DEFERRED_STATUSES
            or status in DISMISSABLE_STATUSES
            or getattr(agent, "pid", None) is None
        ):
            dismissable.append(agent)
        else:
            killable.append(agent)
    return killable, dismissable


def _notify(app: object, message: str, *, severity: str | None = None) -> None:
    notify = getattr(app, "notify", None)
    if callable(notify):
        if severity is None:
            notify(message)
        else:
            notify(message, severity=severity)


__all__ = [
    "KillAndEditLastLaunchMixin",
    "apply_deferred_launch_kill_on_completion",
]
