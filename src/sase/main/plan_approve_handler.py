"""Utility functions for plan approval and notification support.

Provides helpers for auto-approve checking, desktop notifications,
and tmux bell ringing. Used by the agent runner and other plan/question
orchestration code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, NoReturn, cast

from sase.env_contracts import provider_project_dir_from_env
from sase.main.plan_direct_approval import DirectApprovalKind
from sase.main.plan_pending import (
    PendingPlan,
    PendingPlanAmbiguity,
    PendingPlanMatch,
    PendingPlanMiss,
    ensure_plan_notification_available,
    pending_plans,
    plan_context_from_notification,
    resolve_pending_plan_selector,
)
from sase.main.plan_pending_diagnosis import miss_error_code
from sase.main.plan_pending_render import (
    render_ambiguity,
    render_miss,
)
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
    PlanApprovalValidationError,
    execute_plan_approval_response,
)
from sase.plan_approval_choices import PLAN_APPROVAL_AUTO_MODE_CHOICES

PlanAutoApprovalAction = Literal["approve", "epic", "tale"]


def _normalize_plan_action(value: object) -> PlanAutoApprovalAction | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in PLAN_APPROVAL_AUTO_MODE_CHOICES:
        return cast(PlanAutoApprovalAction, normalized)
    return None


def _read_agent_meta() -> dict[str, object]:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return {}
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_auto_plan_approval_action() -> PlanAutoApprovalAction | None:
    """Return the plan-specific auto-approval action, if one is active."""
    raw_argument, has_raw_argument = _raw_auto_plan_argument()
    if has_raw_argument:
        if raw_argument == "epic":
            return "epic"
        if raw_argument == "tale":
            return "tale"
        # ``approve`` is an enabled-state compatibility sentinel. The plan
        # adapter receives and validates the opaque argument separately.
        return "approve"
    for env_name in (
        "SASE_AGENT_AUTO_APPROVE_PLAN_ACTION",
        "SASE_AGENT_AUTO_PLAN_ACTION",
    ):
        action = _normalize_plan_action(os.environ.get(env_name))
        if action is not None:
            return action

    meta = _read_agent_meta()
    action = _normalize_plan_action(meta.get("auto_approve_plan_action"))
    if action is not None:
        return action

    if os.environ.get("SASE_AGENT_AUTO_APPROVE") or meta.get("approve"):
        return "approve"

    return None


def get_auto_plan_approval_argument() -> str | None:
    """Return the optional raw argument retained from ``%auto``."""
    argument, present = _raw_auto_plan_argument()
    return argument if present else None


def _raw_auto_plan_argument() -> tuple[str | None, bool]:
    for env_name in (
        "SASE_AGENT_AUTO_APPROVE_ARGUMENT",
        "SASE_AGENT_AUTO_PLAN_ARGUMENT",
    ):
        if env_name in os.environ:
            value = os.environ.get(env_name, "").strip()
            return value or None, True
    meta = _read_agent_meta()
    if "auto_approve_argument" in meta:
        raw_value = meta.get("auto_approve_argument")
        if isinstance(raw_value, str):
            return raw_value.strip() or None, True
    return None, False


def handle_plan_approve_command(args: argparse.Namespace) -> NoReturn:
    """Approve a live proposal or a plan file through one CLI command."""
    from rich.console import Console

    try:
        result = _approve_plan_from_cli(
            selector=getattr(args, "selector", None),
            kind=getattr(args, "kind", None),
            coder_prompt=getattr(args, "prompt", None),
            coder_model=getattr(args, "model", None),
            wait=getattr(args, "wait", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            project=getattr(args, "project", None),
            decide=tuple(getattr(args, "decide", None) or ()),
        )
    except PlanApprovalValidationError as exc:
        from sase.main.plan_validate_render import render_validation_human

        render_validation_human(
            exc.validation,
            tier=exc.tier,
            path=str(exc.plan_path),
            schema=exc.schema,
            console=Console(stderr=True),
        )
        sys.exit(1)
    except PlanApprovalActionError as exc:
        from sase.main.plan_decide import DecideError

        if isinstance(exc, DecideError):
            from sase.main.plan_approve_render import render_decide_error

            render_decide_error(exc)
            sys.exit(2)
        if not getattr(exc, "_sase_rendered", False):
            from sase.main.plan_approve_render import render_approval_error

            render_approval_error(exc)
        sys.exit(2)
    except Exception as exc:
        from sase.main.plan_direct_approval import DirectApprovalRefused

        if isinstance(exc, DirectApprovalRefused):
            from sase.main.plan_approve_render import render_direct_approval_refusal

            render_direct_approval_refusal(exc.refusal)
            sys.exit(2)
        raise

    if (
        isinstance(result, PlanApprovalActionResult)
        and result.epic_launch_monitor_id is not None
    ):
        monitor_id = result.epic_launch_monitor_id
        Console().print(
            f"[cyan]Monitor {monitor_id}[/cyan] "
            f"[dim]Follow with `sase monitor show {monitor_id} --follow`.[/dim]"
        )
    elif (
        isinstance(result, PlanApprovalActionResult)
        and result.epic_launch_task_id is not None
    ):
        task_id = result.epic_launch_task_id
        Console().print(
            f"[cyan]Proc {task_id}[/cyan] "
            f"[dim]Follow with `sase proc show {task_id} --follow`.[/dim]"
        )
    if getattr(result, "coder_error", None) or getattr(result, "incomplete", False):
        sys.exit(1)
    sys.exit(0)


def _approve_plan_from_cli(
    *,
    selector: str | None,
    kind: str | None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    wait: str | None = None,
    dry_run: bool = False,
    project: str | None = None,
    decide: tuple[str, ...] = (),
) -> PlanApprovalActionResult | object | None:
    """Route a selector to a live gate or a file-backed direct approval."""
    _validate_wait_spec_for_cli(wait)
    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanMatch):
        return _approve_pending_plan(
            outcome.plan,
            selector=selector,
            kind=kind,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            dry_run=dry_run,
            project=project,
            decide=decide,
        )
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise _rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if selector is None or not selector.strip():
        _render_omitted_direct_approval_miss(outcome)
        raise _rendered_error("missing_selector", "selector", outcome.header)

    from sase.main.plan_direct_approval import (
        DirectApprovalRefusal,
        DirectApprovalRefused,
        DirectApprovalRequest,
        resolve_direct_approval,
    )

    direct = resolve_direct_approval(
        DirectApprovalRequest(
            selector=selector,
            kind=cast(DirectApprovalKind | None, kind),
            kind_explicit=kind is not None,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            project=project,
            cwd=Path.cwd(),
            decide=tuple(decide or ()),
        )
    )
    if direct is None:
        assert isinstance(outcome, PendingPlanMiss)
        render_miss(outcome, pending_plans())
        raise _rendered_error(miss_error_code(outcome), selector, outcome.header)
    if isinstance(direct, DirectApprovalRefusal):
        raise DirectApprovalRefused(direct)
    from sase.main.plan_decide import direct_card_lines, retry_line_for_plan

    if direct.recovery is not None:
        if dry_run:
            from sase.main.plan_approve_render import render_coder_recovery_dry_run

            render_coder_recovery_dry_run(
                direct,
                retry_line=retry_line_for_plan(direct.source_path),
            )
            return None
        from sase.main.plan_approve_render import render_coder_recovery
        from sase.main.plan_direct_approval_run import execute_coder_recovery

        recovery_result = execute_coder_recovery(direct)
        render_coder_recovery(
            recovery_result,
            retry_line=retry_line_for_plan(recovery_result.local_plan_path),
        )
        return recovery_result
    if dry_run:
        from sase.main.plan_approve_render import render_direct_approval_dry_run

        render_direct_approval_dry_run(
            direct, decision_lines=direct_card_lines(direct, dry_run=True)
        )
        return None
    from sase.main.plan_approve_render import render_direct_approval
    from sase.main.plan_direct_approval_run import execute_direct_approval

    result = execute_direct_approval(direct)
    render_direct_approval(
        result, decision_lines=direct_card_lines(direct, dry_run=False)
    )
    return result


def _approve_pending_plan(
    plan: PendingPlan,
    *,
    selector: str | None,
    kind: str | None,
    coder_prompt: str | None,
    coder_model: str | None,
    wait: str | None,
    dry_run: bool,
    project: str | None,
    decide: tuple[str, ...] = (),
) -> PlanApprovalActionResult | None:
    """Run or preview the existing gate response path."""
    if project:
        raise PlanApprovalActionError(
            "invalid_request",
            "project",
            "-P/--project only applies to plans without a live approval gate",
        )
    if plan.tier == "epic" and kind is None:
        from sase.main.plan_direct_approval import (
            DirectApprovalRefusal,
            DirectApprovalRefused,
        )

        displayed = selector or plan.display_name
        raise DirectApprovalRefused(
            DirectApprovalRefusal(
                code="epic_guard",
                header=f"✗ {plan.display_name} is an epic plan",
                detail_lines=(
                    f"Approve it as an epic:        sase plan approve {displayed} -k epic",
                    f"Or run it as a single tale:   sase plan approve {displayed} -k tale",
                ),
            )
        )
    selected_kind = kind or "tale"
    notification = plan.notification
    ensure_plan_notification_available(notification)
    from sase.main.plan_decide import parse_decide_assignments

    raw_map = parse_decide_assignments(list(decide or ()))
    decision_context = _live_decision_context(plan, raw_map)
    if dry_run:
        from sase.main.plan_approve_render import render_gate_approval_dry_run
        from sase._plan_approval_protocol import resolve_plan_approval_choice

        resolve_plan_approval_choice(notification.files[0], selected_kind)
        render_gate_approval_dry_run(
            plan,
            selected_kind,
            decision_lines=decision_context.card_lines(
                kind_label=selected_kind,
                plan_name=plan.display_name,
                dry_run=True,
            ),
        )
        return None
    option_inputs: dict[str, dict[str, object]] | None = None
    if decision_context.has_decisions:
        try:
            from sase._plan_approval_protocol import resolve_plan_approval_choice
            from sase.plan_approval_choices import plan_approval_selection_for_choice

            resolved_choice = resolve_plan_approval_choice(
                notification.files[0], selected_kind
            )
            selected_options = plan_approval_selection_for_choice(
                resolved_choice, tier="epic" if plan.tier == "epic" else "tale"
            )
        except (KeyError, ValueError):
            # The executor raises the authoritative selection error itself;
            # submit no decision inputs so its verdict is unchanged.
            selected_options = ()
            resolved_choice = selected_kind
        option_inputs = decision_context.option_inputs_for(
            resolved_choice=resolved_choice,
            selected=selected_options,
        )
    try:
        result = execute_plan_approval_response(
            plan_context_from_notification(notification),
            selected_kind,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            epic_launch_mode="launch",
            epic_launch_origin="cli",
            option_inputs=option_inputs,
            expected_review_revision=decision_context.review_revision,
            source="cli",
        )
    except PlanApprovalActionError as exc:
        if getattr(exc, "code", "") == "stale_review":
            raise _rendered_stale_review_error(plan) from exc
        raise
    from sase.main.plan_approve_render import render_gate_approval

    render_gate_approval(
        plan,
        result,
        decision_lines=decision_context.card_lines(
            kind_label=selected_kind,
            plan_name=plan.display_name,
            dry_run=False,
        ),
    )
    return result


class _LiveDecisionContext:
    """Frozen decision definitions, answers, and card for one live gate."""

    def __init__(
        self,
        *,
        definitions: list[dict[str, object]],
        review_revision: int | None,
        values: dict[str, object],
        rows: list[dict[str, object]],
        sheet: dict[str, object] | None,
        declaring_options: set[str],
        tier: str,
    ) -> None:
        self.definitions = definitions
        self.review_revision = review_revision
        self.values = values
        self.rows = rows
        self.sheet = sheet
        self.declaring_options = declaring_options
        self.tier = tier

    @property
    def has_decisions(self) -> bool:
        """Whether the live gate froze any Plan Decisions."""
        return bool(self.definitions)

    def option_inputs_for(
        self,
        *,
        resolved_choice: str,
        selected: tuple[str, ...],
    ) -> dict[str, dict[str, object]] | None:
        """Build per-option ``decision_*`` inputs for resolved options."""
        del resolved_choice
        if not self.has_decisions:
            return None
        if not self.values and not self.rows:
            return None
        payload = {
            f"decision_{decision_id}": value
            for decision_id, value in self.values.items()
        }
        inputs: dict[str, dict[str, object]] = {}
        for option_id in selected:
            if option_id in self.declaring_options:
                inputs[option_id] = dict(payload)
        return inputs or None

    def card_lines(
        self,
        *,
        kind_label: str,
        plan_name: str,
        dry_run: bool,
    ) -> list[str] | None:
        """Render the Section 1.4 card, or ``None`` without decisions."""
        if not self.has_decisions or self.sheet is None:
            return None
        from sase.main.plan_decide import decision_card_lines, verdict_for_kind

        return decision_card_lines(
            kind_label=kind_label,
            plan_name=plan_name,
            review_revision=self.review_revision or 0,
            sheet=self.sheet,
            rows=self.rows,
            verdict=verdict_for_kind(
                "epic" if self.tier == "epic" and kind_label == "epic" else kind_label
            ),
            dry_run=dry_run,
        )


def _live_decision_context(
    plan: PendingPlan, raw_map: dict[str, str]
) -> _LiveDecisionContext:
    """Freeze ``-D`` answers against the live gate before any side effect."""
    from sase.main.plan_decide import DecideError, caller_for_decide

    tier = "epic" if plan.tier == "epic" else "tale"
    definitions, review_revision, declaring = _live_gate_decisions(plan)
    if not definitions:
        if raw_map:
            raise DecideError(
                f"✗ {plan.display_name} has no decisions; "
                f"-D {next(iter(raw_map))} matches nothing.",
            )
        return _LiveDecisionContext(
            definitions=[],
            review_revision=None,
            values={},
            rows=[],
            sheet=None,
            declaring_options=set(),
            tier=tier,
        )
    from sase.main.plan_decide import resolve_decide_values

    values, rows = resolve_decide_values(
        definitions, raw_map, caller=caller_for_decide()
    )
    from sase.sdd.plan_decisions import sheet_binding

    try:
        sheet: dict[str, object] | None = sheet_binding(
            definitions, values, review_revision
        )
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    return _LiveDecisionContext(
        definitions=definitions,
        review_revision=review_revision,
        values=values,
        rows=rows,
        sheet=sheet,
        declaring_options=declaring,
        tier=tier,
    )


def _live_gate_decisions(
    plan: PendingPlan,
) -> tuple[list[dict[str, object]], int, set[str]]:
    """Read frozen ``payload.decisions`` and the revision from the bundle."""
    try:
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.paths import resolve_action_bundle
    except Exception:
        return [], 0, set()
    try:
        action = "EpicApproval" if plan.tier == "epic" else "PlanApproval"
        bundle = resolve_action_bundle(action, plan.notification.action_data)
        if bundle is None:
            return [], 0, set()
        envelope, _adapter = load_and_verify_bundle(bundle.root)
    except Exception:
        return [], 0, set()
    payload = envelope.get("payload")
    definitions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list):
        return [], 0, set()
    try:
        review_revision = int(envelope.get("review_revision", 1))
    except (TypeError, ValueError):
        review_revision = 1
    declaring: set[str] = set()
    raw_options = envelope.get("options")
    if isinstance(raw_options, list):
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            option_id = raw.get("id")
            schema = raw.get("input_schema")
            props = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(option_id, str) or not isinstance(props, dict):
                continue
            if any(str(name).startswith("decision_") for name in props):
                declaring.add(option_id)
    return (
        [item for item in definitions if isinstance(item, dict)],
        review_revision,
        declaring,
    )


def _rendered_stale_review_error(plan: PendingPlan) -> PlanApprovalActionError:
    """Explain a revision mismatch with a refresh path (contract 5)."""
    return _RenderedSelectionError(
        "stale_review",
        plan.display_name,
        "this review changed since it was shown; "
        "re-run `sase plan show` for the current revision and approve again",
    )


def _render_omitted_direct_approval_miss(outcome: PendingPlanMiss) -> None:
    """Explain the new explicit-file route when no live proposal is selected."""
    from rich.console import Console

    out = Console(stderr=True)
    out.print("[red]✗ Nothing is awaiting approval.[/red]")
    out.print("  To approve a plan without a live gate, pass its name or file:")
    out.print("    sase plan approve <PLAN>")
    if outcome.detail_lines:
        out.print(f"  [dim]{outcome.detail_lines[0]}[/dim]")


def resolve_plan_for_cli(selector: str | None) -> PendingPlan:
    """Resolve PLAN through the structured selector, rendering misses."""
    from sase.main.plan_pending import PendingPlanAmbiguity, PendingPlanMiss

    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise _rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if isinstance(outcome, PendingPlanMiss):
        render_miss(outcome, pending_plans())
        code = (
            "missing_selector" if outcome.selector is None else miss_error_code(outcome)
        )
        raise _rendered_error(code, outcome.selector or "selector", outcome.header)
    return outcome.plan


class _RenderedSelectionError(PlanApprovalActionError):
    """A selection error already rendered by the shared renderer."""

    _sase_rendered = True


def _rendered_error(code: str, target: str, message: str) -> PlanApprovalActionError:
    """Build a selection error already rendered by the shared renderer."""
    return _RenderedSelectionError(code, target, message)


def _validate_wait_spec_for_cli(wait: str | None) -> None:
    """Validate ``sase plan approve --wait`` before resolving the proposal."""
    text = wait.strip() if isinstance(wait, str) else None
    if not text:
        return
    from sase.wait_spec import WaitSpecError, parse_wait_spec

    try:
        parse_wait_spec(text)
    except WaitSpecError as exc:
        raise PlanApprovalActionError("invalid_request", "wait", str(exc)) from exc


def is_auto_approve_active() -> bool:
    """Check if auto-approve is active via env var or agent_meta.json.

    Returns True if SASE_AGENT_AUTO_APPROVE env var is set, or if the
    ``approve`` field is truthy in the agent's ``agent_meta.json`` (located
    via SASE_ARTIFACTS_DIR).
    """
    _argument, has_argument = _raw_auto_plan_argument()
    return bool(
        has_argument
        or os.environ.get("SASE_AGENT_AUTO_APPROVE")
        or _read_agent_meta().get("approve")
    )


def get_tmux_prefix() -> str:
    """Get the tmux window prefix for notifications."""
    project_dir = provider_project_dir_from_env() or "."
    project_name = os.path.basename(project_dir)
    prefix = f"[{project_name}]"

    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-t", tmux_pane, "-p", "#W"],
                capture_output=True,
                text=True,
                check=False,
            )
            window = result.stdout.strip()
            if window:
                prefix = f"[{project_name}#{window}]"
        except FileNotFoundError:
            pass

    return prefix


def send_desktop_notification(title: str, message: str) -> None:
    """Send a desktop notification (cross-platform)."""
    import platform

    if platform.system() == "Darwin":
        subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message],
            check=False,
            capture_output=True,
        )
    else:
        try:
            subprocess.run(
                ["notify-send", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass
