"""Waiting and runner-slot fields from filesystem-backed agent metadata."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    QUEUE_WEIGHT_ERROR,
    valid_queue_weight,
)
from ._meta_enrichment_status import (
    ACTIVE_ENRICHMENT_STATUSES,
    pending_question_status_from_marker,
)
from ..agent import Agent

_QUEUE_WEIGHT_ERROR = QUEUE_WEIGHT_ERROR


def _coerce_queue_weight(value: object, *, explicit: bool) -> float | None:
    return valid_queue_weight(value, explicit=explicit)


def _resolve_capacity_multiplier(data: dict[str, object]) -> float | None:
    """Return the valid ``queue_capacity_multiplier`` unless an integer wins.

    Delegates validity (finite, positive, at most two decimals) to the shared
    queue adapter so filesystem and wire loaders agree with admission.
    """
    from sase.macro.queue_directive import resolve_authored_queue_capacity_multiplier

    try:
        return resolve_authored_queue_capacity_multiplier(data)
    except Exception:
        return None


def apply_queue_weight_fields(agent: Agent, data: dict[str, object]) -> None:
    has_weight = "queue_weight" in data
    if has_weight:
        explicit = data.get("queue_weight_explicit") is True
        weight = _coerce_queue_weight(data.get("queue_weight"), explicit=explicit)
        agent.queue_weight = weight
        agent.queue_weight_explicit = explicit
        if weight is None:
            agent.queue_weight_invalid = True
            raw_error = data.get("queue_weight_error")
            agent.queue_weight_error = (
                raw_error if isinstance(raw_error, str) and raw_error else None
            ) or _QUEUE_WEIGHT_ERROR
            return
        agent.queue_weight_invalid = data.get("queue_weight_invalid") is True
        raw_error = data.get("queue_weight_error")
        agent.queue_weight_error = (
            raw_error if isinstance(raw_error, str) and raw_error else None
        )
        return
    if data.get("queue_weight_invalid") is True:
        agent.queue_weight_invalid = True
        raw_error = data.get("queue_weight_error")
        agent.queue_weight_error = (
            raw_error if isinstance(raw_error, str) and raw_error else None
        ) or _QUEUE_WEIGHT_ERROR


def apply_filesystem_waiting_meta(
    agent: Agent,
    data: dict[str, object],
    artifacts_dir: str,
) -> None:
    """Apply waiting markers and queue settings from filesystem artifacts."""
    from sase.core.wait_epic_follow_view import epic_follow_views

    # Check for waiting.json to set WAITING status (takes precedence over PLAN
    # since the agent can't plan until its dependencies are resolved)
    waiting_path = Path(artifacts_dir) / "waiting.json"
    if waiting_path.exists() and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = "WAITING"
        agent.wait_start_time = agent.start_time
        # waiting.json may contain an updated waiting_for list (e.g. from the TUI
        # "w" keymap), which takes precedence over agent_meta.json's wait_for.
        try:
            with open(waiting_path, encoding="utf-8") as f:
                waiting_data = json.load(f)
            if isinstance(waiting_data, dict):
                if waiting_data.get("waiting_for"):
                    agent.waiting_for = waiting_data["waiting_for"]
                if waiting_data.get("wait_for_beads"):
                    agent.waiting_for_beads = waiting_data["wait_for_beads"]
                if waiting_data.get("wait_for_hoods"):
                    agent.waiting_for_hoods = waiting_data["wait_for_hoods"]
                # waiting.json overrides agent_meta.json for the follow
                # fields, matching the other wait-list keys above.
                if waiting_data.get("wait_for_epics_of"):
                    agent.wait_for_epics_of = [
                        item
                        for item in waiting_data["wait_for_epics_of"]
                        if isinstance(item, str)
                    ]
                if waiting_data.get("wait_epic_follows"):
                    agent.wait_epic_follows = list(
                        epic_follow_views(waiting_data["wait_epic_follows"])
                    )
                from sase.core.agent_scan_wire_markers_wait_turn import (
                    wait_turn_bindings_from_payload,
                )

                waiting_bindings = wait_turn_bindings_from_payload(waiting_data)
                if (
                    waiting_bindings
                    or "wait_turn_bindings" in waiting_data
                    or waiting_data.get("wait_for_artifacts")
                    or waiting_data.get("wait_for_fork_sources")
                ):
                    agent.wait_turn_bindings = waiting_bindings
                # Read wait_duration from waiting.json (preferred source)
                raw_dur = waiting_data.get("wait_duration")
                if raw_dur is not None:
                    try:
                        agent.wait_duration = float(raw_dur)
                    except (ValueError, TypeError):
                        pass
                # Read wait_until from waiting.json
                raw_until = waiting_data.get("wait_until")
                if isinstance(raw_until, str) and raw_until:
                    agent.wait_until = raw_until
                raw_runners = waiting_data.get(
                    "queue_capacity",
                    waiting_data.get("wait_runners"),
                )
                if type(raw_runners) is int and raw_runners >= 0:
                    agent.set_queue_capacity(
                        raw_runners,
                        explicit=(
                            waiting_data.get("queue_capacity_explicit") is True
                            or waiting_data.get("wait_runners_explicit") is True
                        ),
                    )
                else:
                    waiting_multiplier = _resolve_capacity_multiplier(waiting_data)
                    if waiting_multiplier is not None:
                        agent.set_queue_capacity(
                            None,
                            multiplier=waiting_multiplier,
                        )
                    else:
                        agent.set_queue_capacity(
                            None,
                            explicit=(
                                waiting_data.get("queue_capacity_explicit") is True
                                or waiting_data.get("wait_runners_explicit") is True
                            ),
                        )
                raw_priority = waiting_data.get("wait_priority")
                if type(raw_priority) is int and raw_priority >= 0:
                    agent.wait_priority = raw_priority
                if "wait_priority_explicit" in waiting_data:
                    agent.wait_priority_explicit = (
                        waiting_data.get("wait_priority_explicit") is True
                    )
                else:
                    agent.wait_priority_explicit = (
                        type(raw_priority) is int
                        and raw_priority >= 0
                        and raw_priority != DEFAULT_WAIT_PRIORITY
                    )
                apply_queue_weight_fields(agent, waiting_data)
                raw_requested_at = waiting_data.get("slot_requested_at")
                if isinstance(raw_requested_at, str) and raw_requested_at:
                    agent.slot_requested_at = raw_requested_at
                raw_held_by = waiting_data.get("held_by")
                agent.held_by = raw_held_by if isinstance(raw_held_by, str) else None
                raw_hold_expires_at = waiting_data.get("hold_expires_at")
                agent.hold_expires_at = (
                    float(raw_hold_expires_at)
                    if isinstance(raw_hold_expires_at, (int, float))
                    and not isinstance(raw_hold_expires_at, bool)
                    else None
                )
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: read wait_duration from agent_meta.json if not set from waiting.json
    if agent.wait_duration is None:
        raw_dur = data.get("wait_duration")
        if isinstance(raw_dur, (int, float, str)):
            try:
                agent.wait_duration = float(raw_dur)
            except (ValueError, TypeError):
                pass

    # Fallback: read wait_until from agent_meta.json if not set from waiting.json
    if agent.wait_until is None:
        raw_until = data.get("wait_until")
        if isinstance(raw_until, str) and raw_until:
            agent.wait_until = raw_until

    # Fallback: an authored runner-slot priority remains useful after the
    # live waiting marker has been removed or before it has been published.
    if agent.queue_capacity is None and agent.queue_capacity_multiplier is None:
        raw_runners = data.get("queue_capacity", data.get("wait_runners"))
        if type(raw_runners) is int and raw_runners >= 0:
            agent.set_queue_capacity(
                raw_runners,
                explicit=(
                    data.get("queue_capacity_explicit") is True
                    or data.get("wait_runners_explicit") is True
                    or "queue_capacity" in data
                    or "wait_runners" in data
                ),
            )
        else:
            meta_multiplier = _resolve_capacity_multiplier(data)
            if meta_multiplier is not None:
                agent.set_queue_capacity(None, multiplier=meta_multiplier)
    if agent.wait_priority is None:
        raw_priority = data.get("wait_priority")
        if type(raw_priority) is int and raw_priority >= 0:
            agent.wait_priority = raw_priority
            agent.wait_priority_explicit = True

    # Check for pending_question.json to set QUESTION/ANSWERED status. The
    # marker is written by handle_questions_flow() before the response-wait
    # poll loop and retained until a root has reacquired its runner slot. Its
    # presence is therefore the authoritative slot-yield signal, independent of
    # the notification's dismissed/read state. A simultaneous waiting marker
    # wins after the answer because the root is queued to resume.
    pending_question_path = Path(artifacts_dir) / "pending_question.json"
    pending_question_exists = pending_question_path.exists()
    agent.runner_slot_yielded = pending_question_exists
    if pending_question_exists and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = pending_question_status_from_marker(pending_question_path)
