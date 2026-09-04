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
from ._launch_delta import artifact_dir_from_launch_result
from ._launch_records import (
    LaunchRecord,
    LaunchRecordState,
    consume_launch_record,
    latest_live_launch_record,
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


def _agent_for_launch_result(
    agents: Sequence[Agent], result: AgentLaunchResult
) -> Agent | None:
    """Return the loaded row this session's own launch produced, if any."""
    target = artifact_dir_from_launch_result(result)
    if target is None:
        return None
    target_str = str(target)
    for agent in agents:
        if agent.get_artifacts_dir() == target_str:
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

    def _kill_and_edit_last_launch(self) -> None:
        """Kill and edit the newest launch record this session can still target.

        Marks are ignored by design: ``,X`` always targets the most recently
        accepted launch, never the focused or marked row(s). A record whose
        rows were already killed/dismissed by hand is skipped in favor of the
        next live record. An in-flight launch (no row yet) gets an interim
        toast for now; Phase 3 replaces that branch with a deferred kill.
        """
        record = latest_live_launch_record(self)
        while record is not None:
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
            consume_launch_record(record)
            if len(matched) == 1:
                self._kill_and_edit_agent(target=matched[0])  # type: ignore[attr-defined]
            else:
                self._kill_and_edit_last_launch_set(matched)
            return

        self.notify(  # type: ignore[attr-defined]
            "No recent launch to kill and edit", severity="warning"
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
            self._current_group_key = None  # type: ignore[attr-defined]
            self.current_idx = reveal.target_idx  # type: ignore[attr-defined]
            if hasattr(self, "current_attempt_number"):
                self.current_attempt_number = None  # type: ignore[attr-defined]
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh()
        except Exception:
            log.debug("Failed to reveal ,X last-launch target", exc_info=True)

    def _kill_and_edit_last_launch_set(self, agents: list[Agent]) -> None:
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
                return
            missing = sum(prompt is None for prompt in resolved)
            if missing:
                suffix = "s" if missing != 1 else ""
                self.notify(  # type: ignore[attr-defined]
                    f"{missing} launched agent{suffix} missing a prompt; "
                    "nothing killed",
                    severity="warning",
                )
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
                    return
                mount_prompt_stack()

            self._present_bulk_kill_modal(  # type: ignore[attr-defined]
                present_agents, on_confirm=on_confirm
            )

        schedule_relaunch_prompt_resolution(
            self,
            resolve_prompts,
            on_prompts_resolved,
            worker_name="last-launch-relaunch-prompts",
            failure_message="Unable to prepare last-launch relaunch prompts",
        )


__all__ = ["KillAndEditLastLaunchMixin"]
