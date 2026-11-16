"""Human-terminal allow, revoke, and status commands for local trust."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

from ._local_trust_checkout import resolve_local_command_trust_context
from ._local_trust_store import (
    require_human_terminal,
    status_local_commands,
    status_payload,
    store_allow,
    store_revoke,
)
from ._local_trust_support import (
    LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
    LocalCommandTrustContext,
    LocalCommandTrustManagementError,
    canonical_path,
)


def _confirm(prompt: str, *, answer: str) -> bool:
    print(prompt, end="", flush=True)
    response = sys.stdin.readline()
    return response.strip().casefold() == answer


def _print_allow_preview(context: LocalCommandTrustContext) -> None:
    print(
        "Project identity: " + json.dumps(context.project_identity, ensure_ascii=True)
    )
    print("Checkout: " + json.dumps(str(context.checkout_root), ensure_ascii=True))
    print(
        "Selected config: "
        + json.dumps(str(context.selected_config_path), ensure_ascii=True)
    )
    print(
        "Logical config location: "
        + json.dumps(context.logical_config_path, ensure_ascii=True)
    )
    print(f"Policy version: {context.projection.policy_version}")
    print(f"Digest: {context.projection.digest}")
    print("Canonical command-bearing projection:")
    # Rust's canonical JSON escapes JSON controls, so project text is never
    # interpreted as terminal styling or cursor movement.
    print(context.projection.canonical_json)


def _flag_off_message() -> str:
    return (
        "local_config_command_trust is off; local commands run in "
        "compatibility mode and trust records are not created"
    )


def allow_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> int:
    """Preview, confirm, re-read and acknowledge one exact config snapshot."""
    try:
        require_human_terminal()
        try:
            from sase.config.local_trust_enforcement import (
                is_local_command_trust_enabled as _flag_enabled,
            )

            if not _flag_enabled():
                print(_flag_off_message(), file=sys.stderr)
                return 1
        except LocalCommandTrustManagementError:
            raise
        except Exception:
            pass
        reviewed = resolve_local_command_trust_context(path)
        status = status_payload(reviewed)
        if status["status"] == "compatibility":
            print(_flag_off_message(), file=sys.stderr)
            return 1
        if status["status"] == "untrusted":
            raise LocalCommandTrustManagementError(str(status["reason"]))
        if status["status"] == "trusted":
            print("This project's current local commands are already acknowledged.")
            return 0
        _print_allow_preview(reviewed)
        if not _confirm(
            "Type allow to acknowledge this exact configuration: ", answer="allow"
        ):
            print("Trust acknowledgment declined.", file=sys.stderr)
            return 1

        current = resolve_local_command_trust_context(path)
        if (
            current.project_identity != reviewed.project_identity
            or current.logical_config_path != reviewed.logical_config_path
            or canonical_path(current.selected_config_path)
            != canonical_path(reviewed.selected_config_path)
            or current.projection.digest != reviewed.projection.digest
        ):
            raise LocalCommandTrustManagementError(
                "configuration changed; review again"
            )
        outcome = store_allow(
            reviewed.project_identity,
            reviewed.projection.digest,
        )
        if not outcome.get("changed"):
            print("This project's current local commands are already acknowledged.")
        else:
            print("Acknowledged the reviewed local command configuration.")
        return 0
    except LocalCommandTrustManagementError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"local command trust acknowledgment failed: {error}", file=sys.stderr)
        return 1


def revoke_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> int:
    """Require an interactive human confirmation and revoke this project record."""
    try:
        require_human_terminal()
        try:
            from sase.config.local_trust_enforcement import (
                is_local_command_trust_enabled as _flag_enabled,
            )

            if not _flag_enabled():
                print(_flag_off_message(), file=sys.stderr)
                return 1
        except LocalCommandTrustManagementError:
            raise
        except Exception:
            pass
        reviewed = resolve_local_command_trust_context(path)
        status = status_payload(reviewed)
        print(
            "Project identity: "
            + json.dumps(reviewed.project_identity, ensure_ascii=True)
        )
        print(
            "Selected config: "
            + json.dumps(str(reviewed.selected_config_path), ensure_ascii=True)
        )
        if status.get("acknowledged_digest"):
            print(f"Acknowledged digest: {status['acknowledged_digest']}")
        else:
            print("No current acknowledgment is stored.")
        if not _confirm(
            "Type revoke to remove this project's acknowledgment: ", answer="revoke"
        ):
            print("Trust revocation declined.", file=sys.stderr)
            return 1
        current = resolve_local_command_trust_context(path)
        if current.project_identity != reviewed.project_identity or canonical_path(
            current.selected_config_path
        ) != canonical_path(reviewed.selected_config_path):
            raise LocalCommandTrustManagementError(
                "project identity or selected config changed; review again"
            )
        require_human_terminal()
        outcome = store_revoke(reviewed.project_identity)
        message = (
            "Revoked this project's local command acknowledgment."
            if outcome.get("changed")
            else "This project had no local command acknowledgment to revoke."
        )
        print(message)
        return 0
    except LocalCommandTrustManagementError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"local command trust revocation failed: {error}", file=sys.stderr)
        return 1


def print_trust_status(
    path: str | os.PathLike[str] | None = None,
    *,
    as_json: bool = False,
    stdout: TextIO | None = None,
) -> int:
    """Print structured status, distinguishing untrusted and operational errors."""
    stream = sys.stdout if stdout is None else stdout
    try:
        payload = status_local_commands(path)
        code = 0 if payload["status"] in ("trusted", "compatibility") else 1
    except Exception as error:
        payload = {
            "schema_version": LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
            "status": "operational_error",
            "reason": str(error),
        }
        code = 2

    if as_json:
        print(
            json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2),
            file=stream,
        )
        return code
    if payload.get("status") == "operational_error":
        print(
            f"Unable to read local command trust status: {payload['reason']}",
            file=stream,
        )
        return code
    print(f"Status: {payload['status']}", file=stream)
    if payload.get("status") == "compatibility":
        print(
            "Flag local_config_command_trust: off (compatibility mode)",
            file=stream,
        )
    print(
        "Project identity: "
        + json.dumps(payload["project_identity"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Checkout: " + json.dumps(payload["checkout_root"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Selected config: "
        + json.dumps(payload["selected_config_path"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Logical config location: "
        + json.dumps(payload["logical_config_path"], ensure_ascii=True),
        file=stream,
    )
    print(f"Current digest: {payload['current_digest']}", file=stream)
    print(
        f"Acknowledged digest: {payload['acknowledged_digest'] or '(none)'}",
        file=stream,
    )
    print(f"Policy version: {payload['policy_version']}", file=stream)
    if payload["blocked_paths"]:
        print(
            "Command-bearing paths: " + ", ".join(payload["blocked_paths"]), file=stream
        )
    else:
        print("Command-bearing paths: (none)", file=stream)
    print(f"Reason: {payload['reason']}", file=stream)
    return code
