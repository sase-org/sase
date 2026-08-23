"""Declaration and execution-context helpers for the finalizer controller."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import has_pending_handoff
from sase.core.finalizer_wire import (
    FinalizerInstanceResultWire,
    FinalizerPlanWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
    FinalizerDeclarationError,
    ensure_final_declaration_or_recover,
    final_submission_is_current,
    load_latest_finalizer_submission,
    publish_final_context,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF
from sase.llm_provider.types import ModelTier


class FinalizerControllerError(RuntimeError):
    """Raised when the generic controller cannot reach a safe fixed point."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def should_skip_finalizers(artifacts_dir: str | None) -> bool:
    """Return whether the current invocation has no finalizer work to perform."""
    if not artifacts_dir:
        return True
    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        return True
    return has_pending_handoff(artifacts_dir)


def entries_from_plan(plan: FinalizerPlanWire) -> tuple[dict[str, Any], ...]:
    """Convert authenticated plan entries into controller-friendly records."""
    return tuple(
        {
            "instance_id": entry.instance_id,
            "provider_ref": entry.provider_ref,
            "resolved_index": entry.resolved_index,
        }
        for entry in plan.entries
    )


def bind_execution_context(
    artifacts_dir: str | None,
    plan: FinalizerPlanWire,
    publication: FinalContextPublication,
) -> FinalizerExecutionContext:
    """Bind a plan and accepted submission to an executor context."""
    payloads: dict[str, Any] = {}
    if artifacts_dir:
        try:
            submission = load_latest_finalizer_submission(Path(artifacts_dir))
        except FinalizerDeclarationError:
            submission = None
        raw = submission.get("submission") if isinstance(submission, Mapping) else None
        items = raw.get("payloads") if isinstance(raw, Mapping) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                instance_id = item.get("instance_id")
                if isinstance(instance_id, str) and "payload" in item:
                    payloads[instance_id] = item.get("payload")
    return FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
        plan_digest=plan.plan_digest,
        run_id=publication.context.run_id,
        agent_id=publication.context.agent_id,
        turn_nonce=publication.context.turn_nonce,
        context_digest=publication.context.context_digest,
        selected=tuple(entry.instance_id for entry in plan.entries),
        accepted_payloads=payloads,
        obligations=tuple(
            finalizer_wire_to_json_dict(item)
            for item in publication.context.obligations
        ),
    )


def ensure_current_declaration(
    *,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any,
    original_prompt: str | None = None,
) -> Any:
    """Recover a required stale declaration within its one-shot budget."""
    publication = publish_final_context(artifacts_dir=artifacts_dir)
    if not publication.submission_required or final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        return invoke_result
    if declaration_recovery_spent(artifacts_dir):
        raise FinalizerControllerError(
            "required finalizer declaration is missing or stale and the "
            "declaration-recovery budget is exhausted",
            code="stale_declaration",
        )
    recovered = ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=invoke_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        artifacts_dir=artifacts_dir,
        options=options,
        original_prompt=original_prompt,
    )
    _rebind_turn_nonce_to_accepted_context(artifacts_dir)
    return recovered


def _rebind_turn_nonce_to_accepted_context(artifacts_dir: str | None) -> None:
    if not artifacts_dir:
        return
    try:
        payload = json.loads(
            (Path(artifacts_dir) / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, Mapping):
        return
    context = payload.get("context")
    if not isinstance(context, Mapping):
        return
    nonce = context.get("turn_nonce")
    if isinstance(nonce, str) and nonce:
        os.environ[SASE_FINAL_TURN_NONCE_ENV] = nonce


def declaration_recovery_spent(artifacts_dir: str | None) -> bool:
    """Return whether declaration recovery has already been attempted."""
    if not artifacts_dir:
        return False
    return (Path(artifacts_dir) / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).is_file()


def pending_instance_ids(
    entries: tuple[dict[str, Any], ...],
    payload: Mapping[str, Any],
    results_by_id: Mapping[str, FinalizerInstanceResultWire],
    ran_non_commit: set[str],
) -> tuple[str, ...]:
    """Find plan instances that still need to run for the published context."""
    selected = payload.get("selected_instances")
    requirements: dict[str, Mapping[str, Any]] = {}
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, Mapping) and isinstance(item.get("instance_id"), str):
                requirements[str(item["instance_id"])] = item
    pending: list[str] = []
    for entry in entries:
        instance_id = entry["instance_id"]
        provider_ref = entry["provider_ref"]
        if provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
            requirement = requirements.get(instance_id, {})
            triggered = bool(
                requirement.get("submission_required")
                or requirement.get("trigger") == "dirty_repository"
            )
            previous = results_by_id.get(instance_id)
            if previous is None or previous.status != "success" or triggered:
                pending.append(instance_id)
            continue
        if instance_id not in ran_non_commit:
            pending.append(instance_id)
    return tuple(pending)


def cycle_fingerprint(context_digest: str | None, pending: tuple[str, ...]) -> str:
    """Build the stable state key used to detect no-progress cycles."""
    digest = context_digest or ""
    return f"{digest}:{','.join(pending)}"
