"""Unified Agents row projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent
    from ...models.agent import AgentType

_AGENT_SIGNATURE_SKIP_FIELDS = frozenset(
    {
        "attempt_history",
        "clan_context",
        "family_container",
        "feedback_plan_paths",
        "followup_agents",
        "imported_source_owner",
        "retry_chain_siblings",
        "runtime_children",
        "wait_display_source",
    }
)


def _freeze_projection_value(value: Any) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze_projection_value(item))
            for key, item in sorted(value.items(), key=lambda entry: repr(entry[0]))
        )
    if isinstance(value, set | frozenset):
        return tuple(
            sorted((_freeze_projection_value(item) for item in value), key=repr)
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(_freeze_projection_value(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return repr(value)
    return value


def _agent_projection_signature(agent: Agent) -> tuple[tuple[str, object], ...]:
    return tuple(
        (
            field.name,
            _freeze_projection_value(getattr(agent, field.name)),
        )
        for field in fields(agent)
        if field.name not in _AGENT_SIGNATURE_SKIP_FIELDS
    )


def _agents_projection_signature(agents: list[Agent]) -> tuple[object, ...]:
    return tuple(_agent_projection_signature(agent) for agent in agents)


class AgentFleetProjectionMixin:
    """Unified Agents row reprojection."""

    if TYPE_CHECKING:
        current_agents_subtab: AgentsSubTab
        current_tab: str
        current_idx: int
        _agents: list[Agent]
        _agents_with_children: list[Agent]
        _agents_local_with_children: list[Agent]
        _agents_local_visible: list[Agent]
        _agents_fleet_rows: list[Agent]
        _agents_fleet_focus_rows: list[Agent]
        _agents_fleet_applied_projection_signature: object | None
        _agents_refresh_active_source: str

    def watch_current_agents_subtab(
        self,
        old_mode: AgentsSubTab,
        new_mode: AgentsSubTab,
    ) -> None:
        """Normalize restored legacy Agents mode state to the unified list."""
        if old_mode == new_mode:
            return
        if new_mode == "fleet":
            self.current_agents_subtab = "focus"
            return
        self._reproject_agents_from_current_mode(source="mode_switch")
        self._schedule_agents_fleet_refresh(  # type: ignore[attr-defined]
            source="mode_switch",
            force=True,
        )

    def action_connect_agent_machine(self) -> None:
        """Open the persistent Machines administration pane."""
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")

    def action_setup_agent_machine(self) -> None:
        """Open enrollment guidance while no remote machine is configured."""
        fleet_mode_available = getattr(self, "_fleet_mode_available", None)
        if callable(fleet_mode_available) and fleet_mode_available():
            self.notify(  # type: ignore[attr-defined]
                "Remote machines are already enrolled; run 'sase machine init' "
                "to rescan, or 'sase machine list' / 'sase machine status' "
                "from a shell for details"
            )
            return
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")
            return
        visible_after_enrollment = (
            "The Agents list includes it once a machine is enrolled."
        )
        self.notify(  # type: ignore[attr-defined]
            "No remote machines are enrolled. On the target, run "
            "'sase machine bootstrap --json' into a protected file. On this "
            "controller, run 'sase machine init -B <file>' to discover, enroll, "
            f"and verify. {visible_after_enrollment}",
            timeout=12,
        )

    def _set_agents_subtab(self, mode: str) -> None:
        del mode
        self.current_agents_subtab = "focus"

    def _project_agents_for_current_mode_after_load(
        self,
        local_unfiltered: list[Agent],
        local_visible: list[Agent],
    ) -> tuple[list[Agent], list[Agent]]:
        self._agents_local_with_children = list(local_unfiltered)
        self._agents_local_visible = list(local_visible)
        return (
            self._agents_source_for_current_mode(local_unfiltered),
            self._agents_source_for_current_mode(local_visible),
        )

    def _sync_agents_local_source_from_current(self) -> None:
        """Mirror local-only rows after existing in-memory mutations."""
        self._agents_local_with_children = self._local_agents_from_mixed(
            getattr(self, "_agents_with_children", [])
        )
        self._agents_local_visible = self._local_agents_from_mixed(
            getattr(self, "_agents", [])
        )

    def _agents_source_for_current_mode(self, local_agents: list[Agent]) -> list[Agent]:
        from ...models._agent_tree import project_mixed_agent_tree

        fleet_rows = self._fleet_rows_with_dispatch_provisionals(  # type: ignore[attr-defined]
            list(getattr(self, "_agents_fleet_rows", []))
        )
        return project_mixed_agent_tree(local_agents, fleet_rows)

    @staticmethod
    def _local_agents_from_mixed(agents: list[Agent]) -> list[Agent]:
        return [
            agent for agent in agents if not getattr(agent, "fleet_origin_alias", None)
        ]

    def _local_base_for_current_projection(self) -> list[Agent]:
        local_cache = getattr(self, "_agents_local_with_children", None)
        if local_cache is not None:
            return list(local_cache)
        return self._local_agents_from_mixed(
            list(getattr(self, "_agents_with_children", []))
        )

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        force: bool = False,
        selected_identity: tuple[AgentType, str, str | None] | None = None,
    ) -> None:
        if selected_identity is None and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        previous_agents = list(getattr(self, "_agents", []))
        local_base = self._local_base_for_current_projection()
        projected_agents = self._agents_source_for_current_mode(local_base)
        projection_signature = _agents_projection_signature(projected_agents)
        if (
            source == "fleet_refresh"
            and not force
            and self.current_tab == "agents"
            and (previous_agents or not projected_agents)
            and projection_signature
            == getattr(self, "_agents_fleet_applied_projection_signature", None)
        ):
            self._update_agents_header()  # type: ignore[attr-defined]
            return
        self._agents_with_children = projected_agents
        self._agents = list(self._agents_with_children)
        self._agents_refresh_active_source = source  # type: ignore[attr-defined]
        try:
            self._finalize_agent_list(  # type: ignore[attr-defined]
                self.current_tab == "agents",
                selected_identity,
                save_unfiltered=False,
                previous_agents=previous_agents,
            )
        finally:
            self._agents_refresh_active_source = "unknown"  # type: ignore[attr-defined]
        self._agents_fleet_applied_projection_signature = projection_signature
        self._update_agents_header()  # type: ignore[attr-defined]

    def _fleet_mode_available(self) -> bool:
        return bool(
            getattr(self, "_agents_fleet_available", False)
            or getattr(self, "_agents_fleet_rows", ())
            or getattr(self, "_agents_fleet_focus_rows", ())
            or getattr(self, "_agents_dispatch_provisional_rows", {})
        )


__all__ = ["AgentFleetProjectionMixin"]
