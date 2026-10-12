"""State and side effects for the ordered onboarding steps."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase import workspace_provider
from sase.project_onboarding.discovery import (
    identity_for_origin,
    read_git_origin_url,
    resolve_git_dir,
)
from sase.project_onboarding.facts import gather_facts
from sase.project_onboarding.manage import ManagementError, manage_repository
from sase.project_onboarding.refs import UserRefError, parse_user_ref


class StepFailed(RuntimeError):
    """One ordered step effect could not reach its postcondition."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class RunContext:
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


def _effect_checkout(ctx: RunContext) -> None:
    try:
        parsed = parse_user_ref(ctx.ref, workflow_type=ctx.workflow_type or None)
    except UserRefError as exc:
        raise StepFailed(str(exc)) from exc
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
                raise StepFailed(
                    _short_error(retry_exc),
                    hint="Re-run the same command to retry the clone.",
                ) from retry_exc
        else:
            raise StepFailed(
                _short_error(exc),
                hint="Re-run the same command to retry the clone.",
            ) from exc
    _adopt_resolved(ctx, resolved)
    origin = read_git_origin_url(ctx.actual_checkout)
    if resolve_git_dir(ctx.actual_checkout) is None:
        raise StepFailed(
            f"{ctx.actual_checkout} is not a Git checkout after resolving",
            hint="Remove the unexpected path, then re-run the same command.",
        )
    if _origin_identity(origin, ctx.workflow_type) != ctx.identity_key.casefold():
        raise StepFailed(
            "the resolved checkout does not match the reviewed repository",
            hint="Remove the unexpected checkout, then re-run the same command.",
        )
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    post_record = post.get("record")
    if isinstance(post_record, Mapping):
        _adopt_record(ctx, post_record)


def _effect_reenable(ctx: RunContext) -> None:
    from sase.main.project_handler_lifecycle import set_project_state_locked

    if not ctx.actual_key:
        raise StepFailed("no project record is available to re-enable")
    fresh = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    if _record_state(fresh) == "enabled":
        return
    try:
        set_project_state_locked(ctx.actual_key, "enabled")
    except Exception as exc:
        raise StepFailed(
            _short_error(exc),
            hint="Resolve the lifecycle error, then re-run the same command.",
        ) from exc
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    if _record_state(post) != "enabled":
        raise StepFailed(f"project {ctx.actual_key} is still not enabled")


def _effect_identity(ctx: RunContext) -> None:
    from sase import project_aliases

    if not ctx.actual_key:
        raise StepFailed("no project record is available for identity")
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
        raise StepFailed(
            _short_error(exc),
            hint="Fix the name or alias collision, then re-run the same command.",
        ) from exc
    post = gather_facts(_effect_target(ctx), ctx.mode, actor=ctx.actor)
    post_record = post.get("record")
    post_map = post_record if isinstance(post_record, Mapping) else {}
    if wanted_name and str(post_map.get("name") or "") != wanted_name:
        raise StepFailed(f"project name is not {wanted_name!r} after update")
    if wanted_aliases and list(post_map.get("aliases") or []) != wanted_aliases:
        raise StepFailed("project aliases do not match the request after update")
    if isinstance(post_record, Mapping):
        _adopt_record(ctx, post_record)


def _effect_manage(ctx: RunContext) -> None:
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
        raise StepFailed(
            str(exc),
            hint="Resolve the setup failure, then re-run the same command.",
        ) from exc


def _effect_current(ctx: RunContext) -> None:
    from sase.current_project import set_current_project

    if not ctx.actual_key:
        raise StepFailed("no project record is available to make current")
    outcome = set_current_project(ctx.actual_key)
    if outcome.status in {"set", "unchanged"}:
        return
    raise StepFailed(
        outcome.message or f"could not make {ctx.actual_key} current",
        hint="Enable the project, then re-run the same command.",
    )


EFFECTS = {
    "checkout": _effect_checkout,
    "reenable": _effect_reenable,
    "identity": _effect_identity,
    "manage": _effect_manage,
    "current": _effect_current,
}


def _adopt_record(ctx: RunContext, record: Mapping[str, Any]) -> None:
    key = str(record.get("key") or "")
    if key:
        ctx.actual_key = key
    name = str(record.get("name") or "")
    if name:
        ctx.actual_name = name


def _adopt_resolved(ctx: RunContext, resolved: Any) -> None:
    name = str(getattr(resolved, "project_name", "") or "")
    if name:
        ctx.actual_key = name
        ctx.actual_name = name
    checkout = str(getattr(resolved, "checkout_target", "") or "") or str(
        getattr(resolved, "primary_workspace_dir", "") or ""
    )
    if checkout:
        ctx.actual_checkout = checkout


def _effect_target(ctx: RunContext) -> dict[str, Any]:
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


def _short_error(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()
    text = message[0].strip() if message else ""
    return text or type(exc).__name__


__all__ = ["EFFECTS", "RunContext", "StepFailed"]
