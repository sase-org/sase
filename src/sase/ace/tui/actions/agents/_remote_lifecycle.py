"""Remote fleet stop/retry/fork actions with optimistic UI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ..proc_actions import TrackedProcCompletion


def is_remote_fleet_agent(agent: Agent | None) -> bool:
    """Return whether *agent* is a viewer-only remote fleet row."""
    return bool(agent is not None and getattr(agent, "fleet_origin_alias", None))


def remote_capability_enabled(agent: Agent, capability: str) -> bool:
    """Return whether *agent* advertises a lifecycle capability."""
    capabilities = getattr(agent, "fleet_capabilities", None)
    if not isinstance(capabilities, Mapping):
        return False
    resource = capabilities.get("resource")
    if isinstance(resource, Sequence) and not isinstance(resource, (str, bytes)):
        return capability in resource
    return (
        capability in capabilities.values()
        if isinstance(capabilities, Mapping)
        else False
    )


class AgentRemoteLifecycleMixin:
    """Submit remote lifecycle mutations through the durable adapter."""

    def _submit_remote_lifecycle(
        self,
        agents: Sequence[Agent],
        *,
        kind: str,
        fork_prompt: str | None = None,
        confirm_message: str | None = None,
    ) -> None:
        from sase.dispatch.config import load_dispatch_config, remote_dispatch_enabled
        from ..agent_durable import submit_machine_agent_action

        if not remote_dispatch_enabled():
            self.notify(  # type: ignore[attr-defined]
                "remote dispatch is disabled; enable `remote_dispatch` for this invocation",
                severity="warning",
            )
            return
        if not agents:
            self.notify("No remote agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        try:
            config = load_dispatch_config()
        except Exception as exc:
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return
        machines = config.machine_by_alias()
        groups: dict[str, list[Agent]] = {}
        for agent in agents:
            alias = getattr(agent, "fleet_origin_alias", None)
            if not alias:
                continue
            machine = machines.get(alias)
            if machine is None or machine.quarantined:
                self.notify(  # type: ignore[attr-defined]
                    f"{alias} is not an enrolled non-quarantined machine",
                    severity="warning",
                )
                continue
            groups.setdefault(alias, []).append(agent)
        if not groups:
            return
        if confirm_message:
            self.notify(confirm_message)  # type: ignore[attr-defined]
        for alias, group in groups.items():
            self._apply_remote_optimistic_state(group, kind)
            payload = {
                "alias": alias,
                "kind": kind,
                "follow": kind in {"retry", "fork"},
                "fork_prompt": fork_prompt,
                "targets": [_snapshot_for_agent(agent) for agent in group],
            }
            names = tuple(
                str(agent.agent_name or agent.raw_suffix)
                for agent in group
                if agent.agent_name or agent.raw_suffix
            )
            submitted = submit_machine_agent_action(
                self,
                kind=kind,
                alias=alias,
                agent_names=names,
                payload=payload,
                display_name=f"{kind} on {alias}",
                on_complete=self._on_remote_lifecycle_complete,
            )
            if not submitted:
                self.notify(  # type: ignore[attr-defined]
                    f"Unable to submit {kind} on {alias}",
                    severity="error",
                )

    def _confirm_remote_stop(self, agents: Sequence[Agent]) -> None:
        from ...modals import ConfirmKillModal

        alias = getattr(agents[0], "fleet_origin_alias", "remote")
        names = ", ".join(
            str(agent.agent_name or agent.raw_suffix)
            for agent in agents
            if agent.agent_name or agent.raw_suffix
        )
        description = f"Stop {names} on {alias}?"

        def on_dismiss(confirmed: bool | None) -> None:
            selected = self._get_selected_agent()  # type: ignore[attr-defined]
            if not confirmed:
                return
            current = [
                agent
                for agent in agents
                if is_remote_fleet_agent(self._agent_by_identity(agent.identity))
            ]
            if selected is not None:
                current = [
                    agent
                    for agent in current
                    if agent.identity == selected.identity or len(agents) > 1
                ] or current
            self._submit_remote_lifecycle(current, kind="stop")

        self.push_screen(ConfirmKillModal(description), on_dismiss)  # type: ignore[attr-defined]

    def _submit_remote_fork(self, agent: Agent, instruction: str) -> None:
        self._submit_remote_lifecycle(
            [agent],
            kind="fork",
            fork_prompt=instruction,
        )

    def action_retry_remote_agent(self) -> None:
        """Retry the selected remote fleet agent on its owning host."""
        agent = self._reselected_remote_agent()
        if agent is None:
            return
        self._submit_remote_lifecycle([agent], kind="retry")

    def _reselected_remote_agent(self) -> Agent | None:
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if not is_remote_fleet_agent(agent):
            self.notify("Select a remote fleet agent", severity="warning")  # type: ignore[attr-defined]
            return None
        return agent

    def _agent_by_identity(self, identity: tuple[object, ...]) -> Agent | None:
        for agent in getattr(self, "_agents", []):
            if agent.identity == identity:
                return agent
        return None

    def _apply_remote_optimistic_state(
        self, agents: Sequence[Agent], kind: str
    ) -> None:
        label = {"stop": "stopping", "retry": "retrying", "fork": "forking"}[kind]
        overrides = getattr(self, "_agent_status_overrides", None)
        for agent in agents:
            live = self._agent_by_identity(agent.identity) or agent
            live.status = label
            live.fleet_bounded_intent = f"{kind} requested"
            if isinstance(overrides, dict):
                overrides[live.identity] = label
        refilter = getattr(self, "_refilter_agents", None)
        if callable(refilter):
            refilter()

    def _on_remote_lifecycle_complete(
        self,
        completion: TrackedProcCompletion[Any],
    ) -> None:
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        _ = selected
        payload = completion.payload if isinstance(completion.payload, Mapping) else {}
        results = payload.get("results")
        if isinstance(results, list) and results:
            for item in results:
                if isinstance(item, Mapping):
                    self.notify(  # type: ignore[attr-defined]
                        str(item.get("message") or "remote mutation settled")
                    )
        elif completion.message:
            self.notify(completion.message)  # type: ignore[attr-defined]
        overrides = getattr(self, "_agent_status_overrides", None)
        if isinstance(overrides, dict):
            for identity, status in list(overrides.items()):
                if status in {"stopping", "retrying", "forking"}:
                    overrides.pop(identity, None)
        self._schedule_agents_fleet_refresh(source="remote_mutation", force=True)  # type: ignore[attr-defined]


def _snapshot_for_agent(agent: Agent) -> dict[str, Any]:
    row_revision = getattr(agent, "fleet_row_revision", None)
    if not isinstance(row_revision, Mapping):
        revision = getattr(agent, "fleet_revision", None)
        logical_key = getattr(agent, "fleet_logical_key", None)
        if logical_key is not None and revision is not None:
            row_revision = {
                "schema_version": 1,
                "logical_key": logical_key,
                "revision": int(revision),
            }
        else:
            row_revision = None
    return {
        "alias": agent.fleet_origin_alias,
        "origin_installation_id": agent.fleet_origin_installation_id,
        "exact_locator": getattr(agent, "fleet_exact_locator", None),
        "row_revision": row_revision,
        "capabilities": getattr(agent, "fleet_capabilities", None) or {},
    }


__all__ = [
    "AgentRemoteLifecycleMixin",
    "is_remote_fleet_agent",
    "remote_capability_enabled",
]
