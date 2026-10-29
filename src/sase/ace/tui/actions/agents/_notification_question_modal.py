"""User question notification modal handling."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ._notification_utils import refresh_notification_agent_or_request

if TYPE_CHECKING:
    from sase.notification_gates.debug import GateDebugContext
    from sase.notifications import Notification

    from ...models import Agent


log = logging.getLogger(__name__)
_QuestionTaskSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class _QuestionResponseTaskOutcome:
    message: str
    success: bool
    severity: _QuestionTaskSeverity | None = None


def handle_user_question(app: object, notification: Notification) -> bool:
    """Show the user question modal for a Claude Code AskUserQuestion hook.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.

    Returns:
        True if the user question modal was pushed.
    """
    from sase.notification_gates.debug import debug_context_from_notification
    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None:
        app.notify(  # type: ignore[attr-defined]
            "No question request in notification; press d on the notification to debug",
            severity="warning",
        )
        return False

    return _open_user_question_modal(
        app,
        str(bundle.root),
        notification_id=notification.id,
        notification=notification,
        action_data=dict(notification.action_data),
        debug_context=debug_context_from_notification(notification),
        on_response_written=lambda: _on_user_question_response_written(
            app, notification
        ),
    )


def _on_user_question_response_written(app: object, notification: Notification) -> None:
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
            app,
            response_dir,
            notification_id=None,
            notification=None,
            action_data={"response_dir": response_dir},
            debug_context=None,
            on_response_written=None,
        )

    matched = agent

    def on_written() -> None:
        _mark_marker_agent_answered(app, matched)

    return _open_user_question_modal(
        app,
        response_dir,
        notification_id=None,
        notification=None,
        action_data={"response_dir": response_dir},
        debug_context=None,
        on_response_written=on_written,
    )


def _open_user_question_modal(
    app: object,
    response_dir: str,
    *,
    notification_id: str | None,
    notification: Notification | None,
    action_data: dict[str, str],
    debug_context: GateDebugContext | None,
    on_response_written: Callable[[], None] | None,
) -> bool:
    from ...modals import UserQuestionModal, UserQuestionResult
    from sase.user_question_actions import (
        UserQuestionActionContext,
        UserQuestionActionError,
        resolve_user_question_request,
    )

    response_path = Path(response_dir)
    context_data = dict(action_data)
    context_data.setdefault("response_dir", str(response_path))
    try:
        request = resolve_user_question_request(
            UserQuestionActionContext(
                notification_id=notification_id,
                host_action_data=context_data,
            )
        )
    except UserQuestionActionError as e:
        app.notify(  # type: ignore[attr-defined]
            f"Error reading question request: {e}; press d on the notification to debug",
            severity="error",
        )
        return False

    questions = request.questions

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

        _submit_question_response_task(
            app,
            response_dir=response_path,
            notification_id=notification_id,
            action_data=action_data,
            response_data=response_data,
            questions=questions,
            legacy=request.legacy,
            bundle_path=request.root,
            notification=notification,
            on_response_written=on_response_written,
        )

    app.push_screen(  # type: ignore[attr-defined]
        UserQuestionModal(questions, debug_context=debug_context),
        on_dismiss,
    )
    return True


def _submit_question_response_task(
    app: object,
    *,
    response_dir: Path,
    notification_id: str | None,
    action_data: dict[str, str],
    response_data: dict[str, object],
    questions: list[dict[str, object]],
    legacy: bool,
    bundle_path: Path,
    notification: Notification | None,
    on_response_written: Callable[[], None] | None,
) -> None:
    """Run the hashed question command as tracked background work in ACE."""
    from sase.ace.tui.actions.proc_actions import TrackedProcResult
    from sase.user_question_actions import (
        UserQuestionActionContext,
        UserQuestionActionError,
        normalize_user_question_response,
        run_user_question_response_side_effects,
    )

    request_id = action_data.get("request_id") or bundle_path.name
    context_data = dict(action_data)
    context_data.setdefault("response_dir", str(response_dir))
    try:
        normalized = normalize_user_question_response(
            questions,
            response_data,
        )
    except UserQuestionActionError as exc:
        _finish_question_response_task(
            app,
            _QuestionResponseTaskOutcome(str(exc), False, "error"),
            on_response_written,
        )
        return

    if not legacy:
        submit_durable = getattr(app, "_submit_durable_proc", None)
        if callable(submit_durable):
            from sase.ace.tui.actions._durable_ops import (
                durable_fingerprint,
                durable_request_payload,
                sase_argv,
            )
            from sase.ops.names import GATE_ANSWER

            note = normalized.get("global_note")
            feedback = note if isinstance(note, str) and note.strip() else None

            def on_complete(completion: object) -> None:
                success = bool(getattr(completion, "success", False))
                payload = getattr(completion, "payload", None)
                code = payload.get("code") if isinstance(payload, dict) else None
                if success:
                    run_user_question_response_side_effects(
                        UserQuestionActionContext(
                            notification_id=notification_id,
                            host_action_data=context_data,
                        ),
                        source="tui",
                    )
                    outcome = _QuestionResponseTaskOutcome(
                        str(getattr(completion, "message", "Question answered")),
                        True,
                    )
                elif code in {
                    "already_answered",
                    "gate_cancelled",
                    "conflict_already_handled",
                }:
                    outcome = _QuestionResponseTaskOutcome(
                        "Question was already answered", False, "warning"
                    )
                else:
                    outcome = _QuestionResponseTaskOutcome(
                        str(
                            getattr(
                                completion,
                                "message",
                                "Question response failed",
                            )
                        ),
                        False,
                        "error",
                    )
                _finish_question_response_task(app, outcome, on_response_written)

            try:
                submitted = submit_durable(
                    sase_argv(
                        "gate",
                        "answer",
                        "--id",
                        request_id,
                        "--kind",
                        "question",
                        "--no-detach",
                        "--json",
                    ),
                    operation=GATE_ANSWER,
                    request=durable_request_payload(
                        option_ids=["submit"],
                        input_data=normalized,
                        feedback=feedback,
                        source="tui",
                    ),
                    request_fingerprint=durable_fingerprint(
                        GATE_ANSWER,
                        "question",
                        request_id,
                        "submit",
                        "",
                        "tui",
                    ),
                    concurrency_keys=(
                        f"notification-gate:{notification_id or request_id}",
                    ),
                    label=f"answer question {request_id}",
                    display_name=f"answer question {request_id}",
                    cl_name=f"question {request_id}",
                    project_file=str(bundle_path),
                    on_complete=on_complete,
                    reload_on_complete=False,
                    notify_on_complete=False,
                )
            except Exception:
                log.exception("Failed to submit durable question answer")
                _finish_question_response_task(
                    app,
                    _QuestionResponseTaskOutcome(
                        "Question response failed", False, "error"
                    ),
                    on_response_written,
                )
                return
            if submitted is not None and notification is not None:
                from ._notification_utils import schedule_gate_decision_receipt_refresh

                schedule_gate_decision_receipt_refresh(
                    app,
                    notification=notification,
                    bundle_path=bundle_path,
                )
            return

    def task_body() -> _QuestionResponseTaskOutcome:
        from sase.user_question_actions import (
            execute_user_question_response,
        )

        try:
            result = execute_user_question_response(
                UserQuestionActionContext(
                    notification_id=notification_id,
                    host_action_data=context_data,
                ),
                response_data,
                source="tui",
            )
        except UserQuestionActionError as exc:
            severity: _QuestionTaskSeverity = (
                "warning" if exc.code == "conflict_already_handled" else "error"
            )
            message = (
                "Question was already answered"
                if exc.code == "conflict_already_handled"
                else str(exc)
            )
            return _QuestionResponseTaskOutcome(message, False, severity)
        return _QuestionResponseTaskOutcome(result.message, True)

    def tracked_body() -> TrackedProcResult[_QuestionResponseTaskOutcome]:
        outcome = task_body()
        return TrackedProcResult(
            success=outcome.success,
            message=outcome.message,
            payload=outcome,
            error=None if outcome.success else outcome.message,
        )

    def finish(completion: object) -> None:
        outcome = getattr(completion, "payload", None)
        if not isinstance(outcome, _QuestionResponseTaskOutcome):
            if not bool(getattr(completion, "success", False)):
                app.notify(  # type: ignore[attr-defined]
                    str(getattr(completion, "message", "Question response failed")),
                    severity="error",
                )
            return
        _finish_question_response_task(app, outcome, on_response_written)

    submit = getattr(app, "_submit_session_worker", None)
    if callable(submit):
        try:
            submit(
                "question",
                tracked_body,
                display_name=f"answer question {request_id}",
                cl_name=f"question {request_id}",
                project_file=str(response_dir),
                on_complete=finish,
            )
            return
        except Exception:
            log.debug("Falling back to synchronous question response", exc_info=True)

    _finish_question_response_task(app, task_body(), on_response_written)


def _finish_question_response_task(
    app: object,
    outcome: _QuestionResponseTaskOutcome,
    on_response_written: Callable[[], None] | None,
) -> None:
    if outcome.success and on_response_written is not None:
        on_response_written()
    if outcome.severity is None:
        app.notify(outcome.message)  # type: ignore[attr-defined]
    else:
        app.notify(outcome.message, severity=outcome.severity)  # type: ignore[attr-defined]
    refresh_count = getattr(app, "_refresh_notification_count", None)
    if callable(refresh_count):
        refresh_count()


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
    this does not broaden to unrelated rows that merely share a Patch
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
    override is reconciled away.

    All overrides are written before any row refresh so a refilter-based
    refresh observes every ANSWERED override at once.
    """
    for agent in agents:
        identity = agent.identity
        app._agent_status_overrides[identity] = "ANSWERED"  # type: ignore[attr-defined]
    for agent in agents:
        refresh_notification_agent_or_request(app, agent=agent)
