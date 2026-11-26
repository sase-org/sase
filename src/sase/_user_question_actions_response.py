"""UserQuestion request resolution and response execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase._user_question_actions_models import (
    QUESTION_OPTION_ID,
    QUESTION_REQUEST_FILE,
    QUESTION_RESPONSE_FILE,
    UserQuestionActionContext,
    UserQuestionActionError,
)
from sase._user_question_actions_payload import (
    normalize_user_question_response_data,
    validate_user_questions,
)


@dataclass(frozen=True)
class _UserQuestionActionResult:
    """Result returned after a question response reaches durable storage."""

    notification_id: str | None
    response_file: str
    response_path: Path
    response_json: dict[str, Any]
    answers: dict[str, Any]
    message: str = "Question answered"


@dataclass(frozen=True)
class _ResolvedUserQuestionRequest:
    """Question request details prepared for a host surface."""

    root: Path
    response_path: Path
    legacy: bool
    questions: list[dict[str, Any]]


@dataclass(frozen=True)
class _PreparedUserQuestionResponse:
    """Validated question answers ready for gate execution."""

    root: Path
    response_path: Path
    legacy: bool
    questions: list[dict[str, Any]]
    normalized: dict[str, Any]


def execute_user_question_response(
    context: UserQuestionActionContext,
    response_data: Mapping[str, Any],
    *,
    source: str = "question_response",
) -> _UserQuestionActionResult:
    """Resolve a neutral UserQuestion, with legacy in-flight fallback."""
    prepared = _prepare_user_question_response(context, response_data)
    normalized = prepared.normalized

    if prepared.legacy:
        response_path = prepared.response_path
        _write_json_once(response_path, normalized, context.notification_id)
        response_json = normalized
        response_file = QUESTION_RESPONSE_FILE
    else:
        from sase.gate_turn.log import bind_gate_turn_execution_callbacks
        from sase.gate_turn.settlement import settle_gate_turn
        from sase.gate_turn.store import find_gate_turn_by_gate_id
        from sase.notification_gates.executor import execute_gate_selection
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.models import GateError
        from sase.notification_gates.paths import RESPONSE_FILENAME

        envelope, _adapter = load_and_verify_bundle(prepared.root)
        turn_backed = isinstance(envelope.get("turn"), dict) or isinstance(
            envelope.get("shell"), dict
        )
        gate_turn = (
            find_gate_turn_by_gate_id(None, str(envelope.get("request_id") or ""))
            if turn_backed
            else None
        )
        execution_kwargs: dict[str, Any] = (
            {}
            if gate_turn is None
            else bind_gate_turn_execution_callbacks(gate_turn.artifacts_dir).as_kwargs()
        )
        try:
            shared_feedback = response_data.get("feedback")
            if not isinstance(shared_feedback, str):
                shared_feedback = normalized.get("global_note")
            if not isinstance(shared_feedback, str) or not shared_feedback.strip():
                shared_feedback = None
            execution = execute_gate_selection(
                prepared.root,
                [QUESTION_OPTION_ID],
                normalized,
                feedback=shared_feedback,
                source=source,
                **execution_kwargs,
            )
        except GateError as exc:
            code = (
                "conflict_already_handled"
                if exc.code in {"already_answered", "gate_cancelled"}
                else exc.code
            )
            raise UserQuestionActionError(code, exc.target, str(exc)) from exc
        if gate_turn is not None:
            settle_gate_turn(
                gate_turn,
                gate_state="answered",
                reason="question answered",
            )
        if execution.already_completed:
            raise UserQuestionActionError(
                "conflict_already_handled",
                context.notification_id or str(prepared.root),
                "response already exists",
            )
        response_json = execution.response
        option_results = response_json.get("option_results")
        result = (
            next(
                (
                    entry.get("result")
                    for entry in option_results
                    if isinstance(entry, Mapping)
                    and entry.get("id") == QUESTION_OPTION_ID
                ),
                None,
            )
            if isinstance(option_results, list)
            else None
        )
        if not isinstance(result, dict):
            raise UserQuestionActionError(
                "invalid_response",
                str(prepared.response_path),
                "question command returned no result object",
            )
        normalized = normalize_user_question_response_data(prepared.questions, result)
        response_path = prepared.response_path
        response_file = RESPONSE_FILENAME

    _run_question_side_effects(context, source=source)
    return _UserQuestionActionResult(
        notification_id=context.notification_id,
        response_file=response_file,
        response_path=response_path,
        response_json=response_json,
        answers=normalized,
    )


def read_user_question_request(response_dir: str | Path) -> dict[str, Any]:
    """Read a neutral question payload first, then an in-flight legacy request."""
    root = Path(response_dir).expanduser()
    return _request_from_root(root, legacy=not (root / "request.json").is_file())


def resolve_user_question_request(
    context: UserQuestionActionContext,
) -> _ResolvedUserQuestionRequest:
    """Resolve a question bundle and validate its questions for a UI surface."""
    bundle = _resolve_question_bundle(context)
    questions = _questions_from_request_root(bundle.root, legacy=bundle.legacy)
    return _ResolvedUserQuestionRequest(
        root=bundle.root,
        response_path=bundle.response,
        legacy=bundle.legacy,
        questions=questions,
    )


def normalize_user_question_response(
    questions: list[dict[str, Any]], response_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Normalize and validate modal answers against already-loaded questions."""
    return normalize_user_question_response_data(questions, response_data)


