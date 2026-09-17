"""Remote fleet attention: toast dedupe and the answer/approve action."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.dispatch.attention_inbox import (
    REMOTE_ATTENTION_NOTIFICATION_ACTION,
    fetch_remote_attention_inventory,
    reconcile_remote_attention_inbox,
    remote_attention_from_notification,
)
from sase.dispatch.attention_notices import decide_and_persist_attention_notices

from ...util.pump_tasks import spawn_pump_free_task
from ..agent_durable import submit_machine_attention_action
from ._remote_lifecycle import is_remote_fleet_agent, remote_capability_enabled

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.fleet_agents import FleetRowsProjection
    from ..proc_actions import TrackedProcCompletion

log = logging.getLogger(__name__)

FLEET_ATTENTION_INVENTORY_NETWORK_REFRESH_SECONDS = 60.0

_ATTENTION_CAPABILITY_BY_KIND = {
    "question": "attention.answer_question",
    "gate": "attention.approve_gate",
}


@dataclass(frozen=True)
class _FleetAttentionInventoryPollResult:
    """Trace-friendly summary of one remote attention inventory poll."""

    changed: bool = False
    polls: int = 0
    cache_polls: int = 0
    network_polls: int = 0
    duration_ms: float = 0.0
    modes: tuple[str, ...] = ()
    outcome: str = "unchanged"
    coalesced_requests: int = 0
    skipped: bool = False
    error: bool = False

    def __bool__(self) -> bool:
        return self.changed


def has_pending_remote_attention(agent: Agent | None) -> bool:
    """Return whether *agent* carries a pending, capability-backed attention entry."""
    if not is_remote_fleet_agent(agent):
        return False
    attention = getattr(agent, "fleet_attention", None)
    if not isinstance(attention, Mapping) or attention.get("state") != "pending":
        return False
    capability = _ATTENTION_CAPABILITY_BY_KIND.get(str(attention.get("kind")))
    return bool(capability and remote_capability_enabled(agent, capability))  # type: ignore[arg-type]


def handle_remote_attention_notification(app: Any, notification: Any) -> bool:
    """Open a remote attention notification in the reusable answer modal."""
    opener = getattr(app, "_open_remote_attention_notification", None)
    if not callable(opener):
        return False
    return bool(opener(notification))


class RemoteAttentionMixin:
    """Toast dedupe for pending remote attention and the answer/approve action."""

    def _fleet_attention_inventory_network_due(
        self,
        *,
        now_mono: float | None = None,
    ) -> bool:
        """Return whether the slower network inventory recompute is due."""
        now = time.monotonic() if now_mono is None else now_mono
        interval = getattr(
            self,
            "_fleet_attention_inventory_network_refresh_seconds",
            FLEET_ATTENTION_INVENTORY_NETWORK_REFRESH_SECONDS,
        )
        try:
            interval_seconds = float(interval)
        except (TypeError, ValueError):
            interval_seconds = FLEET_ATTENTION_INVENTORY_NETWORK_REFRESH_SECONDS
        if interval_seconds <= 0:
            interval_seconds = FLEET_ATTENTION_INVENTORY_NETWORK_REFRESH_SECONDS
        last = getattr(self, "_fleet_attention_inventory_last_network_mono", 0.0)
        try:
            last_mono = float(last)
        except (TypeError, ValueError):
            last_mono = 0.0
        return now - last_mono >= interval_seconds

    def _schedule_fleet_attention_inventory_network_refresh(
        self,
        *,
        source: str,
    ) -> bool:
        """Launch a non-cache inventory recompute outside the auto-refresh tick."""
        if not self._fleet_attention_inventory_network_due():
            return False
        return self._schedule_fleet_attention_inventory_refresh(
            source=source,
            cache_only=False,
        )

    def _schedule_fleet_attention_inventory_cache_refresh(
        self,
        *,
        source: str,
    ) -> bool:
        """Launch a cache-only inventory refresh outside the auto-refresh tick."""
        return self._schedule_fleet_attention_inventory_refresh(
            source=source,
            cache_only=True,
        )

    def _schedule_fleet_attention_inventory_refresh(
        self,
        *,
        source: str,
        cache_only: bool,
    ) -> bool:
        """Reserve and launch one coalesced inventory poll."""
        if getattr(
            self, "_fleet_attention_inventory_refresh_running", False
        ) or getattr(
            self,
            "_fleet_attention_inventory_refresh_scheduled",
            False,
        ):
            self._coalesce_fleet_attention_inventory_request(cache_only=cache_only)
            return False
        self._fleet_attention_inventory_refresh_scheduled = True  # type: ignore[attr-defined]
        self._fleet_attention_inventory_scheduled_cache_only = cache_only  # type: ignore[attr-defined]
        self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]
        self._fleet_attention_inventory_coalesced_requests = 0  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._run_scheduled_fleet_attention_inventory_poll(source=source),
            name="sase-agents-fleet-attention-inventory",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
            self._fleet_attention_inventory_scheduled_cache_only = True  # type: ignore[attr-defined]
            self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]
            return False

        def _release_if_cancelled(completed: asyncio.Task[object]) -> None:
            if not completed.cancelled():
                return
            self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
            self._fleet_attention_inventory_refresh_running = False  # type: ignore[attr-defined]
            self._fleet_attention_inventory_running_cache_only = None  # type: ignore[attr-defined]
            self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]

        task.add_done_callback(_release_if_cancelled)
        return task is not None

    async def _run_scheduled_fleet_attention_inventory_poll(
        self,
        *,
        source: str,
    ) -> _FleetAttentionInventoryPollResult:
        """Run the reserved inventory poll using the strongest scheduled mode."""
        try:
            return await self._poll_fleet_attention_inventory(
                source=source,
                cache_only=bool(
                    getattr(
                        self,
                        "_fleet_attention_inventory_scheduled_cache_only",
                        True,
                    )
                ),
                _reserved=True,
            )
        finally:
            if not getattr(self, "_fleet_attention_inventory_refresh_running", False):
                self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]

    def _coalesce_fleet_attention_inventory_request(
        self,
        *,
        cache_only: bool,
    ) -> None:
        """Remember a stronger pending request without stacking poll tasks."""
        self._fleet_attention_inventory_coalesced_requests = (  # type: ignore[attr-defined]
            int(getattr(self, "_fleet_attention_inventory_coalesced_requests", 0)) + 1
        )
        if cache_only:
            return
        if getattr(
            self, "_fleet_attention_inventory_refresh_scheduled", False
        ) and not getattr(
            self,
            "_fleet_attention_inventory_refresh_running",
            False,
        ):
            self._fleet_attention_inventory_scheduled_cache_only = False  # type: ignore[attr-defined]
            return
        if getattr(self, "_fleet_attention_inventory_running_cache_only", None) is True:
            self._fleet_attention_inventory_pending_cache_only = False  # type: ignore[assignment]

    def _record_fleet_attention_inventory_completion(
        self,
        result: _FleetAttentionInventoryPollResult,
    ) -> None:
        """Store completed poll counters for the next auto-refresh trace span."""
        if result.skipped:
            return
        counters = dict(
            getattr(self, "_fleet_attention_inventory_completed_counters", {}) or {}
        )
        counters["fleet_attention_poll_batches"] = (
            int(counters.get("fleet_attention_poll_batches", 0)) + 1
        )
        counters["fleet_attention_cache_polls"] = (
            int(counters.get("fleet_attention_cache_polls", 0)) + result.cache_polls
        )
        counters["fleet_attention_network_polls"] = (
            int(counters.get("fleet_attention_network_polls", 0)) + result.network_polls
        )
        counters["fleet_attention_changed"] = int(
            counters.get("fleet_attention_changed", 0)
        ) + int(result.changed)
        counters["fleet_attention_errors"] = int(
            counters.get("fleet_attention_errors", 0)
        ) + int(result.error)
        counters["fleet_attention_duration_ms"] = round(
            float(counters.get("fleet_attention_duration_ms", 0.0))
            + result.duration_ms,
            3,
        )
        counters["fleet_attention_coalesced_requests"] = (
            int(counters.get("fleet_attention_coalesced_requests", 0))
            + result.coalesced_requests
        )
        modes = ",".join(result.modes)
        if modes:
            previous_modes = str(counters.get("fleet_attention_modes") or "")
            counters["fleet_attention_modes"] = (
                f"{previous_modes};{modes}" if previous_modes else modes
            )
        counters["fleet_attention_outcome"] = result.outcome
        self._fleet_attention_inventory_completed_counters = counters  # type: ignore[attr-defined]

    def _consume_fleet_attention_inventory_completed_counters(self) -> dict[str, Any]:
        """Return and clear completed inventory poll counters for trace emission."""
        counters = dict(
            getattr(self, "_fleet_attention_inventory_completed_counters", {}) or {}
        )
        self._fleet_attention_inventory_completed_counters = {}  # type: ignore[attr-defined]
        return counters

    async def _poll_fleet_attention_inventory(
        self,
        *,
        source: str,
        cache_only: bool = False,
        _reserved: bool = False,
    ) -> _FleetAttentionInventoryPollResult:
        """Reconcile global remote attention into the durable inbox.

        This is intentionally independent of the Agents tab's visible row
        projection. It stays cheap for zero-machine configs because the
        dispatch helper returns the disabled read shape before building a
        federation worker facade.
        """
        del source
        if getattr(self, "_fleet_attention_inventory_refresh_running", False) or (
            getattr(self, "_fleet_attention_inventory_refresh_scheduled", False)
            and not _reserved
        ):
            self._coalesce_fleet_attention_inventory_request(cache_only=cache_only)
            return _FleetAttentionInventoryPollResult(
                skipped=True,
                cache_polls=1 if cache_only else 0,
                network_polls=0 if cache_only else 1,
                modes=("cache" if cache_only else "network",),
                outcome="skipped",
            )
        if _reserved:
            cache_only = bool(
                getattr(
                    self,
                    "_fleet_attention_inventory_scheduled_cache_only",
                    cache_only,
                )
            )
        else:
            self._fleet_attention_inventory_coalesced_requests = 0  # type: ignore[attr-defined]
            self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]
        self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
        self._fleet_attention_inventory_refresh_running = True  # type: ignore[attr-defined]
        self._fleet_attention_inventory_running_cache_only = cache_only  # type: ignore[assignment]
        saw_change = False
        polls = 0
        cache_polls = 0
        network_polls = 0
        saw_error = False
        cancelled = False
        modes: list[str] = []
        started = time.perf_counter()
        try:
            while True:
                self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]
                self._fleet_attention_inventory_running_cache_only = cache_only  # type: ignore[assignment]
                modes.append("cache" if cache_only else "network")
                polls += 1
                if cache_only:
                    cache_polls += 1
                else:
                    network_polls += 1
                    self._fleet_attention_inventory_last_network_mono = (  # type: ignore[attr-defined]
                        time.monotonic()
                    )
                try:
                    response = await asyncio.to_thread(
                        fetch_remote_attention_inventory,
                        cache_only=cache_only,
                    )
                    reconcile_outcome = await asyncio.to_thread(
                        reconcile_remote_attention_inbox,
                        response,
                    )
                except Exception as exc:
                    saw_error = True
                    self._fleet_attention_inventory_last_error = str(exc)  # type: ignore[attr-defined]
                    log.debug("remote attention inventory poll failed", exc_info=True)
                    break
                self._fleet_attention_inventory_last_error = None  # type: ignore[assignment,attr-defined]
                if reconcile_outcome.changed:
                    saw_change = True
                    self._dirty_notifications = True  # type: ignore[attr-defined]
                    schedule = getattr(
                        self, "_schedule_notification_snapshot_refresh", None
                    )
                    if callable(schedule):
                        schedule()
                pending_cache_only = getattr(
                    self,
                    "_fleet_attention_inventory_pending_cache_only",
                    None,
                )
                if pending_cache_only is None:
                    break
                cache_only = bool(pending_cache_only)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            self._fleet_attention_inventory_refresh_running = False  # type: ignore[attr-defined]
            self._fleet_attention_inventory_running_cache_only = None  # type: ignore[attr-defined]
            self._fleet_attention_inventory_pending_cache_only = None  # type: ignore[attr-defined]
            self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
            if cancelled:
                self._fleet_attention_inventory_coalesced_requests = 0  # type: ignore[attr-defined]
        result_outcome = (
            "error" if saw_error else "changed" if saw_change else "unchanged"
        )
        result = _FleetAttentionInventoryPollResult(
            changed=saw_change,
            polls=polls,
            cache_polls=cache_polls,
            network_polls=network_polls,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
            modes=tuple(modes),
            outcome=result_outcome,
            coalesced_requests=int(
                getattr(self, "_fleet_attention_inventory_coalesced_requests", 0)
            ),
            error=saw_error,
        )
        self._fleet_attention_inventory_coalesced_requests = 0  # type: ignore[attr-defined]
        self._record_fleet_attention_inventory_completion(result)
        return result

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

    def _open_remote_attention_notification(self, notification: Any) -> bool:
        """Open a remote-attention notification with the existing answer modal."""
        payload = remote_attention_from_notification(notification)
        if payload is None:
            self.notify(  # type: ignore[attr-defined]
                "Remote attention notification is missing its request payload",
                severity="warning",
            )
            return False
        alias, attention = payload

        from ...modals.remote_attention_modal import RemoteAttentionModal

        def _on_dismiss(intent: dict[str, Any] | None) -> None:
            if not intent:
                return
            self._submit_remote_attention_answer(None, alias, attention, intent)

        self.push_screen(  # type: ignore[attr-defined]
            RemoteAttentionModal(alias=alias, entry=attention),
            _on_dismiss,
        )
        return True

    def _submit_remote_attention_answer(
        self,
        agent: Agent | None,
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
        if agent is not None:
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
        poll_inventory = getattr(self, "_poll_fleet_attention_inventory", None)
        if callable(poll_inventory):
            task = spawn_pump_free_task(
                self,
                poll_inventory(source="remote_attention"),
                name="sase-agents-fleet-attention-inventory",
                registry_attr="_agents_fleet_async_tasks",
            )
            if task is None:
                self._dirty_notifications = True  # type: ignore[attr-defined]


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
    "REMOTE_ATTENTION_NOTIFICATION_ACTION",
    "RemoteAttentionMixin",
    "handle_remote_attention_notification",
    "has_pending_remote_attention",
]
