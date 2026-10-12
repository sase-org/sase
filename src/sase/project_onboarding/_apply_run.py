"""Plan validation and ordered project onboarding execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import time
from typing import Any

from sase.project_onboarding.facts import gather_facts
from sase.project_onboarding.human_only import detect_actor
from sase.project_onboarding.journal import (
    record_intent,
    set_journal_status,
    update_step,
)
from sase.project_onboarding.planning import build_plan_document
from sase.project_onboarding.refs import UserRefError, parse_user_ref
from sase.project_onboarding._apply_effects import EFFECTS, RunContext, StepFailed
from sase.project_onboarding._apply_locks import ApplyLockTimeout, hold_apply_locks

_ADD_STEP_ORDER = ("checkout", "reenable", "identity", "manage", "current")


def run_request(
    request: Mapping[str, Any],
    *,
    send: Callable[..., None],
    proc_id: str,
    preview: Mapping[str, Any] | None,
    lock_timeout: float,
) -> dict[str, Any]:
    mode = str(request.get("mode") or "add")
    raw_target = request.get("target")
    target_map = raw_target if isinstance(raw_target, Mapping) else {}
    identity_key = str(target_map.get("identity_key") or "")
    checkout_dir = str(target_map.get("checkout_dir") or "")
    display = str(target_map.get("display") or "")
    workflow_type = str(target_map.get("workflow_type") or "")
    ref = str(target_map.get("ref") or "")
    if not identity_key or not checkout_dir or not workflow_type or not ref:
        parsed = _parse_target_ref(ref, workflow_type)
        if parsed is None:
            return _finish(
                send,
                status="blocked",
                key="",
                name="",
                next_argv=[],
                message=(
                    "cannot onboard an unrecognized repository reference; "
                    "re-check the input and retry"
                    if ref
                    else "cannot onboard without a repository reference"
                ),
            )
        identity_key = identity_key or parsed["identity_key"]
        checkout_dir = checkout_dir or parsed["checkout_dir"]
        display = display or parsed["display"]
        workflow_type = workflow_type or parsed["workflow_type"]
        ref = parsed["ref"]
    if not identity_key:
        return _finish(
            send,
            status="blocked",
            key="",
            name="",
            next_argv=[],
            message="cannot onboard without a repository identity",
        )
    try:
        with hold_apply_locks(identity_key, checkout_dir, timeout=lock_timeout):
            return _apply_locked(
                request,
                mode=mode,
                identity_key=identity_key,
                checkout_dir=checkout_dir,
                display=display or ref,
                workflow_type=workflow_type,
                ref=ref,
                send=send,
                proc_id=proc_id,
                preview=preview,
            )
    except ApplyLockTimeout as exc:
        return _finish(
            send,
            status="blocked",
            key="",
            name="",
            next_argv=[],
            message=(
                f"another onboarding operation holds {exc}; "
                "wait for it to finish, then re-run the same command"
            ),
        )


def _apply_locked(
    request: Mapping[str, Any],
    *,
    mode: str,
    identity_key: str,
    checkout_dir: str,
    display: str,
    workflow_type: str,
    ref: str,
    send: Callable[..., None],
    proc_id: str,
    preview: Mapping[str, Any] | None,
) -> dict[str, Any]:
    actor = str(request.get("actor") or detect_actor())
    target = {
        "workflow_type": workflow_type,
        "ref": ref,
        "identity_key": identity_key,
        "display": display,
        "checkout_dir": checkout_dir,
    }
    observed = gather_facts(target, mode, actor=actor)
    document = build_plan_document(request, facts=observed)
    send({"event": "plan", "plan": document})
    plan_target = document.get("target")
    plan_target_map = plan_target if isinstance(plan_target, Mapping) else {}
    canonical_ref = str(plan_target_map.get("ref") or ref)
    canonical_display = str(plan_target_map.get("display") or display)
    fingerprint = str(document.get("intent_fingerprint") or "")
    setup_map = document.get("setup")
    setup_enabled = bool(isinstance(setup_map, Mapping) and setup_map.get("enabled"))
    plan_project = document.get("project")
    plan_project_map = plan_project if isinstance(plan_project, Mapping) else {}
    actual_key = str(plan_project_map.get("key") or "")
    actual_name = str(plan_project_map.get("name") or canonical_display or actual_key)
    if preview is not None:
        preview_fingerprint = str(preview.get("intent_fingerprint") or "")
        if preview_fingerprint and preview_fingerprint != fingerprint:
            return _finish(
                send,
                status="blocked",
                key=actual_key,
                name=actual_name,
                next_argv=[],
                message=(
                    "the onboarding plan changed since it was reviewed; "
                    "re-run check, then apply the fresh plan"
                ),
            )
    blockers = document.get("blockers")
    blocker_list = list(blockers) if isinstance(blockers, list) else []
    if str(document.get("status") or "") == "blocked" or blocker_list:
        return _finish(
            send,
            status="blocked",
            key=actual_key,
            name=actual_name,
            next_argv=[],
            message=_blocker_message(blocker_list),
        )
    if mode == "create" and _step_state(document, "create_remote") == "pending":
        return _finish(
            send,
            status="blocked",
            key=actual_key,
            name=actual_name,
            next_argv=[],
            message=(
                "creating a remote repository is owned by "
                "`sase project create`, not by apply"
            ),
        )
    ctx = RunContext(
        identity_key=identity_key,
        display=canonical_display,
        workflow_type=workflow_type,
        ref=canonical_ref,
        checkout_dir=checkout_dir,
        mode=mode,
        actor=actor,
        fingerprint=fingerprint,
        setup_enabled=setup_enabled,
        requested=_requested(request),
        actual_key=actual_key,
        actual_name=actual_name,
        checkout_done_initially=_step_state(document, "checkout") == "done",
    )
    record_intent(
        identity_key=identity_key,
        ref=canonical_ref,
        display=canonical_display,
        workflow_type=workflow_type,
        mode=mode,
        intent_fingerprint=fingerprint,
        proc_id=proc_id,
        setup_required=setup_enabled,
    )
    for step_id in _ADD_STEP_ORDER:
        step = _find_step(document, step_id)
        if step is None or _step_state(document, step_id) != "pending":
            continue
        if bool(step.get("handoff")):
            continue
        if not _run_step(ctx, step_id, step, send):
            break
    return _finish_run(ctx, document, send)


def _run_step(
    ctx: RunContext,
    step_id: str,
    step: Mapping[str, Any],
    send: Callable[..., None],
) -> bool:
    label = str(step.get("label") or step_id)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    started = time.monotonic()
    update_step(ctx.identity_key, step_id, status="running", display=ctx.display)
    send(
        {
            "event": "step",
            "id": step_id,
            "status": "running",
            "label": label,
            "started_at": started_at,
        }
    )
    try:
        EFFECTS[step_id](ctx)
    except StepFailed as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        update_step(
            ctx.identity_key,
            step_id,
            status="failed",
            message=exc.message,
            display=ctx.display,
        )
        event: dict[str, Any] = {
            "event": "step",
            "id": step_id,
            "status": "failed",
            "label": label,
            "elapsed_ms": elapsed_ms,
            "message": exc.message,
        }
        if exc.hint:
            event["hint"] = exc.hint
        send(event)
        ctx.failed = (step_id, label, exc.message, exc.hint)
        return False
    elapsed_ms = int((time.monotonic() - started) * 1000)
    update_step(ctx.identity_key, step_id, status="done", display=ctx.display)
    send(
        {
            "event": "step",
            "id": step_id,
            "status": "done",
            "label": label,
            "elapsed_ms": elapsed_ms,
        }
    )
    ctx.completed.append(step_id)
    return True


def _finish_run(
    ctx: RunContext,
    document: Mapping[str, Any],
    send: Callable[..., None],
) -> dict[str, Any]:
    next_argv = _next_argv(document, ctx.actual_key)
    if ctx.failed is None:
        set_journal_status(
            ctx.identity_key,
            "complete",
            display=ctx.display,
            project_key=ctx.actual_key,
        )
        message = f"{ctx.display} is ready"
        if next_argv:
            message += f"; run `{' '.join(next_argv)}` to initialize"
        return _finish(
            send,
            status="ok",
            key=ctx.actual_key,
            name=ctx.actual_name,
            next_argv=next_argv,
            message=message,
        )
    _, label, detail, hint = ctx.failed
    registered = ctx.checkout_done_initially or bool(ctx.completed)
    status = "partial" if registered else "failed"
    if registered:
        message = (
            f"{label} failed: {detail} "
            "Registration is preserved; re-run the same command to resume."
        )
    else:
        message = f"{label} failed before registration: {detail}"
    if hint:
        message += f" {hint}"
    return _finish(
        send,
        status=status,
        key=ctx.actual_key,
        name=ctx.actual_name,
        next_argv=next_argv if registered else [],
        message=message,
    )


def _finish(
    send: Callable[..., None],
    *,
    status: str,
    key: str,
    name: str,
    next_argv: list[str],
    message: str,
) -> dict[str, Any]:
    result = {
        "event": "result",
        "status": status,
        "project": {"key": key, "name": name},
        "next_argv": list(next_argv),
        "message": message,
    }
    send(result)
    return result


def _requested(request: Mapping[str, Any]) -> dict[str, Any]:
    raw = request.get("requested")
    requested = raw if isinstance(raw, Mapping) else {}
    aliases = requested.get("aliases") or []
    return {
        "name": str(requested.get("name") or ""),
        "aliases": [str(alias) for alias in aliases],
        "setup": str(requested.get("setup") or "auto"),
        "make_current": bool(requested.get("make_current")),
    }


def _parse_target_ref(ref: str, workflow_type: str) -> dict[str, str] | None:
    if not ref:
        return None
    try:
        parsed = parse_user_ref(ref, workflow_type=workflow_type or None)
    except UserRefError:
        return None
    return {
        "identity_key": parsed.identity_key,
        "display": parsed.display,
        "workflow_type": parsed.workflow_type,
        "ref": parsed.ref,
        "checkout_dir": parsed.checkout_dir,
    }


def _find_step(document: Mapping[str, Any], step_id: str) -> Mapping[str, Any] | None:
    steps = document.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, Mapping) and step.get("id") == step_id:
            return step
    return None


def _step_state(document: Mapping[str, Any], step_id: str) -> str:
    step = _find_step(document, step_id)
    if step is None:
        return ""
    return str(step.get("state") or "")


def _blocker_message(blockers: list[Any]) -> str:
    lines: list[str] = []
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            continue
        message = str(blocker.get("message") or "")
        hint = str(blocker.get("hint") or "")
        if message and hint:
            lines.append(f"{message} ({hint})")
        elif message:
            lines.append(message)
    if not lines:
        lines.append("the onboarding plan is blocked")
    lines.append("Resolve the blocker, then re-run check.")
    return " ".join(lines)


def _next_argv(document: Mapping[str, Any], key: str) -> list[str]:
    if not key:
        return []
    steps = document.get("steps")
    if not isinstance(steps, list):
        return []
    for step in steps:
        if (
            isinstance(step, Mapping)
            and step.get("id") == "init"
            and step.get("state") == "pending"
            and bool(step.get("handoff"))
        ):
            return ["sase", "init", "-p", key]
    return []


__all__ = ["run_request"]