def run_user_question_response_side_effects(
    context: UserQuestionActionContext, *, source: str = "question_response"
) -> None:
    """Dismiss and mark a question notification after a durable answer."""
    _run_question_side_effects(context, source=source)


def _prepare_user_question_response(
    context: UserQuestionActionContext,
    response_data: Mapping[str, Any],
) -> _PreparedUserQuestionResponse:
    """Resolve the bundle and validate answers before a host submits the answer."""
    request = resolve_user_question_request(context)
    return _PreparedUserQuestionResponse(
        root=request.root,
        response_path=request.response_path,
        legacy=request.legacy,
        questions=request.questions,
        normalized=normalize_user_question_response(request.questions, response_data),
    )


def _resolve_question_bundle(context: UserQuestionActionContext) -> Any:
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import (
        CANCELLATION_FILENAME,
        REQUEST_FILENAME,
        RESPONSE_FILENAME,
        ResolvedGateBundle,
        assert_owned_bundle,
        resolve_action_bundle,
    )

    bundle = resolve_action_bundle("UserQuestion", context.host_action_data)
    if bundle is not None and (bundle.request.is_file() or bundle.response.is_file()):
        return bundle
    raw_root = context.host_action_data.get("response_dir")
    if not raw_root:
        raise UserQuestionActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    root = Path(raw_root).expanduser()
    neutral_request = root / REQUEST_FILENAME
    if neutral_request.is_file():
        try:
            root = assert_owned_bundle(root)
        except GateError as exc:
            raise UserQuestionActionError(exc.code, exc.target, str(exc)) from exc
        return ResolvedGateBundle(
            kind="question",
            root=root,
            request=root / REQUEST_FILENAME,
            response=root / RESPONSE_FILENAME,
            cancellation=root / CANCELLATION_FILENAME,
            legacy=False,
        )
    return ResolvedGateBundle(
        kind="question",
        root=root,
        request=root / QUESTION_REQUEST_FILE,
        response=root / QUESTION_RESPONSE_FILE,
        cancellation=root / CANCELLATION_FILENAME,
        legacy=True,
    )


def _questions_from_request_root(root: Path, *, legacy: bool) -> list[dict[str, Any]]:
    data = _request_from_root(root, legacy=legacy)
    return validate_user_questions(data.get("questions"))


def _request_from_root(root: Path, *, legacy: bool) -> dict[str, Any]:
    if not legacy:
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.models import GateError

        try:
            envelope, adapter = load_and_verify_bundle(root)
        except GateError as exc:
            raise UserQuestionActionError(exc.code, exc.target, str(exc)) from exc
        if adapter.kind != "question":
            raise UserQuestionActionError(
                "invalid_request", str(root), "gate is not a question request"
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise UserQuestionActionError(
                "invalid_request", str(root / "request.json"), "payload is missing"
            )
        return payload

    request_path = root / QUESTION_REQUEST_FILE
    try:
        value = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request is missing"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise UserQuestionActionError(
            "invalid_request", str(request_path), "question request must be an object"
        )
    return value


def _write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str | None,
) -> None:
    try:
        with response_path.open("x", encoding="utf-8") as stream:
            json.dump(response_json, stream, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise UserQuestionActionError(
            "conflict_already_handled",
            notification_id or str(response_path),
            "response already exists",
        ) from exc


def _run_question_side_effects(
    context: UserQuestionActionContext, *, source: str
) -> None:
    if not context.notification_id:
        return
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(context.notification_id)
    except Exception:
        pass
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(
            context.notification_id,
            source=source,
            action=QUESTION_OPTION_ID,
        )
    except Exception:
        pass
