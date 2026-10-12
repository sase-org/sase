"""Serialized convergent execution of project onboarding plans.

``apply_plan`` runs the add-mode steps of a plan document derived by
:mod:`sase.project_onboarding.planning` over facts from
:mod:`sase.project_onboarding.facts`. Add-mode order is checkout,
reenable, identity, manage, current, with init as a handoff that is
never executed here. ``create_remote`` belongs to ``sase project
create`` and is refused, never executed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import fcntl
import hashlib
import time
from typing import Any

from sase import workspace_provider
from sase.project_onboarding.discovery import (
    identity_for_origin,
    read_git_origin_url,
    resolve_git_dir,
)
from sase.project_onboarding.events import emit_event
from sase.project_onboarding.facts import gather_facts
from sase.project_onboarding.human_only import detect_actor
from sase.project_onboarding.journal import (
    journals_dir,
    record_intent,
    set_journal_status,
    update_step,
)
from sase.project_onboarding.manage import ManagementError, manage_repository
from sase.project_onboarding.planning import build_plan_document
from sase.project_onboarding.refs import UserRefError, parse_user_ref

_ADD_STEP_ORDER = ("checkout", "reenable", "identity", "manage", "current")
_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05


class _StepFailed(RuntimeError):
    """One ordered step effect could not reach its postcondition."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class _LockTimeout(TimeoutError):
    """A cooperating onboarding lock stayed held past the bounded wait."""


