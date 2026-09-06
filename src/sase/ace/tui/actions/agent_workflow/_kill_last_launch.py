"""``,X`` — kill and edit the most recently launched agent this session."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from ._entry_relaunch import (
    prepare_kill_edit_agent_prompt,
    resolve_agent_identity,
    schedule_relaunch_prompt_resolution,
)
from ._kill_last_launch_deferred import (
    apply_deferred_launch_kill_on_completion,
    register_pending_launch_kill as _register_pending_launch_kill,
)
from ._kill_last_launch_targets import (
    ResolvedLaunchTargets as _ResolvedLaunchTargets,
    agent_for_launch_result as _agent_for_launch_result,
    is_gate_dismissable as _is_gate_dismissable,
    launch_result_key as _launch_result_key,
    mark_all_record_results_handled as _mark_all_record_results_handled,
    matched_agents_for_record as _matched_agents_for_record,
    notify_unresolved_launch_targets as _notify_unresolved_launch_targets,
    resolve_agents_for_record as _resolve_agents_for_record_impl,
)
from ._launch_records import (
    LaunchRecord,
    LaunchRecordState,
    begin_resolved_launch_action,
    consume_launch_record,
    latest_live_launch_record,
    release_resolved_launch_action,
)
from ._types import RelaunchOperation, current_prompt_session
from ..navigation._agent_reveal import (
    AgentIdentity,
    prepare_agent_navigation_target,
    reveal_agent_navigation_target,
)

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


def _resolve_agents_for_record(
    app: object,
    record: LaunchRecord,
    agents: Sequence[Agent],
) -> _ResolvedLaunchTargets:
    return _resolve_agents_for_record_impl(
        app,
        record,
        agents,
        match_record_agents=_matched_agents_for_record,
    )


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
            resolved = _resolve_agents_for_record(self, record, agents)
            if resolved.unresolved_count:
                _notify_unresolved_launch_targets(
                    self,
                    record,
                    resolved.unresolved_count,
                )
                return
            matched = list(resolved.agents)
            if not matched:
                if resolved.handled_count:
                    consume_launch_record(record)
                    record = latest_live_launch_record(self)
                    continue
                _notify_unresolved_launch_targets(self, record, 1)
                return

            operation = RelaunchOperation(
                f"kill-and-edit last launch {record.display_name}"
            )
            record.relaunch_operation = operation
            self._reveal_last_launch_target(matched[0].identity)
            begin_resolved_launch_action(record)

            def finish(initiated: bool, target_record: LaunchRecord = record) -> None:
                self._finish_resolved_launch_action(target_record, initiated=initiated)

            if len(matched) == 1:
                self._kill_and_edit_agent(  # type: ignore[attr-defined]
                    target=matched[0],
                    on_initiated=finish,
                    relaunch_operation=operation,
                )
            else:
                self._kill_and_edit_last_launch_set(
                    matched,
                    on_initiated=finish,
                    relaunch_operation=operation,
                )
            return

        self.notify(  # type: ignore[attr-defined]
            "No recent launch to kill and edit", severity="warning"
        )

    def _begin_inflight_deferred_kill(self, record: LaunchRecord) -> None:
        """Restore the prompt now and kill the launch when its proc completes."""
        operation = record.relaunch_operation
        if operation is None:
            operation = RelaunchOperation(
                f"kill-and-edit pending launch {record.display_name}"
            )
            record.relaunch_operation = operation
        self._mount_inflight_launch_prompt(record, relaunch_operation=operation)
        _register_pending_launch_kill(self, record, operation=operation)
        self.notify(  # type: ignore[attr-defined]
            f'Will kill "{record.display_name}" when its launch finishes'
        )

    def _refocus_kill_pending_launch_prompt(self, record: LaunchRecord) -> None:
        """Re-focus the restored prompt; never advance to an older record."""
        session = current_prompt_session(self)
        operation = record.relaunch_operation
        mounted = getattr(self, "_mounted_prompt_bar", None)
        bar = mounted() if callable(mounted) else None
        if (
            bar is not None
            and session is not None
            and session.relaunch_operation is operation
        ):
            focus = getattr(bar, "focus", None)
            if callable(focus):
                focus()
            return
        if operation is None:
            operation = RelaunchOperation(
                f"kill-and-edit pending launch {record.display_name}"
            )
            record.relaunch_operation = operation
        self._mount_inflight_launch_prompt(record, relaunch_operation=operation)

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
            _mark_all_record_results_handled(record)
            consume_launch_record(record)
            return
        release_resolved_launch_action(record)

    def _mount_inflight_launch_prompt(
        self,
        record: LaunchRecord,
        *,
        relaunch_operation: RelaunchOperation,
    ) -> None:
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
                relaunch_operation=relaunch_operation,
            )
            return
        self._edit_and_relaunch_agent(  # type: ignore[attr-defined]
            record.prompt,
            ctx.project_file,
            ctx.cl_name,
            ctx.is_project_agent,
            relaunch_operation=relaunch_operation,
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
        relaunch_operation: RelaunchOperation | None = None,
    ) -> None:
        """Kill/dismiss a resolved record's rows after one confirmation, then edit.

        Mirrors :meth:`AgentMarkedKillMixin._bulk_kill_marked_agents_and_edit`
        (same prompt resolution, confirmation rule, and relaunch-barrier
        machinery) but sources its agent set from a launch record's joined
        rows instead of the marked set.
        """
        if relaunch_operation is None:
            relaunch_operation = RelaunchOperation(
                f"kill-and-edit last launch ({len(agents)} agent(s))"
            )
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
                        relaunch_operation=relaunch_operation,
                    )

                from ._relaunch_barrier import (
                    open_relaunch_cleanup_barrier,
                    settle_relaunch_cleanup_barrier,
                )

                barrier = open_relaunch_cleanup_barrier(
                    self,
                    f"kill-and-edit last launch ({len(exact_agents)} agent(s))",
                    operation=relaunch_operation,
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


__all__ = [
    "KillAndEditLastLaunchMixin",
    "apply_deferred_launch_kill_on_completion",
]
