"""Public facade for mobile notification gateway host bridge helpers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from sase.integrations._mobile_notification_actions import (
    execute_mobile_gate_action,
    execute_mobile_question_action,
)
from sase.integrations._mobile_notification_attachments import (
    build_mobile_attachment_manifests,
)
from sase.integrations._mobile_notification_models import (
    MobileAttachmentManifest,
    MobileGateActionError,
    MobileGateActionResult,
    MobileNotificationBridgeCounts,
    MobileNotificationBridgeRow,
    MobileNotificationBridgeSnapshot,
)
from sase.integrations._mobile_notification_snapshot import (
    read_mobile_notification_snapshot,
    resolve_mobile_notification_detail,
)

__all__ = [
    "MobileAttachmentManifest",
    "MobileGateActionError",
    "MobileGateActionResult",
    "MobileNotificationBridgeCounts",
    "MobileNotificationBridgeRow",
    "MobileNotificationBridgeSnapshot",
    "build_mobile_attachment_manifests",
    "execute_mobile_gate_action",
    "execute_mobile_question_action",
    "handle_mobile_notification_bridge",
    "read_mobile_notification_snapshot",
    "resolve_mobile_notification_detail",
]


MOBILE_NOTIFICATION_WIRE_SCHEMA_VERSION = 5


def handle_mobile_notification_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed notification mutation over JSON stdin/stdout."""
    try:
        request = _read_bridge_request(stdin)
        operation = getattr(args, "mobile_notification_bridge_subcommand", None)
        if operation not in {"gate-action", "question-action"}:
            raise MobileGateActionError(
                "invalid_request", "operation", "unknown notification bridge operation"
            )
        schema_version = request.get("schema_version")
        # Kept in sync with `validate_schema` in
        # crates/sase_core/src/notifications/mobile.rs: both sides of the
        # bridge must accept the same schema_version range.
        if (
            not isinstance(schema_version, int)
            or not 1 <= schema_version <= MOBILE_NOTIFICATION_WIRE_SCHEMA_VERSION
        ):
            raise MobileGateActionError(
                "invalid_request", "schema_version", "unsupported schema_version"
            )
        prefix = request.get("prefix")
        if not isinstance(prefix, str) or not prefix:
            raise MobileGateActionError(
                "invalid_request", "prefix", "prefix must be a non-empty string"
            )
        if operation == "gate-action":
            selected_option_ids = request.get("selected_option_ids")
            feedback = request.get("feedback")
            if (
                not isinstance(selected_option_ids, list)
                or not selected_option_ids
                or not all(isinstance(value, str) for value in selected_option_ids)
            ):
                raise MobileGateActionError(
                    "invalid_request",
                    "selected_option_ids",
                    "selected_option_ids must be a non-empty array of strings",
                )
            if feedback is not None and not isinstance(feedback, str):
                raise MobileGateActionError(
                    "invalid_request", "feedback", "feedback must be a string or null"
                )
            option_inputs = request.get("option_inputs")
            if option_inputs is not None:
                if schema_version < 5:
                    raise MobileGateActionError(
                        "invalid_request",
                        "option_inputs",
                        "option_inputs requires schema_version 5 or newer",
                    )
                if not isinstance(option_inputs, dict) or not all(
                    isinstance(key, str) for key in option_inputs
                ):
                    raise MobileGateActionError(
                        "invalid_request",
                        "option_inputs",
                        "option_inputs must be an object keyed by option id",
                    )
            result = execute_mobile_gate_action(
                prefix,
                selected_option_ids,
                feedback=feedback,
                option_inputs=option_inputs,
            )
        else:
            choice = request.get("choice")
            if choice not in {"answer", "custom"}:
                raise MobileGateActionError(
                    "invalid_request", "choice", "unsupported question action choice"
                )
            result = execute_mobile_question_action(
                prefix,
                choice,
                question_index=request.get("question_index"),
                selected_option_id=request.get("selected_option_id"),
                selected_option_label=request.get("selected_option_label"),
                selected_option_index=request.get("selected_option_index"),
                custom_answer=request.get("custom_answer"),
                global_note=request.get("global_note"),
            )
    except MobileGateActionError as exc:
        json.dump(
            {"code": exc.code, "target": exc.target, "message": str(exc)},
            stderr,
            separators=(",", ":"),
        )
        stderr.write("\n")
        return _bridge_error_exit_code(exc.code)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        json.dump(
            {"code": "invalid_request", "target": "request", "message": str(exc)},
            stderr,
            separators=(",", ":"),
        )
        stderr.write("\n")
        return 2

    json.dump(
        {
            "schema_version": MOBILE_NOTIFICATION_WIRE_SCHEMA_VERSION,
            "action_kind": result.action_kind,
            "prefix": result.prefix,
            "notification_id": result.notification_id,
            "state": "available",
            "response_file": result.response_file,
            "response_json": result.response_json,
            "message": result.message,
        },
        stdout,
        separators=(",", ":"),
    )
    stdout.write("\n")
    return 0


def _read_bridge_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        raise MobileGateActionError(
            "invalid_request", "request", "request JSON is required"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise MobileGateActionError(
            "invalid_request", "request", "request JSON must be an object"
        )
    return payload


def _bridge_error_exit_code(code: str) -> int:
    if code in {"not_found"}:
        return 4
    if code in {"conflict_already_handled", "already_answered", "gate_cancelled"}:
        return 5
    if code == "gone_stale":
        return 6
    if code == "unsupported_action":
        return 7
    return 2
