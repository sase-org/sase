"""Plan approval types, validation, and response protocol mapping."""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.plan_approval_choices import (
    PLAN_APPROVAL_CLI_KINDS,
    plan_approval_protocol_for_selection,
    plan_approval_response_message_for_selection,
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
EpicLaunchMode = Literal["detached", "skip"]


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
    epic_launch_task_id: str | None = None


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
        command = f"sase plan validate {shlex.quote(str(plan_path))} --explain"
        message = f"plan failed {tier} validation"
        if details:
            message += f": {details}"
        message += f". Fix the plan and retry; run `{command}` for the full schema."
        super().__init__("plan_validation_failed", str(plan_path), message)


def resolve_plan_approval_choice(plan_file: str, choice: str | None) -> str:
    """Resolve an implicit approval choice and validate its target tier."""
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
        return validate_plan_file(plan_path, tier, mode="launch")

    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return validate_plan_file(plan_path, tier, mode="launch")
    target_content, replacements = re.subn(
        r"(?m)^tier[ \t]*:.*$",
        f"tier: {tier}",
        content,
        count=1,
    )
    if replacements != 1:
        return validate_plan_file(plan_path, tier, mode="launch")
    return validate_plan(target_content, tier, mode="launch")


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


def plan_response_json_for_selection(
    selected_option_ids: Sequence[str],
    *,
    tier: Literal["tale", "epic"],
    feedback: str | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    epic_launch_owner: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Derive the runner protocol solely from a v2 selected option set."""
    selected = tuple(selected_option_ids)
    if selected == ("reject",):
        response: dict[str, Any] = {"action": "reject"}
        if feedback:
            response["feedback"] = feedback
        return response, plan_approval_response_message_for_selection(
            selected, tier=tier
        )
    if selected == ("feedback",):
        if not feedback:
            raise PlanApprovalActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return {
            "action": "reject",
            "feedback": feedback,
        }, plan_approval_response_message_for_selection(selected, tier=tier)
    try:
        protocol = plan_approval_protocol_for_selection(selected, tier=tier)
    except ValueError as exc:
        raise PlanApprovalActionError(
            "unsupported_action",
            ",".join(selected),
            f"unsupported {tier} plan option selection",
        ) from exc
    message = plan_approval_response_message_for_selection(selected, tier=tier)
    response = {
        "action": protocol.action,
        "commit_plan": protocol.commit_plan,
        "run_coder": protocol.run_coder,
    }
    if protocol.run_coder:
        _add_optional_coder_fields(
            response,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
        )
    if protocol.action == "epic" and epic_launch_owner == "host":
        response["epic_launch_owner"] = "host"
    return response, message


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


def persisted_plan_action(response_json: dict[str, Any]) -> str | None:
    """Return the canonical persisted action for a plan response."""
    action = response_json.get("action")
    if action == "epic":
        return str(action)
    if action != "approve":
        return None

    if (
        response_json.get("run_coder", True) is False
        and response_json.get("commit_plan") is True
    ):
        return "commit"
    if response_json.get("commit_plan") is True:
        return "tale"
    return "approve"
