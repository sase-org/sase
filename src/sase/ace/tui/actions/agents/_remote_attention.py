"""Remote fleet attention: toast dedupe and the answer/approve action."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.dispatch.attention_notices import decide_and_persist_attention_notices

from ...util.pump_tasks import spawn_pump_free_task
from ..agent_durable import submit_machine_attention_action
from ._remote_lifecycle import is_remote_fleet_agent, remote_capability_enabled

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.fleet_agents import FleetRowsProjection
    from ..proc_actions import TrackedProcCompletion

log = logging.getLogger(__name__)

_ATTENTION_CAPABILITY_BY_KIND = {
    "question": "attention.answer_question",
    "gate": "attention.approve_gate",
}


def has_pending_remote_attention(agent: Agent | None) -> bool:
    """Return whether *agent* carries a pending, capability-backed attention entry."""
    if not is_remote_fleet_agent(agent):
        return False
    attention = getattr(agent, "fleet_attention", None)
    if not isinstance(attention, Mapping) or attention.get("state") != "pending":
        return False
    capability = _ATTENTION_CAPABILITY_BY_KIND.get(str(attention.get("kind")))
    return bool(capability and remote_capability_enabled(agent, capability))  # type: ignore[arg-type]


class RemoteAttentionMixin:
    """Toast dedupe for pending remote attention and the answer/approve action."""

    def _announce_remote_attention(self, projection: FleetRowsProjection) -> None:
        pending = _pending_attention_rows(projection)
        if not pending:
            return
        task = spawn_pump_free_task(
            self,
            self._announce_remote_attention_async(pending),
            name="sase-agents-fleet-attention-notice",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            log.debug("could not schedule remote attention notice task")

    async def _announce_remote_attention_async(
        self,
        pending: list[tuple[Agent, dict[str, Any]]],
    ) -> None:
        entries = [entry for _row, entry in pending]
        try:
            to_announce = await asyncio.to_thread(
                decide_and_persist_attention_notices, entries
            )
        except Exception:
            log.debug("attention notice decision failed", exc_info=True)
            return
        if not to_announce:
            return
        by_request_id: dict[str, Agent] = {}
        for row, entry in pending:
            request_id = _request_id(entry)
            if request_id:
                by_request_id[request_id] = row
        for entry in to_announce:
            request_id = _request_id(entry)
            toast_row = by_request_id.get(request_id) if request_id else None
            alias = getattr(toast_row, "fleet_origin_alias", None) or "a remote host"
            kind = entry.get("kind")
            noun = "question" if kind == "question" else "gate"
            title = entry.get("title") or f"Pending {noun}"
            self.notify(f"{alias}: {title}")  # type: ignore[attr-defined]

    def action_answer_remote_attention(self) -> None:
        """Answer or approve the selected row's pending remote attention."""
        from sase.dispatch.config import remote_dispatch_enabled

        if not remote_dispatch_enabled():
            self.notify(  # type: ignore[attr-defined]
                "remote dispatch is disabled; enable `remote_dispatch` for this invocation",
                severity="warning",
            )
            return
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if not has_pending_remote_attention(agent):
            self.notify(  # type: ignore[attr-defined]
                "Select a remote row with a pending question or gate",
                severity="warning",
            )
            return
        alias = getattr(agent, "fleet_origin_alias", None)
        attention = getattr(agent, "fleet_attention", None)
        if not alias or not isinstance(attention, Mapping):
            return
        attention = dict(attention)
        identity = agent.identity  # type: ignore[union-attr]

        from ...modals.remote_attention_modal import RemoteAttentionModal

        def _on_dismiss(intent: dict[str, Any] | None) -> None:
            if not intent:
                return
            current = self._agent_by_identity(identity)  # type: ignore[attr-defined]
            if not has_pending_remote_attention(current):
                self.notify(  # type: ignore[attr-defined]
                    "Attention request is no longer pending",
                    severity="warning",
                )
                return
            self._submit_remote_attention_answer(current, alias, attention, intent)

        self.push_screen(  # type: ignore[attr-defined]
            RemoteAttentionModal(alias=alias, entry=attention),
            _on_dismiss,
        )

    def _submit_remote_attention_answer(
        self,
        agent: Agent,
        alias: str,
        attention: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> None:
        request_id = _request_id(attention)
        if not request_id:
            return
        from sase.dispatch.config import load_dispatch_config

        machine = load_dispatch_config().machine_by_alias().get(alias)
        if machine is None or machine.quarantined:
            reason = (
                getattr(machine, "quarantine_reason", None) or "machine is quarantined"
                if machine is not None
                else "machine is not enrolled"
            )
            self.notify(f"{alias}: {reason}", severity="error")  # type: ignore[attr-defined]
            return
        kind = str(intent.get("kind") or attention.get("kind") or "answer")
        # The modal only decides the user's selection/answer; the request's
        # own identity and observed revision come from the entry ACE already
        # read, so the durable runner can trust this sidecar payload outright
        # instead of re-reading attention itself.
        full_intent: dict[str, Any] = {
            "kind": kind,
            "request_key": dict(attention.get("request_key") or {}),
            "observed_revision": attention.get("revision"),
            "selected_option_ids": [],
            "feedback": None,
            "question_choice": None,
            "question_index": None,
            "selected_option_id": None,
            "selected_option_label": None,
            "selected_option_index": None,
            "custom_answer": None,
            "global_note": None,
        }
        full_intent.update(
            {key: value for key, value in intent.items() if key != "kind"}
        )
        label = "answering" if kind == "question" else "approving"
        live = self._agent_by_identity(agent.identity) or agent  # type: ignore[attr-defined]
        live.status = label
        overrides = getattr(self, "_agent_status_overrides", None)
        if isinstance(overrides, dict):
            overrides[live.identity] = label
        refilter = getattr(self, "_refilter_agents", None)
        if callable(refilter):
            refilter()
        submitted = submit_machine_attention_action(
            self,
            kind="approve" if kind == "gate" else "answer",
            alias=alias,
            request_id=request_id,
            payload={
                "alias": alias,
                "request_id": request_id,
                "intent": full_intent,
            },
            display_name=f"Answering {alias}",
            on_complete=self._on_remote_attention_complete,
        )
        if not submitted:
            self.notify(f"Unable to submit answer on {alias}", severity="error")  # type: ignore[attr-defined]

    def _on_remote_attention_complete(
        self,
        completion: TrackedProcCompletion[Any],
    ) -> None:
        payload = completion.payload if isinstance(completion.payload, Mapping) else {}
        message = payload.get("message") if isinstance(payload, Mapping) else None
        notice = str(message) if message else (completion.message or "Answer submitted")
        self.notify(notice)  # type: ignore[attr-defined]
        overrides = getattr(self, "_agent_status_overrides", None)
        if isinstance(overrides, dict):
            for identity, status in list(overrides.items()):
                if status in {"answering", "approving"}:
                    overrides.pop(identity, None)
        self._schedule_agents_fleet_refresh(source="remote_attention", force=True)  # type: ignore[attr-defined]


def _request_id(entry: Mapping[str, Any]) -> str | None:
    request_key = entry.get("request_key")
    if not isinstance(request_key, Mapping):
        return None
    request_id = request_key.get("request_id")
    return request_id if isinstance(request_id, str) and request_id else None


def _pending_attention_rows(
    projection: FleetRowsProjection,
) -> list[tuple[Agent, dict[str, Any]]]:
    seen: set[str] = set()
    result: list[tuple[Agent, dict[str, Any]]] = []
    for row in (*projection.focus_rows, *projection.fleet_rows):
        attention = getattr(row, "fleet_attention", None)
        if not isinstance(attention, Mapping) or attention.get("state") != "pending":
            continue
        request_id = _request_id(attention)
        if not request_id or request_id in seen:
            continue
        seen.add(request_id)
        result.append((row, dict(attention)))
    return result


__all__ = [
    "RemoteAttentionMixin",
    "has_pending_remote_attention",
]