def apply_plan(
    request: Mapping[str, Any],
    *,
    emit: Callable[..., None] | None = None,
    proc_id: str = "",
    plan: Mapping[str, Any] | None = None,
    lock_timeout: float = _LOCK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute the add-mode steps of *request* and return the result event.

    The plan is re-derived under cooperating locks before any effect; a
    changed or blocked plan is reported before the checkout is touched.
    Exactly one ``result`` event is emitted per call. ``plan`` optionally
    carries the document the caller reviewed, so a changed plan is
    reported instead of executed. Unexpected internal errors are
    returned as a failed result with journal evidence preserved.
    """

    send = emit_event if emit is None else emit
    try:
        return _apply_plan(
            request,
            send=send,
            proc_id=proc_id,
            preview=plan,
            lock_timeout=lock_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - executor ends with one result
        identity = ""
        try:
            identity = str((request.get("target") or {}).get("identity_key"))
        except Exception:
            identity = ""
        message = f"internal error during project onboarding: {exc}"
        if identity:
            try:
                set_journal_status(identity, "failed", message=message)
            except Exception:
                pass
        result = {
            "event": "result",
            "status": "failed",
            "project": {"key": "", "name": ""},
            "next_argv": [],
            "message": message,
        }
        try:
            send(result)
        except Exception:
            pass
        return result


def _apply_plan(
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
        with _hold_apply_locks(identity_key, checkout_dir, timeout=lock_timeout):
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
    except _LockTimeout as exc:
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
    ctx = _RunContext(
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
    ctx: _RunContext,
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
        _EFFECTS[step_id](ctx)
    except _StepFailed as exc:
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
    ctx: _RunContext,
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


class _RunContext:
    """Mutable execution state shared by the ordered step effects."""

    def __init__(
        self,
        *,
        identity_key: str,
        display: str,
        workflow_type: str,
        ref: str,
        checkout_dir: str,
        mode: str,
        actor: str,
        fingerprint: str,
        setup_enabled: bool,
        requested: dict[str, Any],
        actual_key: str,
        actual_name: str,
        checkout_done_initially: bool,
    ) -> None:
        self.identity_key = identity_key
        self.display = display
        self.workflow_type = workflow_type
        self.ref = ref
        self.checkout_dir = checkout_dir
        self.mode = mode
        self.actor = actor
        self.fingerprint = fingerprint
        self.setup_enabled = setup_enabled
        self.requested = requested
        self.actual_key = actual_key
        self.actual_name = actual_name
        self.actual_checkout = checkout_dir
        self.checkout_done_initially = checkout_done_initially
        self.completed: list[str] = []
        self.failed: tuple[str, str, str, str] | None = None


def _effect_checkout(ctx: _RunContext) -> None:
    try:
        parsed = parse_user_ref(ctx.ref, workflow_type=ctx.workflow_type or None)
    except UserRefError as exc:
        raise _StepFailed(str(exc)) from exc
    fresh = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    checkout = fresh.get("checkout")
    fresh_state = (
        str(checkout.get("state") or "") if isinstance(checkout, Mapping) else ""
    )
    record = fresh.get("record")
    if fresh_state == "matching" and isinstance(record, Mapping):
        _adopt_record(ctx, record)
        return
    try:
        resolved = workspace_provider.resolve_ref(parsed.ref, ctx.workflow_type)
    except Exception as exc:
        if fresh_state == "empty_dir" and _remove_if_still_empty(ctx.checkout_dir):
            try:
                resolved = workspace_provider.resolve_ref(parsed.ref, ctx.workflow_type)
            except Exception as retry_exc:
                raise _StepFailed(
                    _short_error(retry_exc),
                    hint="Re-run the same command to retry the clone.",
                ) from retry_exc
        else:
            raise _StepFailed(
                _short_error(exc),
                hint="Re-run the same command to retry the clone.",
            ) from exc
    _adopt_resolved(ctx, resolved)
    origin = read_git_origin_url(ctx.actual_checkout)
    if resolve_git_dir(ctx.actual_checkout) is None:
        raise _StepFailed(
            f"{ctx.actual_checkout} is not a Git checkout after resolving",
            hint="Remove the unexpected path, then re-run the same command.",
        )
    if _origin_identity(origin, ctx.workflow_type) != ctx.identity_key.casefold():
        raise _StepFailed(
            "the resolved checkout does not match the reviewed repository",
            hint="Remove the unexpected checkout, then re-run the same command.",
        )
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    post_record = post.get("record")
    if isinstance(post_record, Mapping):
        _adopt_record(ctx, post_record)


def _effect_reenable(ctx: _RunContext) -> None:
    from sase.main.project_handler_lifecycle import set_project_state_locked

    if not ctx.actual_key:
        raise _StepFailed("no project record is available to re-enable")
    fresh = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    if _record_state(fresh) == "enabled":
        return
    try:
        set_project_state_locked(ctx.actual_key, "enabled")
    except Exception as exc:
        raise _StepFailed(
            _short_error(exc),
            hint="Resolve the lifecycle error, then re-run the same command.",
        ) from exc
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    if _record_state(post) != "enabled":
        raise _StepFailed(f"project {ctx.actual_key} is still not enabled")


def _effect_identity(ctx: _RunContext) -> None:
    from sase import project_aliases

    if not ctx.actual_key:
        raise _StepFailed("no project record is available for identity")
    fresh = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    record = fresh.get("record")
    record_map = record if isinstance(record, Mapping) else {}
    current_name = str(record_map.get("name") or "")
    current_aliases = list(record_map.get("aliases") or [])
    wanted_name = str(ctx.requested.get("name") or "")
    wanted_aliases = [str(item) for item in list(ctx.requested.get("aliases") or [])]
    try:
        if wanted_name and wanted_name != current_name:
            project_aliases.ensure_project_name_locked(ctx.actual_key, wanted_name)
        if wanted_aliases and wanted_aliases != current_aliases:
            project_aliases.set_project_aliases_locked(ctx.actual_key, wanted_aliases)
    except Exception as exc:
        raise _StepFailed(
            _short_error(exc),
            hint="Fix the name or alias collision, then re-run the same command.",
        ) from exc
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    post_record = post.get("record")
    post_map = post_record if isinstance(post_record, Mapping) else {}
    if wanted_name and str(post_map.get("name") or "") != wanted_name:
        raise _StepFailed(f"project name is not {wanted_name!r} after update")
    if wanted_aliases and list(post_map.get("aliases") or []) != wanted_aliases:
        raise _StepFailed("project aliases do not match the request after update")
    if isinstance(post_record, Mapping):
        _adopt_record(ctx, post_record)


def _effect_manage(ctx: _RunContext) -> None:
    fresh = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    remote = fresh.get("remote")
    remote_map = dict(remote) if isinstance(remote, Mapping) else {}
    target = {
        "identity_key": ctx.identity_key,
        "display": ctx.display,
        "ref": ctx.ref,
        "workflow_type": ctx.workflow_type,
        "checkout_dir": ctx.actual_checkout,
    }
    try:
        manage_repository(target, remote_map, intent_fingerprint=ctx.fingerprint)
    except ManagementError as exc:
        raise _StepFailed(
            str(exc),
            hint="Resolve the setup failure, then re-run the same command.",
        ) from exc


def _effect_current(ctx: _RunContext) -> None:
    from sase.current_project import set_current_project

    if not ctx.actual_key:
        raise _StepFailed("no project record is available to make current")
    outcome = set_current_project(ctx.actual_key)
    if outcome.status in {"set", "unchanged"}:
        return
    raise _StepFailed(
        outcome.message or f"could not make {ctx.actual_key} current",
        hint="Enable the project, then re-run the same command.",
    )


_EFFECTS = {
    "checkout": _effect_checkout,
    "reenable": _effect_reenable,
    "identity": _effect_identity,
    "manage": _effect_manage,
    "current": _effect_current,
}


def _adopt_record(ctx: _RunContext, record: Mapping[str, Any]) -> None:
    key = str(record.get("key") or "")
    if key:
        ctx.actual_key = key
    name = str(record.get("name") or "")
    if name:
        ctx.actual_name = name


def _adopt_resolved(ctx: _RunContext, resolved: Any) -> None:
    name = str(getattr(resolved, "project_name", "") or "")
    if name:
        ctx.actual_key = name
        ctx.actual_name = name
    checkout = str(getattr(resolved, "checkout_target", "") or "") or str(
        getattr(resolved, "primary_workspace_dir", "") or ""
    )
    if checkout:
        ctx.actual_checkout = checkout


def _effect_target(ctx: _RunContext) -> dict[str, Any]:
    return {
        "workflow_type": ctx.workflow_type,
        "ref": ctx.ref,
        "identity_key": ctx.identity_key,
        "display": ctx.display,
        "checkout_dir": ctx.actual_checkout,
    }


def _record_state(facts: Mapping[str, Any]) -> str:
    record = facts.get("record")
    if not isinstance(record, Mapping):
        return ""
    return str(record.get("state") or "")


def _origin_identity(origin: str, workflow_type: str) -> str:
    if not origin:
        return ""
    if workflow_type:
        try:
            parsed = workspace_provider.parse_repo_ref(workflow_type, origin)
        except Exception:
            parsed = None
        if parsed is not None and parsed.identity_key:
            return parsed.identity_key.casefold()
    return identity_for_origin(origin).casefold()


def _remove_if_still_empty(checkout_dir: str) -> bool:
    try:
        path = Path(checkout_dir).expanduser()
    except Exception:
        return False
    try:
        if not path.is_dir():
            return False
        next(path.iterdir())
    except StopIteration:
        pass
    except OSError:
        return False
    else:
        return False
    try:
        path.rmdir()
    except OSError:
        return False
    return True


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


def _short_error(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()
    text = message[0].strip() if message else ""
    return text or type(exc).__name__


def _apply_identity_lock_path(identity_key: str) -> Path:
    """Return the cooperating apply lock path for *identity_key*.

    This is intentionally separate from the journal lock file: apply
    holds this lock across the whole plan-and-effects critical section
    while the journal helpers lock the journal file for each atomic
    update. Sharing one file would self-deadlock on ``flock``.
    """

    digest = hashlib.sha1(identity_key.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f".apply-{digest}.lock"


def _checkout_lock_path(checkout_dir: str) -> Path:
    normalized = str(Path(checkout_dir).expanduser())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f".checkout-{digest}.lock"


@contextmanager
def _hold_apply_locks(
    identity_key: str, checkout_dir: str, *, timeout: float
) -> Iterator[None]:
    """Hold the identity and checkout locks in deterministic order."""

    wanted = {str(_apply_identity_lock_path(identity_key))}
    if checkout_dir.strip():
        wanted.add(str(_checkout_lock_path(checkout_dir)))
    handles: list[Any] = []
    try:
        deadline = time.monotonic() + max(0.0, timeout)
        for path_text in sorted(wanted):
            path = Path(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "ab")
            handles.append(handle)
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    if time.monotonic() >= deadline:
                        raise _LockTimeout(path_text) from None
                    time.sleep(_LOCK_POLL_SECONDS)
                else:
                    break
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                handle.close()


__all__ = ["apply_plan"]
