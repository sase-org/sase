"""Typed sudo notification review and terminal handoff."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.app import SuspendNotSupported

from sase.ace.tui.actions._durable_ops import sase_argv
from sase.feature_flags import SASE_FEATURE_FLAGS_ENV
from sase.sudo.gate import DENY_OPTION_ID

from ._notification_gate_execution import GateSubmission, submit_gate_execution_task
from ._notification_utils import request_notification_agents_refresh

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...modals import (
        SudoCommandReviewData,
        SudoRequestModalData,
        SudoRequestModalResult,
    )


@dataclass(frozen=True)
class _SudoCliMessage:
    text: str
    severity: str = "information"


def handle_sudo_request(app: object, notification: Notification) -> bool:
    """Load a verified sudo bundle off-pump and open the typed review modal."""
    from ...util.pump_tasks import spawn_pump_free_task

    async def load_and_open() -> None:
        try:
            data = await asyncio.to_thread(_load_sudo_request_modal_data, notification)
        except Exception as exc:
            app.notify(  # type: ignore[attr-defined]
                f"Could not open sudo request: {exc}; press d on the notification to debug",
                severity="error",
            )
            return

        from ...modals import SudoRequestModal, SudoRequestModalResult
        from sase.notification_gates.debug import debug_context_from_notification

        def on_dismiss(result: object) -> None:
            if not isinstance(result, SudoRequestModalResult):
                return
            if result.action == "deny":
                submit_gate_execution_task(
                    app,
                    notification,
                    GateSubmission(
                        selected_option_ids=(DENY_OPTION_ID,),
                        feedback=result.feedback,
                    ),
                )
                return
            _run_sudo_terminal_handoff(app, notification, data, result)

        app.push_screen(  # type: ignore[attr-defined]
            SudoRequestModal(
                data,
                debug_context=debug_context_from_notification(notification),
            ),
            on_dismiss,
        )

    task = spawn_pump_free_task(
        app,
        load_and_open(),
        name=f"sudo-request-open:{notification.id}",
        registry_attr="_sudo_request_open_tasks",
    )
    if task is None:
        app.notify("Sudo request loading is unavailable", severity="error")  # type: ignore[attr-defined]
        return False
    return True


def _load_sudo_request_modal_data(notification: Notification) -> SudoRequestModalData:
    """Read and verify one sudo bundle for the typed modal."""
    from ...modals import (
        SudoCommandReviewData,
        SudoRequestModalData,
        sudo_request_expires_at,
    )
    from ...modals.notification_modal_tags import notification_origin_agent
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import resolve_notification_bundle
    from sase.notification_gates.summary import gate_summary_from_notification

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy:
        raise GateError(
            "missing_gate",
            notification.id,
            "notification does not reference a neutral sudo gate",
        )
    envelope, adapter = load_and_verify_bundle(bundle.root)
    if adapter.kind != "sudo" or envelope.get("kind") != "sudo":
        raise GateError(
            "missing_gate",
            notification.id,
            "notification does not reference a sudo gate",
        )
    sudo_payload = _sudo_payload(envelope)
    request = _sudo_request(sudo_payload)
    manifest = _manifest(sudo_payload)
    review_commands = _review_commands(request)
    commands = tuple(
        _command_data(command, index) for index, command in enumerate(review_commands)
    )
    summary = gate_summary_from_notification(notification)
    return SudoRequestModalData(
        request_id=str(envelope.get("request_id") or notification.id),
        title=_title(envelope, summary.title if summary is not None else None),
        sender=notification.sender,
        reason=_str_field(request, "reason", default=""),
        commands=commands,
        run_as=_str_field(manifest, "run_as", default="root"),
        cwd=_str_field(manifest, "cwd", default=""),
        env=_env_items(manifest.get("env")),
        timeout_seconds=_manifest_timeout(manifest),
        stop_policy=(
            "stop_on_failure"
            if bool(manifest.get("stop_on_failure", True))
            else "continue_on_failure"
        ),
        output_policy=_str_field(manifest, "output_to_agent", default="none"),
        machine=_target_label(sudo_payload),
        manifest_sha256=_str_field(sudo_payload, "manifest_sha256", default=""),
        risk_badges=_str_tuple(sudo_payload.get("risk_badges")),
        requester=notification_origin_agent(notification),
        project=_project(notification, envelope),
        expires_at=sudo_request_expires_at(envelope),
        created_at=_optional_str(envelope.get("created_at")),
    )


def _run_sudo_terminal_handoff(
    app: object,
    notification: Notification,
    data: SudoRequestModalData,
    result: SudoRequestModalResult,
) -> None:
    """Run ``sase sudo answer`` in a real terminal and toast the outcome."""
    from ...util.external_tool import suspend_for_external_tool

    argv = _sudo_answer_argv(data.request_id, result.command_ids)
    env = {
        key: value for key, value in os.environ.items() if key != SASE_FEATURE_FLAGS_ENV
    }
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        with suspend_for_external_tool(
            app,
            action="sudo_answer",
            tool_kind="sudo",
            command=argv[0],
            status_message=_terminal_banner(data, result.command_ids),
        ):
            completed = subprocess.run(
                argv,
                check=False,
                env=env,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
            )
    except SuspendNotSupported:
        _notify(
            app,
            "Could not open a trusted terminal for sudo authentication; gate remains pending",
            severity="error",
        )
        _refresh_after_sudo(app, notification)
        return
    except OSError as exc:
        _notify(
            app,
            f"Could not run sudo authentication handoff: {exc}; gate remains pending",
            severity="error",
        )
        _refresh_after_sudo(app, notification)
        return

    payload = _json_payload(completed.stdout)
    message = _sudo_cli_message(completed.returncode, payload)
    _notify(app, message.text, severity=message.severity)
    _refresh_after_sudo(app, notification)


def _sudo_answer_argv(request_id: str, command_ids: tuple[str, ...]) -> list[str]:
    argv = sase_argv("sudo", "answer", request_id, "--run", "--json")
    for command_id in command_ids:
        argv.extend(["--command", command_id])
    return argv


def _terminal_banner(data: SudoRequestModalData, command_ids: tuple[str, ...]) -> str:
    command_summary = ", ".join(command_ids) if command_ids else "all commands"
    return (
        "SASE sudo authentication handoff. "
        f"Request {data.request_id}; reviewed commands: {command_summary}."
    )


def _sudo_cli_message(
    returncode: int,
    payload: Mapping[str, Any] | None,
) -> _SudoCliMessage:
    if returncode == 0 and payload is not None and payload.get("status") == "answered":
        outcome = str(payload.get("outcome") or "")
        if outcome == "command_failed":
            return _SudoCliMessage(
                "Sudo authentication completed, but a selected command failed",
                "warning",
            )
        return _SudoCliMessage("Sudo request completed")

    outcome = str(payload.get("outcome") or "") if payload is not None else ""
    code = str(payload.get("code") or "") if payload is not None else ""
    message = str(payload.get("message") or "") if payload is not None else ""
    if outcome == "authentication_failed":
        return _SudoCliMessage(
            "Sudo authentication failed; gate remains pending",
            "warning",
        )
    if outcome == "cancellation":
        return _SudoCliMessage(
            "Sudo authentication was cancelled; gate remains pending",
            "warning",
        )
    if outcome == "timeout":
        return _SudoCliMessage("Sudo authentication timed out; gate remains pending")
    if outcome == "lock_contention":
        return _SudoCliMessage(
            "Another sudo authentication handoff is active; gate remains pending",
            "warning",
        )
    if outcome == "missing_tty":
        return _SudoCliMessage(
            "No trusted terminal was available for sudo; gate remains pending",
            "error",
        )
    if code or message:
        suffix = message or code
        return _SudoCliMessage(f"Sudo handoff failed: {suffix}", "error")
    return _SudoCliMessage("Sudo handoff failed; gate remains pending", "error")


def _refresh_after_sudo(app: object, notification: Notification) -> None:
    refresh_count = getattr(app, "_refresh_notification_count", None)
    if callable(refresh_count):
        refresh_count()
    request_notification_agents_refresh(app, notification=notification)


def _notify(app: object, message: str, *, severity: str) -> None:
    notify = getattr(app, "notify", None)
    if not callable(notify):
        return
    try:
        notify(message, severity=severity)
    except TypeError:
        notify(message)


def _json_payload(value: object) -> Mapping[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _sudo_payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    from sase.notification_gates.models import GateError

    payload = envelope.get("payload")
    sudo_payload = payload.get("sudo") if isinstance(payload, Mapping) else None
    if not isinstance(sudo_payload, Mapping):
        raise GateError("invalid_sudo_payload", "payload.sudo", "sudo payload missing")
    return sudo_payload


def _sudo_request(sudo_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    from sase.notification_gates.models import GateError

    request = sudo_payload.get("request")
    if not isinstance(request, Mapping):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo.request", "sudo request missing"
        )
    return request


def _manifest(sudo_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    from sase.notification_gates.models import GateError

    manifest = sudo_payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest",
            "sudo manifest missing",
        )
    return manifest


def _review_commands(request: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    from sase.notification_gates.models import GateError

    commands = request.get("commands")
    if not isinstance(commands, list) or not commands:
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.request.commands",
            "sudo manifest commands missing",
        )
    normalized: list[Mapping[str, Any]] = []
    for index, command in enumerate(commands):
        if not isinstance(command, Mapping):
            raise GateError(
                "invalid_sudo_payload",
                f"payload.sudo.request.commands[{index}]",
                "sudo command must be an object",
            )
        normalized.append(command)
    return normalized


def _command_data(
    command: Mapping[str, Any],
    index: int,
) -> SudoCommandReviewData:
    from ...modals import SudoCommandReviewData
    from sase.notification_gates.models import GateError

    command_id = command.get("id")
    argv = command.get("argv")
    executable_sha256 = command.get("executable_sha256")
    if not isinstance(command_id, str) or not command_id:
        raise GateError(
            "invalid_sudo_payload",
            f"payload.sudo.manifest.commands[{index}].id",
            "sudo command id missing",
        )
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise GateError(
            "invalid_sudo_payload",
            f"payload.sudo.manifest.commands[{index}].argv",
            "sudo command argv missing",
        )
    if not isinstance(executable_sha256, str):
        raise GateError(
            "invalid_sudo_payload",
            f"payload.sudo.manifest.commands[{index}].executable_sha256",
            "sudo executable hash missing",
        )
    return SudoCommandReviewData(
        id=command_id,
        argv=tuple(argv),
        executable_sha256=executable_sha256,
    )


def _manifest_timeout(manifest: Mapping[str, Any]) -> int:
    commands = manifest.get("commands")
    if not isinstance(commands, list):
        return 0
    values: list[int] = []
    for command in commands:
        if not isinstance(command, Mapping):
            continue
        timeout = _int_field(command, "timeout_seconds", default=0)
        if timeout:
            values.append(timeout)
    return max(values) if values else 0


def _target_label(sudo_payload: Mapping[str, Any]) -> str | None:
    target = sudo_payload.get("target")
    if isinstance(target, Mapping):
        requested = _optional_str(target.get("requested_machine"))
        host = _optional_str(target.get("host"))
        if requested and host and requested != host:
            return f"{requested} ({host})"
        return requested or host
    request = sudo_payload.get("request")
    if isinstance(request, Mapping):
        return _optional_str(request.get("machine"))
    return None


def _title(envelope: Mapping[str, Any], fallback: str | None) -> str:
    presentation = envelope.get("presentation")
    if isinstance(presentation, Mapping):
        title = presentation.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return fallback or "Sudo request"


def _project(notification: Notification, envelope: Mapping[str, Any]) -> str | None:
    for key in ("project", "project_name"):
        value = notification.action_data.get(key)
        if value:
            return value
    producer = envelope.get("producer")
    if isinstance(producer, Mapping):
        for key in ("project", "project_name"):
            value = producer.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _str_field(
    value: Mapping[str, Any],
    key: str,
    *,
    default: str,
) -> str:
    raw = value.get(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def _optional_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_field(value: Mapping[str, Any], key: str, *, default: int) -> int:
    raw = value.get(key)
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return default


def _env_items(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(
        (str(key), str(env_value))
        for key, env_value in sorted(value.items(), key=lambda item: str(item[0]))
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


__all__ = [
    "handle_sudo_request",
]
