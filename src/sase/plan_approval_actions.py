"""Shared plan approval response protocol and side effects."""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_approval_choices import (
    PLAN_APPROVAL_CLI_KINDS,
    approval_choice_archives_plan,
    require_plan_approval_choice,
)
from sase.sdd.plan_validate import (
    PlanFrontmatterFieldSpec,
    PlanValidationResult,
    plan_frontmatter_schema,
    validate_plan,
    validate_plan_file,
)

PLAN_APPROVAL_KINDS = PLAN_APPROVAL_CLI_KINDS
PLAN_APPROVAL_ACTIONS = frozenset({"PlanApproval", "EpicApproval"})
EpicLaunchMode = Literal["detached", "foreground", "skip"]


@dataclass(frozen=True)
class PlanApprovalActionContext:
    id: str
    host_files: tuple[str, ...]
    host_action_data: dict[str, str]


@dataclass(frozen=True)
class PlanApprovalActionResult:
    notification_id: str
    response_file: str
    response_path: Path
    response_json: dict[str, Any]
    message: str


class PlanApprovalActionError(RuntimeError):
    """Deterministic host-side plan action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


class PlanApprovalValidationError(PlanApprovalActionError):
    """An approval target tier rejected the pending plan."""

    def __init__(
        self,
        *,
        plan_path: Path,
        tier: str,
        validation: PlanValidationResult,
        schema: tuple[PlanFrontmatterFieldSpec, ...],
    ) -> None:
        self.plan_path = plan_path
        self.tier = tier
        self.validation = validation
        self.schema = schema
        details = "; ".join(
            _approval_diagnostic_text(plan_path, diagnostic)
            for diagnostic in validation.diagnostics
            if diagnostic.is_error
        )
        command = f"sase plan validate {shlex.quote(str(plan_path))} --tier {tier}"
        message = f"plan failed {tier} validation"
        if details:
            message += f": {details}"
        message += f". Fix the plan and retry; run `{command}` for the full schema."
        super().__init__("plan_validation_failed", str(plan_path), message)


def execute_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str | None,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    epic_launch_mode: EpicLaunchMode = "detached",
) -> PlanApprovalActionResult:
    """Resolve a neutral plan gate, with legacy in-flight fallback."""
    request_kind = notification.host_action_data.get("request_kind")
    action = "EpicApproval" if request_kind == "epic_plan" else "PlanApproval"
    from sase.notification_gates.paths import resolve_action_bundle

    bundle = resolve_action_bundle(action, notification.host_action_data)
    if bundle is not None and not bundle.legacy:
        return _execute_neutral_plan_approval_response(
            notification,
            bundle.root,
            choice,
            feedback=feedback,
            commit_plan=commit_plan,
            run_coder=run_coder,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            epic_launch_mode=epic_launch_mode,
        )
    return _execute_legacy_plan_approval_response(
        notification,
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        epic_launch_mode=epic_launch_mode,
    )


def _execute_legacy_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str | None,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    epic_launch_mode: EpicLaunchMode,
) -> PlanApprovalActionResult:
    """Write the runner response for an in-flight legacy PlanApproval."""
    raw_response_dir = notification.host_action_data.get("response_dir")
    if not raw_response_dir:
        raise PlanApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )

    response_dir = Path(raw_response_dir).expanduser()
    if not response_dir.is_dir():
        raise PlanApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    if not (response_dir / "plan_request.json").is_file():
        raise PlanApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "plan request was already consumed",
        )
    if not notification.host_files:
        raise PlanApprovalActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )

    choice = _resolve_plan_approval_choice(notification.host_files[0], choice)

    response_json, message = plan_response_json(
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
    )
    response_path = response_dir / "plan_response.json"
    host_owns_epic_launch = False
    epic_launch_cwd: Path | None = None
    if choice == "epic":
        if epic_launch_mode == "skip":
            host_owns_epic_launch = True
        else:
            epic_launch_cwd = _epic_launch_cwd(notification)
            host_owns_epic_launch = epic_launch_cwd is not None
        if host_owns_epic_launch:
            response_json["epic_launch_owner"] = "host"
    _write_json_once(response_path, response_json, notification.id)

    run_plan_side_effects(notification, choice, response_path, response_json)
    if (
        host_owns_epic_launch
        and epic_launch_mode != "skip"
        and not prepare_epic_launch(
            notification,
            Path(notification.host_files[0]),
            mode=epic_launch_mode,
            response_dir=response_dir,
            resolved_cwd=epic_launch_cwd,
        )
    ):
        raise PlanApprovalActionError(
            "epic_launch_failed",
            notification.host_files[0],
            "host claimed the epic launch but could not start it",
        )
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file="plan_response.json",
        response_path=response_path,
        response_json=response_json,
        message=message,
    )


def _execute_neutral_plan_approval_response(
    notification: PlanApprovalActionContext,
    bundle_path: Path,
    choice: str | None,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    epic_launch_mode: EpicLaunchMode,
) -> PlanApprovalActionResult:
    """Execute one tier-approved choice through the shared gate executor."""
    if not notification.host_files:
        raise PlanApprovalActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )
    resolved_choice = _resolve_plan_approval_choice(notification.host_files[0], choice)
    choice_id = (
        "feedback"
        if resolved_choice == "reject" and feedback is not None
        else resolved_choice
    )
    input_data: dict[str, Any] = {}
    if feedback is not None:
        input_data["feedback"] = feedback
    if commit_plan is not None:
        input_data["commit_plan"] = commit_plan
    if run_coder is not None:
        input_data["run_coder"] = run_coder
    if coder_prompt is not None:
        input_data["coder_prompt"] = coder_prompt
    if coder_model is not None:
        input_data["coder_model"] = coder_model
    if choice_id == "epic":
        input_data["epic_launch_mode"] = epic_launch_mode

    from sase.notification_gates.executor import execute_gate_choice
    from sase.notification_gates.models import GateError
    from sase.notification_gates.paths import RESPONSE_FILENAME

    try:
        execution = execute_gate_choice(
            bundle_path,
            choice_id,
            input_data,
            source="plan_response",
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise PlanApprovalActionError(code, exc.target, str(exc)) from exc
    if execution.already_completed:
        raise PlanApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "response already exists",
        )
    result = execution.response.get("result")
    if not isinstance(result, dict):
        raise PlanApprovalActionError(
            "invalid_response",
            str(bundle_path / RESPONSE_FILENAME),
            "plan command returned no result object",
        )
    try:
        message = require_plan_approval_choice(choice_id).response_message
    except KeyError as exc:  # pragma: no cover - executor rejects first
        raise PlanApprovalActionError(
            "unsupported_action", choice_id, "unsupported plan action choice"
        ) from exc
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file=RESPONSE_FILENAME,
        response_path=bundle_path / RESPONSE_FILENAME,
        response_json=execution.response,
        message=message,
    )


def prepare_epic_launch(
    notification: PlanApprovalActionContext,
    plan_file: str | Path,
    *,
    mode: EpicLaunchMode,
    response_dir: Path,
    resolved_cwd: Path | None = None,
) -> bool:
    """Start the host-owned epic launch and report whether the host claimed it."""
    if mode not in {"detached", "foreground", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return True
    cwd = resolved_cwd or _epic_launch_cwd(notification)
    if cwd is None:
        return False

    plan_path = str(plan_file)
    if mode == "detached":
        try:
            from sase.bead.epic_launch import spawn_detached_epic_launch

            artifacts_dir = resolve_plan_agent_artifacts_dir(
                notification.host_action_data
            )
            log_root = Path(artifacts_dir) if artifacts_dir else response_dir
            spawn_detached_epic_launch(
                plan_path,
                cwd=cwd,
                log_path=log_root / "epic_launch.log",
                artifacts_dir=artifacts_dir,
                cl_name=notification.host_action_data.get("agent_cl_name"),
            )
            return True
        except Exception:
            return False

    try:
        from sase.bead.epic_launch import run_epic_launch_foreground

        completed = run_epic_launch_foreground(plan_path, cwd=cwd)
    except OSError as exc:
        raise PlanApprovalActionError(
            "epic_launch_failed", plan_path, f"could not start epic launch: {exc}"
        ) from exc
    if completed.returncode != 0:
        from sase.bead.epic_launch import build_epic_launch_argv

        resume = shlex.join(build_epic_launch_argv(plan_path))
        raise PlanApprovalActionError(
            "epic_launch_failed",
            plan_path,
            f"epic launch failed with exit code {completed.returncode}; resume with `{resume}`",
        )
    return True


def can_claim_epic_launch(
    notification: PlanApprovalActionContext,
    *,
    mode: EpicLaunchMode,
) -> bool:
    """Return whether the host can durably claim an epic launch."""
    if mode not in {"detached", "foreground", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    return mode == "skip" or _epic_launch_cwd(notification) is not None


def _epic_launch_cwd(notification: PlanApprovalActionContext) -> Path | None:
    project_dir = notification.host_action_data.get("project_dir")
    if not project_dir:
        return None
    try:
        from sase.bead.epic_launch import resolve_epic_launch_cwd

        return resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=notification.host_action_data.get("agent_project_file"),
        )
    except Exception:
        return None


def _resolve_plan_approval_choice(plan_file: str, choice: str | None) -> str:
    """Resolve an implicit approval choice and enforce target-tier validation.

    An omitted choice follows the tier authored in the pending plan. Explicit
    ``tale`` and ``epic`` choices are cross-tier overrides and therefore
    validate against their target schema before any approval side effect.
    Choices that do not assign an SDD tier keep their existing behavior.
    """
    plan_path = Path(plan_file).expanduser()
    if choice is None:
        from sase.sdd.plan_tiers import read_plan_tier

        choice = read_plan_tier(plan_path)
        if choice is None:
            raise PlanApprovalActionError(
                "invalid_request",
                "tier",
                "approval kind was omitted, but the plan has no valid authored "
                "tier; add `tier: tale` or `tier: epic`, or pass `--kind`",
            )

    try:
        require_plan_approval_choice(choice)
    except KeyError as exc:
        raise PlanApprovalActionError(
            "unsupported_action", choice, "unsupported plan action choice"
        ) from exc

    if choice in {"tale", "epic"}:
        require_plan_approval_validation(plan_path, choice)
    return choice


def require_plan_approval_validation(
    plan_file: str | Path,
    tier: str,
) -> PlanValidationResult:
    """Validate an approval target before notifications or files are mutated."""
    plan_path = Path(plan_file).expanduser()
    validation = _validate_plan_for_approval(plan_path, tier)
    if validation.ok:
        return validation
    raise PlanApprovalValidationError(
        plan_path=plan_path,
        tier=tier,
        validation=validation,
        schema=plan_frontmatter_schema(tier),
    )


def _validate_plan_for_approval(
    plan_path: Path,
    tier: str,
) -> PlanValidationResult:
    """Validate as the target tier that approval will persist.

    A cross-tier approval override replaces only the authored ``tier`` scalar
    in the validation copy. This lets an epic-authored plan be intentionally
    downgraded (its epic fields become tale warnings), while upgrading a tale
    still fails on missing epic structure. The source file is never changed by
    the gate.
    """
    from sase.sdd.plan_tiers import read_plan_tier

    authored_tier = read_plan_tier(plan_path)
    if authored_tier is None or authored_tier == tier:
        return validate_plan_file(plan_path, tier)

    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return validate_plan_file(plan_path, tier)
    target_content, replacements = re.subn(
        r"(?m)^tier[ \t]*:.*$",
        f"tier: {tier}",
        content,
        count=1,
    )
    if replacements != 1:
        return validate_plan_file(plan_path, tier)
    return validate_plan(target_content, tier)


def _approval_diagnostic_text(plan_path: Path, diagnostic: Any) -> str:
    location = f"{plan_path}:{diagnostic.line}" if diagnostic.line else str(plan_path)
    return f"{location} [{diagnostic.code}] {diagnostic.message}"


def plan_response_json(
    choice: str,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
) -> tuple[dict[str, Any], str]:
    """Map a product-level plan choice to the existing runner protocol."""
    try:
        record = require_plan_approval_choice(choice)
    except KeyError as exc:
        raise PlanApprovalActionError(
            "unsupported_action", choice, "unsupported plan action choice"
        ) from exc

    if record.protocol is not None:
        protocol = record.protocol
        response: dict[str, Any] = {
            "action": protocol.action,
            "commit_plan": protocol.commit_plan,
            "run_coder": protocol.run_coder,
        }
        if record.allow_protocol_overrides:
            if commit_plan is not None:
                response["commit_plan"] = commit_plan
            if run_coder is not None:
                response["run_coder"] = run_coder
        if record.allow_coder_options:
            _add_optional_coder_fields(
                response, coder_prompt=coder_prompt, coder_model=coder_model
            )
        return response, record.response_message

    if choice == "reject":
        response = {"action": "reject"}
        if feedback is not None:
            response["feedback"] = feedback
        return response, record.response_message

    if choice == "feedback":
        if not feedback:
            raise PlanApprovalActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return {"action": "reject", "feedback": feedback}, record.response_message

    raise PlanApprovalActionError(
        "unsupported_action", choice, "unsupported plan action choice"
    )


def _write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str,
) -> None:
    """Write a JSON response without overwriting an existing approval."""
    try:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise PlanApprovalActionError(
            "conflict_already_handled", notification_id, "response already exists"
        ) from exc


def dismiss_notification_best_effort(notification_id: str) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        pass


def _mark_action_handled_best_effort(
    notification_id: str,
    *,
    source: str,
    action: str | None = None,
) -> None:
    """Record that a notification action was resolved in the shared store.

    Best-effort so transports (e.g. Telegram) can later dismiss any inline
    keyboard they sent. Never raises — a failure must not block the runner
    response that the agent is waiting on.
    """
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(notification_id, source=source, action=action)
    except Exception:
        pass


def run_plan_side_effects(
    notification: PlanApprovalActionContext,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
    *,
    response_container: dict[str, Any] | None = None,
    source: str = "plan_response",
) -> None:
    dismiss_notification_best_effort(notification.id)
    _mark_action_handled_best_effort(notification.id, source=source, action=choice)

    persisted_action = _persist_plan_approved_metadata(notification, response_json)
    if persisted_action is None:
        return

    if approval_choice_archives_plan(choice):
        saved_path = _archive_plan_for_approval(notification, persisted_action)
        if saved_path:
            try:
                response_json["saved_plan_path"] = saved_path
                if response_container is not None:
                    response_container["result"] = response_json
                if response_container is not None:
                    from sase.notification_gates.durability import atomic_write_json

                    atomic_write_json(response_path, response_container)
                else:
                    response_path.write_text(
                        json.dumps(response_json, indent=2) + "\n",
                        encoding="utf-8",
                    )
            except OSError:
                pass


def _add_optional_coder_fields(
    response: dict[str, Any],
    *,
    coder_prompt: str | None,
    coder_model: str | None,
) -> None:
    if coder_prompt is not None:
        response["coder_prompt"] = coder_prompt
    if coder_model is not None:
        response["coder_model"] = coder_model


def _persist_plan_approved_metadata(
    notification: PlanApprovalActionContext,
    response_json: dict[str, Any],
) -> str | None:
    action = persisted_plan_action(response_json)
    if action is None:
        return None

    artifacts_dir = resolve_plan_agent_artifacts_dir(notification.host_action_data)
    if artifacts_dir:
        meta_path = Path(artifacts_dir) / "agent_meta.json"
    else:
        raw_response_dir = notification.host_action_data.get("response_dir")
        if not raw_response_dir:
            return action
        meta_path = Path(raw_response_dir).expanduser().parent / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}

    meta["plan_approved"] = True
    meta["plan_action"] = action
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        update_agent_artifact_index_for_marker_mutation(meta_path.parent)
    except OSError:
        pass
    return action


def persisted_plan_action(response_json: dict[str, Any]) -> str | None:
    """Return the canonical persisted action for a plan response."""
    return _persisted_plan_action(response_json)


def _persisted_plan_action(response_json: dict[str, Any]) -> str | None:
    action = response_json.get("action")
    if action == "epic":
        return str(action)
    if action != "approve":
        return None

    if response_json.get("run_coder", True) is False:
        return "commit"
    if response_json.get("commit_plan") is True:
        return "tale"
    return "approve"


def resolve_plan_agent_artifacts_dir(action_data: Mapping[str, str]) -> str | None:
    """Resolve the agent artifact dir carried by a plan-approval notification."""
    explicit = _nonempty(action_data.get("artifacts_dir"))
    if explicit:
        resolved = _existing_agent_artifacts_dir(explicit)
        if resolved is not None:
            return resolved

    timestamp = _normalize_agent_timestamp(action_data.get("agent_timestamp"))
    if timestamp is None:
        return None

    project_name = _plan_action_project_name(action_data)
    if project_name is None:
        return None

    workflow_dir = (
        _nonempty(action_data.get("agent_workflow_dir"))
        or _nonempty(action_data.get("workflow_dir"))
        or "ace-run"
    )
    resolved = _resolve_project_timestamp_artifacts_dir(
        project_name, workflow_dir, timestamp
    )
    if resolved is not None:
        return resolved
    if workflow_dir != "ace-run":
        return None
    return _find_project_timestamp_artifacts_dir(project_name, timestamp)


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _existing_agent_artifacts_dir(path: str) -> str | None:
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_path

        candidate = resolve_agent_artifact_path(path)
    except Exception:
        candidate = Path(path).expanduser()
    return str(candidate) if candidate.is_dir() else None


def _normalize_agent_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        from sase.ace.tui.models._timestamps import normalize_to_14_digit

        return normalize_to_14_digit(value.strip())
    except Exception:
        return value.strip() or None


def _plan_action_project_name(action_data: Mapping[str, str]) -> str | None:
    if project_file := _nonempty(action_data.get("agent_project_file")):
        return _canonical_plan_project_name(Path(project_file).expanduser().parent.name)

    if project_dir := _nonempty(action_data.get("project_dir")):
        try:
            from sase.workspace_provider import get_workspace_name

            workspace_name = get_workspace_name(str(Path(project_dir).expanduser()))
        except Exception:
            workspace_name = None
        if workspace_name:
            project_name = _canonical_plan_project_name(workspace_name)
            if project_name is not None:
                return project_name
        basename = re.sub(r"_\d+$", "", Path(project_dir).expanduser().name)
        return _canonical_plan_project_name(basename)

    return None


def _canonical_plan_project_name(value: str) -> str | None:
    try:
        from sase.project_aliases import resolve_project_alias_ref

        value = resolve_project_alias_ref(value)
    except Exception:
        pass
    try:
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(value):
            return None
    except Exception:
        return None
    return value


def _resolve_project_timestamp_artifacts_dir(
    project_name: str,
    workflow_dir: str,
    timestamp: str,
) -> str | None:
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

        candidate = resolve_agent_artifact_timestamp_path(
            project_name,
            workflow_dir,
            timestamp,
        )
    except Exception:
        from sase.core.paths import sase_projects_dir

        candidate = (
            sase_projects_dir() / project_name / "artifacts" / workflow_dir / timestamp
        )
    return str(candidate) if candidate.is_dir() else None


def _find_project_timestamp_artifacts_dir(
    project_name: str,
    timestamp: str,
) -> str | None:
    from sase.core.paths import sase_projects_dir

    artifacts_root = sase_projects_dir() / project_name / "artifacts"
    if not artifacts_root.is_dir():
        return None
    try:
        workflow_dirs = [path for path in artifacts_root.iterdir() if path.is_dir()]
    except OSError:
        return None
    for workflow_dir in sorted(workflow_dirs, key=lambda path: path.name):
        resolved = _resolve_project_timestamp_artifacts_dir(
            project_name,
            workflow_dir.name,
            timestamp,
        )
        if resolved is not None:
            return resolved
    return None


def _archive_plan_for_approval(
    notification: PlanApprovalActionContext,
    persisted_action: str,
) -> str | None:
    if not notification.host_files:
        return None
    try:
        from sase.running_field import get_workspace_directory
        from sase.sdd.files import (
            commit_sdd_store_files,
            ensure_bare_git_sdd_initialized,
        )
        from sase.sdd.plan_archive import archive_plan_file
        from sase.sdd.store import materialize_sdd_store

        project_dir = notification.host_action_data.get("project_dir")
        if not project_dir:
            return None
        artifacts_dir = resolve_plan_agent_artifacts_dir(notification.host_action_data)
        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_store = materialize_sdd_store(workspace_dir, 1)
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(
                workspace_dir,
                commit=True,
                push=False,
            )
        tier: Literal["tale", "epic"] = "epic" if persisted_action == "epic" else "tale"
        src_plan = Path(notification.host_files[0])
        archived = archive_plan_file(
            src_plan,
            sdd_store,
            tier=tier,
            preserve_existing=False,
        )
        if not sdd_store.is_in_tree:
            commit_sdd_store_files(
                sdd_store,
                f"Archive approved plan {src_plan.stem}",
                paths=[archived.path],
                artifacts_dir=artifacts_dir,
            )
        return str(archived.path)
    except Exception:
        return None
