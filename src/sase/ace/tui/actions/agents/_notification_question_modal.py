"""User question notification modal handling."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_modal_responses import write_workflow_action_response
from ._notification_utils import refresh_notification_agent_or_request

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def handle_user_question(app: object, notification: Notification) -> bool:
    """Show the user question modal for a Claude Code AskUserQuestion hook.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.

    Returns:
        True if the user question modal was pushed.
    """
    response_dir = notification.action_data.get("response_dir")
    if not response_dir:
        app.notify("No response_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    return _open_user_question_modal(
        app,
        response_dir,
        notification_id=notification.id,
        on_response_written=lambda: _on_user_question_response_written(
            app, notification
        ),
    )


def _on_user_question_response_written(app: object, notification: Notification) -> None:
    from sase.notifications import mark_dismissed

    mark_dismissed(notification.id)
    _mark_answered_for_notification(app, notification)


def _normalize_timestamp(value: object) -> str | None:
    """Normalize a raw_suffix/parent_timestamp value to 14-digit form."""
    if not isinstance(value, str):
        return None
    from sase.ace.tui.models._timestamps import normalize_to_14_digit

    return normalize_to_14_digit(value.strip())


def open_user_question_modal_from_marker(
    app: object, response_dir: str, agent: Agent | None = None
) -> bool:
    """Open the UserQuestionModal directly from a pending_question.json marker.

    Used by the "jump to current agent's question" keybind when the matching
    notification has been dismissed but the agent is still blocked on user
    input (marker is still present). No notification is dismissed because
    none is present; the marker is cleared by ``handle_questions_flow()``
    itself once the response is consumed. When *agent* is supplied, the row is
    flipped to the transient ``ANSWERED`` override once the response is written
    (mirroring the notification-driven path).
    """
    if agent is None:
        return _open_user_question_modal(
            app, response_dir, notification_id=None, on_response_written=None
        )

    matched = agent

    def on_written() -> None:
        _mark_marker_agent_answered(app, matched)

    return _open_user_question_modal(
        app, response_dir, notification_id=None, on_response_written=on_written
    )


def _open_user_question_modal(
    app: object,
    response_dir: str,
    *,
    notification_id: str | None,
    on_response_written: Callable[[], None] | None,
) -> bool:
    from ...modals import UserQuestionModal, UserQuestionResult

    response_path = Path(response_dir)
    request_path = response_path / "question_request.json"

    if not request_path.exists():
        app.notify("User question request expired or not found", severity="warning")  # type: ignore[attr-defined]
        return False

    try:
        with open(request_path, encoding="utf-8") as f:
            request_data = json.load(f)
    except Exception as e:
        app.notify(f"Error reading question request: {e}", severity="error")  # type: ignore[attr-defined]
        return False

    questions = request_data.get("questions", [])

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, UserQuestionResult):
            return

        response_data: dict[str, object] = {
            "answers": [
                {
                    "question": a.question,
                    "selected": a.selected,
                    "custom_feedback": a.custom_feedback,
                }
                for a in result.answers
            ],
            "global_note": result.global_note,
        }

        question_response_path = response_path / "question_response.json"
        try:
            write_workflow_action_response(
                question_response_path,
                response_data,
                action_kind="user_question",
                notification_id=notification_id or str(question_response_path),
            )
            app.notify("Sent question response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]
            return

        if on_response_written is not None:
            on_response_written()

    app.push_screen(UserQuestionModal(questions), on_dismiss)  # type: ignore[attr-defined]
    return True


def _mark_answered_for_notification(app: object, notification: Notification) -> None:
    """Flip every loaded row matching *notification* to transient ANSWERED.

    A single ``UserQuestion`` notification carries both ``agent_timestamp``
    (the concrete asking child row) and ``agent_root_timestamp`` (the
    root/aggregate row). Because ``Agent.identity`` includes ``raw_suffix``,
    each row holds a separate override key, so marking only the first match
    would leave the other row stuck on its stale ``QUESTION`` override. Mark
    them all.
    """
    from ._notification_navigation import find_agents_for_notification

    _mark_agents_answered(app, find_agents_for_notification(app, notification))


def _mark_marker_agent_answered(app: object, agent: Agent) -> None:
    """Mark a marker-supplied row ANSWERED, plus its loaded root row.

    The dismissed-notification marker fallback has no notification carrying
    both timestamps, so the related root/aggregate row is resolved from the
    asking child's ``parent_timestamp`` when that row is currently loaded.
    """
    _mark_agents_answered(app, [agent, *_loaded_root_rows_for_child(app, agent)])


def _loaded_root_rows_for_child(app: object, agent: Agent) -> list[Agent]:
    """Return loaded root rows whose ``raw_suffix`` is *agent*'s parent.

    Timestamp matching is the primary signal here: a child's
    ``parent_timestamp`` points at exactly its root row's ``raw_suffix``, so
    this does not broaden to unrelated rows that merely share a ChangeSpec
    name.
    """
    parent_timestamp = _normalize_timestamp(getattr(agent, "parent_timestamp", None))
    if not parent_timestamp:
        return []
    rows: list[Agent] = []
    for candidate in getattr(app, "_agents", []):
        if candidate is agent:
            continue
        if (
            _normalize_timestamp(getattr(candidate, "raw_suffix", None))
            == parent_timestamp
        ):
            rows.append(candidate)
    return rows


def _mark_agents_answered(app: object, agents: list[Agent]) -> None:
    """Record the transient ANSWERED override for each row after a response.

    The user has written ``question_response.json`` but the runner has not yet
    consumed it. ANSWERED reads as an active/progress state until a fresh load
    shows the agent resuming (or a terminal status), at which point the
    override is reconciled away. The stale ``_agent_pre_question_status`` entry
    is dropped — the transient ANSWERED state replaces the pre-question
    restore behavior.

    All overrides are written before any row refresh so a refilter-based
    refresh observes every ANSWERED override at once.
    """
    for agent in agents:
        identity = agent.identity
        app._agent_pre_question_status.pop(identity, None)  # type: ignore[attr-defined]
        app._agent_status_overrides[identity] = "ANSWERED"  # type: ignore[attr-defined]
    for agent in agents:
        refresh_notification_agent_or_request(app, agent=agent)
