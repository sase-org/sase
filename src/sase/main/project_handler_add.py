"""Handler for ``sase project add`` and its durable operation contract."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import subprocess
import sys
from typing import Any

from sase import workspace_provider
from sase.ops.cli import emit_operation_result, load_request, resolve_request_path
from sase.ops.errors import OperationIOError
from sase.ops.names import PROJECT_ADD
from sase.project_onboarding.apply import apply_plan
from sase.project_onboarding.events import emit_event
from sase.project_onboarding.human_only import detect_actor
from sase.project_onboarding.planning import build_plan_document
from sase.project_onboarding.refs import UserRefError, parse_user_ref
from sase.project_onboarding.render import (
    print_apply_event,
    print_plan_document,
    render_plan_json,
)


def handle_add(args: argparse.Namespace) -> int:
    """Preview or execute registration of an existing repository."""

    try:
        request = _request_from_args(args)
        document = build_plan_document(request)
    except OperationIOError as exc:
        message = str(exc)
        _print_error(message)
        if not bool(getattr(args, "check", False)):
            _store_terminal_result(args, _result("failed", message), success=False)
        return 1
    except (UserRefError, ValueError) as exc:
        message = str(exc)
        _print_error(message)
        if not bool(getattr(args, "check", False)):
            _store_terminal_result(args, _result("failed", message), success=False)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI surfaces provider/planner errors
        message = f"could not plan project onboarding: {exc}"
        _print_error(message)
        if not bool(getattr(args, "check", False)):
            _store_terminal_result(args, _result("failed", message), success=False)
        return 1

    blocked = str(document.get("status") or "") == "blocked" or bool(
        document.get("blockers")
    )
    human_only = _has_human_only_blocker(document)

    if bool(getattr(args, "check", False)):
        if bool(getattr(args, "json", False)):
            print(render_plan_json(document))
        else:
            print_plan_document(document)
        return 1 if blocked else 0

    json_output = bool(getattr(args, "json", False))
    yes = bool(getattr(args, "yes", False))
    is_tty = _interactive_terminal()
    if blocked:
        event = _result(
            "blocked",
            _blocker_message(document),
            key=_project_key(document),
            name=_project_name(document),
        )
        if json_output:
            emit_event({"event": "plan", "plan": document})
            emit_event(event)
        else:
            print_plan_document(document)
            _print_error(str(event["message"]))
        _store_terminal_result(args, event, success=False)
        return 2 if human_only else 1

    if not yes:
        if not json_output:
            print_plan_document(document)
        elif is_tty:
            print_plan_document(document, file=sys.stderr)

        if not is_tty:
            message = "Not applying without a terminal; re-run with --yes."
            if json_output:
                emit_event({"event": "plan", "plan": document})
                emit_event(
                    _result(
                        "blocked",
                        message,
                        key=_project_key(document),
                        name=_project_name(document),
                    )
                )
            else:
                _print_error(message)
            event = _result(
                "blocked",
                message,
                key=_project_key(document),
                name=_project_name(document),
            )
            _store_terminal_result(args, event, success=False)
            return 1

        try:
            answer = input("Apply? [y/N] ").strip().casefold()
        except (EOFError, OSError):
            answer = ""
        if answer not in {"y", "yes"}:
            message = (
                "Project registration was declined; no onboarding effects were applied."
            )
            event = _result(
                "blocked",
                message,
                key=_project_key(document),
                name=_project_name(document),
            )
            if json_output:
                emit_event({"event": "plan", "plan": document})
                emit_event(event)
            else:
                print_apply_event(event)
            _store_terminal_result(args, event, success=False)
            return 1

    plan_already_shown = not yes

    def send(event: Mapping[str, Any]) -> None:
        normalized = dict(event)
        if json_output:
            emit_event(normalized)
        elif normalized.get("event") == "plan":
            if not plan_already_shown:
                plan = normalized.get("plan")
                if isinstance(plan, dict):
                    print_plan_document(plan)
        else:
            print_apply_event(normalized)

    result = apply_plan(request, emit=send, plan=document)
    final_event = dict(result)
    if (
        not json_output
        and is_tty
        and final_event.get("status") == "ok"
        and final_event.get("next_argv")
    ):
        final_event = _offer_init(final_event)
    success = final_event.get("status") == "ok"
    result_written = _store_terminal_result(args, final_event, success=success)
    if not success and final_event.get("status") == "partial" and not json_output:
        print_apply_event(final_event)
    if not result_written:
        return 1
    if success:
        return 0
    return 1


def _request_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Build intent from argv and verify a durable sidecar against that intent."""

    actor = detect_actor(stderr=sys.stderr)
    target = _target_for_ref(str(getattr(args, "ref", "")))
    requested = _requested_for_args(args)
    cli_request: dict[str, Any] = {
        "mode": "add",
        "actor": actor,
        "target": target,
        "requested": requested,
    }
    if resolve_request_path(args) is None:
        return cli_request

    durable = load_request(PROJECT_ADD, args, required=True)
    payload = durable.payload
    if not isinstance(payload, Mapping):
        raise OperationIOError(
            "invalid", "project.add request payload must be an object"
        )
    source = payload.get("request", payload)
    if not isinstance(source, Mapping):
        raise OperationIOError(
            "invalid", "project.add request must contain an intent object"
        )
    sidecar_mode = str(source.get("mode") or "add")
    sidecar_target = source.get("target")
    sidecar_requested = source.get("requested")
    if not isinstance(sidecar_target, Mapping) or not isinstance(
        sidecar_requested, Mapping
    ):
        raise OperationIOError(
            "invalid", "project.add request is missing target or requested intent"
        )

    try:
        sidecar_parsed = parse_user_ref(
            str(sidecar_target.get("ref") or ""),
            workflow_type=str(sidecar_target.get("workflow_type") or "") or None,
        )
    except UserRefError as exc:
        raise OperationIOError(
            "invalid", f"invalid target in project.add request: {exc}"
        ) from exc
    if (
        sidecar_mode != "add"
        or sidecar_parsed.identity_key.casefold()
        != str(target["identity_key"]).casefold()
        or sidecar_parsed.ref != target["ref"]
    ):
        raise OperationIOError(
            "mismatch",
            "project.add request target does not match the repository in argv",
        )

    normalized_requested = {
        "name": str(sidecar_requested.get("name") or ""),
        "aliases": [str(item) for item in list(sidecar_requested.get("aliases") or [])],
        "setup": str(sidecar_requested.get("setup") or "auto"),
        "make_current": bool(sidecar_requested.get("make_current")),
    }
    if normalized_requested != requested:
        raise OperationIOError(
            "mismatch",
            "project.add request options do not match the reviewed options in argv",
        )

    return cli_request


