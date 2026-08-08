"""Waiting, response translation, and dispatch for launch approval requests."""

from __future__ import annotations

import json
import os
import signal
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_preview import LAUNCH_REQUEST_FILE
from sase.agent.launch_request_types import (
    ApprovedLaunchDispatchResult,
    LaunchRequestCreationResult,
    LaunchRequestError,
    LaunchRequestOutcome,
    LaunchRequestStatus,
)
from sase.notification_gates.paths import REQUEST_FILENAME


def wait_for_launch_approval(
    request: LaunchRequestCreationResult,
    *,
    poll_interval: float = 0.2,
) -> LaunchRequestOutcome:
    """Wait mechanically for a launch gate and translate its neutral response."""
    from sase.notification_gates.models import GateError
    from sase.notification_gates.poller import wait_for_gate

    terminated = False
    previous_sigterm: Any = None

    def on_sigterm(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal terminated
        terminated = True

    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.signal(signal.SIGTERM, on_sigterm)
    try:
        result = wait_for_gate(
            request.response_dir,
            poll_interval=poll_interval,
            cancelled=lambda: terminated,
        )
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    if result.status != "responded":
        status: LaunchRequestStatus = (
            "timed_out" if result.status == "timed_out" else "cancelled"
        )
        return LaunchRequestOutcome(
            status=status,
            request_id=request.request_id,
            notification_id=request.notification_id,
            selected_option_ids=(),
            message=(
                "Launch approval timed out"
                if status == "timed_out"
                else "Launch approval cancelled"
            ),
            response=result.payload,
        )
    return _launch_outcome_from_response(request, result.payload)


def cancel_launch_approval_request(
    request: LaunchRequestCreationResult,
) -> dict[str, Any]:
    """Cancel a request that the requester no longer intends to wait for."""
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.models import GateError

    try:
        return cancel_gate(request.response_dir, source="launch_requester")
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc


def dispatch_approved_launch_request(
    response_dir: Path,
) -> ApprovedLaunchDispatchResult:
    """Dispatch a neutral launch bundle or an in-flight legacy request."""
    data = read_launch_request(response_dir)

    dispatch = data.get("dispatch")
    if not isinstance(dispatch, dict):
        raise LaunchRequestError(
            "invalid_request", "dispatch", "launch request has no dispatch payload"
        )
    prompt = dispatch.get("prompt")
    cwd = dispatch.get("cwd")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchRequestError(
            "invalid_request", "dispatch.prompt", "dispatch prompt is missing"
        )
    if not isinstance(cwd, str) or not cwd:
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", "dispatch cwd is missing"
        )

    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_dir():
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", f"dispatch cwd does not exist: {cwd}"
        )

    original_cwd = Path.cwd()
    try:
        os.chdir(cwd_path)
        from sase.agent import launcher as launcher_mod

        results = launcher_mod.launch_agents_from_cwd(prompt)
    finally:
        os.chdir(original_cwd)

    return ApprovedLaunchDispatchResult(
        request_id=str(data.get("request_id") or ""),
        results=results,
    )


def read_launch_request(response_dir: Path) -> dict[str, Any]:
    """Read a neutral launch payload first, then the legacy request file."""
    neutral_path = response_dir / REQUEST_FILENAME
    legacy_path = response_dir / LAUNCH_REQUEST_FILE
    request_path = neutral_path if neutral_path.is_file() else legacy_path
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is missing"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request must be an object"
        )

    if request_path == neutral_path:
        if data.get("kind") != "launch":
            raise LaunchRequestError(
                "invalid_request", str(request_path), "gate is not a launch request"
            )
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise LaunchRequestError(
                "invalid_request",
                str(request_path),
                "launch gate payload must be an object",
            )
        return payload
    return data


def _launch_outcome_from_response(
    request: LaunchRequestCreationResult, response: dict[str, Any]
) -> LaunchRequestOutcome:
    raw_selected = response.get("selected_option_ids")
    option_results = response.get("option_results")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or not isinstance(raw_selected[0], str)
        or not isinstance(option_results, list)
    ):
        raise LaunchRequestError(
            "invalid_response",
            str(request.response_path),
            "launch response must select exactly one option",
        )
    selected_option_ids = tuple(raw_selected)
    option_id = selected_option_ids[0]
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == option_id
        ),
        None,
    )
    if not isinstance(result, dict):
        raise LaunchRequestError(
            "invalid_response",
            str(request.response_path),
            "launch response is missing its selected option result",
        )
    translated_response = dict(response)
    feedback = response.get("feedback")
    if not isinstance(feedback, str) or not feedback:
        legacy_feedback = result.get("feedback")
        feedback = legacy_feedback if isinstance(legacy_feedback, str) else None
    if feedback:
        translated_response["feedback"] = feedback
    if option_id == "approve":
        if result.get("dispatch_status") == "failed":
            status: LaunchRequestStatus = "dispatch_failed"
            message = str(result.get("dispatch_error") or "Launch dispatch failed")
        elif result.get("dispatch_status") == "launched":
            status = "approved"
            count = int(result.get("launched_count") or 0)
            message = (
                f"Launch approved and dispatched {count} agent"
                f"{'s' if count != 1 else ''}"
            )
        else:
            raise LaunchRequestError(
                "invalid_response",
                str(request.response_path),
                "approved launch response has no dispatch status",
            )
    elif option_id == "reject":
        # A rejection carrying a note stays its own reported status, so the
        # waiting agent can tell "no" apart from "no, and here is why".
        status = "feedback" if feedback else "rejected"
        message = "Launch rejected with feedback" if feedback else "Launch rejected"
    elif option_id == "feedback":
        # Legacy only: a launch gate created before feedback became a
        # declared input on `reject` answered through a third option id.
        status = "feedback"
        message = "Launch rejected with feedback"
    else:
        raise LaunchRequestError(
            "invalid_response",
            str(request.response_path),
            f"unsupported launch response option: {option_id}",
        )
    return LaunchRequestOutcome(
        status=status,
        request_id=request.request_id,
        notification_id=request.notification_id,
        selected_option_ids=selected_option_ids,
        message=message,
        response=translated_response,
    )
