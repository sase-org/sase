"""Provisional dispatch-launch rows for the Agents fleet view."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from ...models.dispatch_launch_rows import (
    dispatch_operation_id,
    dispatch_provisional_agent_from_payload,
    dispatch_provisional_agent_from_preview,
    dispatch_row_reconciled,
    mark_dispatch_row_checking,
    mark_dispatch_row_unknown,
)

if TYPE_CHECKING:
    from sase.dispatch.launch import RemoteDispatchLaunchPreview

    from ...models import Agent
    from ...models.agent import AgentType


class AgentFleetDispatchLaunchMixin:
    """In-memory rows for source-side `%dispatch` launch submission state."""

    if TYPE_CHECKING:
        _agents_dispatch_provisional_rows: dict[str, Agent]
        _dispatch_launch_prompt_to_operation: dict[str, str]
        _agents_fleet_available: bool

        def _get_selected_agent(self) -> Agent | None: ...
        def _reproject_agents_from_current_mode(
            self,
            *,
            source: str,
            selected_identity: tuple[AgentType, str, str | None] | None = None,
        ) -> None: ...
        def _submit_launch_proc(
            self,
            *,
            display_name: str,
            cl_name: str,
            project_file: str,
            prompt: str,
            dedup_key: str | None = None,
            submitted_prompt: str | None = None,
            extra_payload: dict[str, object] | None = None,
        ) -> object | None: ...
        def notify(
            self,
            message: str,
            *,
            title: str = "",
            severity: Literal["information", "warning", "error"] = "information",
            timeout: float | None = None,
            markup: bool = True,
        ) -> None: ...

    def action_check_dispatch_launch_outcome(self) -> None:
        """Reconcile the selected provisional dispatch launch operation."""
        agent = self._get_selected_agent()
        if agent is None:
            self.notify("Select a provisional dispatch launch row")
            return
        operation_id = dispatch_operation_id(agent)
        if operation_id is None:
            self.notify("Select a provisional dispatch launch row")
            return
        prompt = getattr(agent, "fleet_dispatch_prompt", None)
        payload = getattr(agent, "fleet_dispatch_payload", None)
        if not isinstance(prompt, str) or not prompt:
            self.notify("Dispatch launch prompt is unavailable", severity="warning")
            return
        if not isinstance(payload, Mapping):
            self.notify(
                "Dispatch launch source context is unavailable", severity="warning"
            )
            return
        extra_payload = dict(payload)
        extra_payload["request_id"] = operation_id
        extra_payload["follow"] = True
        mark_dispatch_row_checking(agent)
        self._reproject_agents_from_current_mode(
            source="dispatch_check",
            selected_identity=agent.identity,
        )
        proc = self._submit_launch_proc(
            display_name=f"check launch {agent.fleet_origin_alias}",
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            prompt=prompt,
            dedup_key=f"dispatch-check:{operation_id}",
            extra_payload=extra_payload,
            submitted_prompt=prompt,
        )
        if proc is None:
            self.notify("Unable to submit dispatch outcome check", severity="error")

    def _record_dispatch_launch_preview(
        self,
        preview: RemoteDispatchLaunchPreview,
        *,
        prompt: str,
        payload: Mapping[str, object],
    ) -> None:
        """Insert the immediate provisional row for an accepted local submit."""
        row = dispatch_provisional_agent_from_preview(
            preview,
            prompt=prompt,
            payload=payload,
        )
        operation_id = dispatch_operation_id(row)
        if operation_id is None:
            return
        self._agents_dispatch_provisional_rows[operation_id] = row
        self._dispatch_launch_prompt_to_operation[prompt] = operation_id
        self._agents_fleet_available = True
        self._reproject_agents_from_current_mode(
            source="dispatch_preview",
            selected_identity=row.identity,
        )

    def _record_dispatch_launch_outcome(
        self,
        dispatch: Mapping[str, object],
        *,
        prompt: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        """Update a provisional row from the durable dispatch launch result."""
        operation = dispatch.get("operation_key")
        operation_id = None
        if isinstance(operation, Mapping):
            raw_operation_id = operation.get("operation_id")
            if isinstance(raw_operation_id, str) and raw_operation_id:
                operation_id = raw_operation_id
        if operation_id is None:
            return
        existing = self._agents_dispatch_provisional_rows.get(operation_id)
        if payload is None and existing is not None:
            existing_payload = getattr(existing, "fleet_dispatch_payload", None)
            if isinstance(existing_payload, Mapping):
                payload = existing_payload
        if prompt is None and existing is not None:
            existing_prompt = getattr(existing, "fleet_dispatch_prompt", None)
            if isinstance(existing_prompt, str):
                prompt = existing_prompt
        row = dispatch_provisional_agent_from_payload(
            dispatch,
            prompt=prompt,
            payload=payload,
        )
        if row is None:
            return
        self._agents_dispatch_provisional_rows[operation_id] = row
        if prompt:
            self._dispatch_launch_prompt_to_operation[prompt] = operation_id
        self._agents_fleet_available = True
        self._reproject_agents_from_current_mode(
            source="dispatch_outcome",
            selected_identity=row.identity,
        )

    def _mark_dispatch_launch_unknown_for_prompt(
        self,
        prompt: str | None,
        message: str,
    ) -> None:
        """Show an explicit check-outcome affordance after uncertain completion."""
        if not prompt:
            return
        operation_id = self._dispatch_launch_prompt_to_operation.get(prompt)
        if operation_id is None:
            return
        row = self._agents_dispatch_provisional_rows.get(operation_id)
        if row is None:
            return
        mark_dispatch_row_unknown(row, message)
        self._reproject_agents_from_current_mode(
            source="dispatch_unknown",
            selected_identity=row.identity,
        )

    def _fleet_rows_with_dispatch_provisionals(
        self,
        rows: list[Agent],
    ) -> list[Agent]:
        """Append unreconciled provisional dispatch rows to fleet rows."""
        provisionals = getattr(self, "_agents_dispatch_provisional_rows", {})
        if not provisionals:
            return rows
        retained: list[Agent] = []
        for operation_id, row in list(provisionals.items()):
            if dispatch_row_reconciled(row, rows):
                provisionals.pop(operation_id, None)
                continue
            retained.append(row)
        return [*rows, *retained]


__all__ = ["AgentFleetDispatchLaunchMixin"]