def _target_for_ref(raw_ref: str) -> dict[str, Any]:
    parsed = parse_user_ref(raw_ref)
    metadata = next(
        (
            item
            for item in workspace_provider.get_all_workflow_metadata()
            if item.workflow_type == parsed.workflow_type
        ),
        None,
    )
    try:
        provider_display = workspace_provider.get_display_name(parsed.workflow_type)
    except Exception:
        provider_display = parsed.workflow_type
    return {
        "workflow_type": parsed.workflow_type,
        "provider_display": str(provider_display or parsed.workflow_type),
        "storage_policy": str(getattr(metadata, "sdd_storage_policy", "") or ""),
        "ref": parsed.ref,
        "identity_key": parsed.identity_key,
        "display": parsed.display,
        "host": parsed.host,
        "owner": parsed.owner,
        "name": parsed.name,
        "web_url": parsed.web_url,
        "checkout_dir": parsed.checkout_dir,
        "project_key_base": parsed.project_key_base,
        "project_name_base": parsed.project_name_base,
    }


def _requested_for_args(args: argparse.Namespace) -> dict[str, Any]:
    if bool(getattr(args, "setup", False)):
        setup = "on"
    elif bool(getattr(args, "no_setup", False)):
        setup = "off"
    else:
        setup = "auto"
    return {
        "name": str(getattr(args, "name", None) or ""),
        "aliases": [str(alias) for alias in list(getattr(args, "alias", []) or [])],
        "setup": setup,
        "make_current": bool(getattr(args, "make_current", False)),
    }


def _offer_init(result: dict[str, Any]) -> dict[str, Any]:
    argv_value = result.get("next_argv")
    argv = [str(item) for item in argv_value] if isinstance(argv_value, list) else []
    if not argv:
        return result
    try:
        answer = input(f"Run {' '.join(argv)} now? [Y/n] ").strip().casefold()
    except (EOFError, OSError):
        answer = "n"
    if answer in {"n", "no"}:
        updated = dict(result)
        updated["status"] = "partial"
        updated["message"] = (
            str(result.get("message") or "Project registration completed")
            + f"; initialization was declined. Run `{' '.join(argv)}` to retry."
        )
        return updated
    try:
        returncode = subprocess.run(argv, check=False).returncode
    except OSError as exc:
        detail = str(exc)
    else:
        if returncode == 0:
            updated = dict(result)
            updated["next_argv"] = []
            updated["message"] = (
                str(result.get("message") or "Project is ready") + "; initialized"
            )
            return updated
        detail = f"sase init exited with status {returncode}"
    updated = dict(result)
    updated["status"] = "partial"
    updated["message"] = (
        str(result.get("message") or "Project registration completed")
        + f"; initialization failed ({detail}). Run `{' '.join(argv)}` to retry."
    )
    return updated


def _store_terminal_result(
    args: argparse.Namespace,
    event: dict[str, Any],
    *,
    success: bool,
) -> bool:
    message = str(event.get("message") or "")
    try:
        emit_operation_result(
            operation=PROJECT_ADD,
            success=success,
            message=message,
            error=None if success else message,
            payload=event,
            args=args,
        )
        return True
    except Exception as exc:  # result IO failure must remain visible
        _print_error(f"could not write project.add result: {exc}")
        return False


def _result(
    status: str,
    message: str,
    *,
    key: str = "",
    name: str = "",
) -> dict[str, Any]:
    return {
        "event": "result",
        "status": status,
        "project": {"key": key, "name": name},
        "next_argv": [],
        "message": message,
    }


def _project_key(document: Mapping[str, Any]) -> str:
    project = document.get("project")
    return str(project.get("key") or "") if isinstance(project, Mapping) else ""


def _project_name(document: Mapping[str, Any]) -> str:
    project = document.get("project")
    return str(project.get("name") or "") if isinstance(project, Mapping) else ""


def _has_human_only_blocker(document: Mapping[str, Any]) -> bool:
    blockers = document.get("blockers")
    return isinstance(blockers, list) and any(
        isinstance(blocker, Mapping) and blocker.get("code") == "human_only"
        for blocker in blockers
    )


def _blocker_message(document: Mapping[str, Any]) -> str:
    blockers = document.get("blockers")
    messages = []
    if isinstance(blockers, list):
        for blocker in blockers:
            if isinstance(blocker, Mapping):
                detail = str(blocker.get("message") or blocker.get("detail") or "")
                if detail:
                    messages.append(detail)
    return "; ".join(messages) or "project onboarding is blocked"


def _interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


__all__ = ["handle_add"]
