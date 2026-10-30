"""Host-owned workflow completion seam for staged HITL reviews.

A non-staged workflow prompt step invokes the provider (which settles
finalizers inside :func:`sase.llm_provider.invoke_agent`) before calling its
HITL handler. Staging after that point hits the accepted-current-submission
guard, and the settled finalizer evidence is bound to a context that never
knew about the handoff. Script steps have the mirror problem: they can
request HITL without any provider invocation at that step, so a prior step's
finalizer result is not evidence for their edits.

This module is the narrow host-owned boundary that fixes the ordering
without relaxing CLI admission:

1. Reviewed prompt steps obtain the provider result first via
   :func:`invoke_provider_for_review` (finalizers deferred), so output
   preparation and review staging precede finalizer settlement. The normal
   non-HITL ``invoke_agent`` path is unchanged.
2. :func:`prepare_workflow_review` builds the same durable shell-backed
   review specification the agent-context HITL handler publishes today,
   frozen through the shared staged-gate preparation (validation,
   auto-policy freeze, resource snapshots).
3. :func:`stage_workflow_review` persists the admitted handoff before
   workflow cleanup. After cleanup, :func:`settle_workflow_review` binds the
   staged handoff to a refreshed finalizer context through the ordinary
   finalizer controller, before the runner's adoption epilogue.

The seam never clears a valid submission, never accepts a stale
declaration as proof for the changed context, and adds no
environment-variable bypass. When the refreshed context cannot cover the
stage, the controller runs ordinary declaration recovery (which fails
closed here: the completion pass carries no live provider) or legal
host-synthesized carry. A finalizer failure leaves the stage held so the
runner's adoption epilogue holds publication instead of publishing
past an unsettled turn.

Agent-context HITL reviews now use this staged path and suspend workflow
execution while preserving the waiting step and pending continuation. Legacy
non-agent gate callers keep their immediate publication path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.staged_handoff import (
    HostStageAdmission,
    HostStageIdentity,
    StagedHandoffError,
    acquire_staging_reservation,
    release_staging_reservation,
    write_staged_handoff,
    write_staged_handoff_response,
)

#: Command label used for workflow review staging admission.
WORKFLOW_REVIEW_COMMAND = "workflow review"

#: Workflow step types the completion seam accepts.
WORKFLOW_REVIEW_STEP_TYPES = ("agent", "bash", "python")


class WorkflowCompletionError(RuntimeError):
    """Raised when a host-owned workflow completion cannot proceed."""


@dataclass(frozen=True)
class WorkflowReviewIdentity:
    """Explicit originating invocation/step identity for one review."""

    workflow: str
    step: str
    step_type: str


@dataclass(frozen=True)
class PreparedWorkflowReview:
    """Frozen staged-gate preparation for one configured workflow review."""

    identity: WorkflowReviewIdentity
    request_id: str
    staged_id: str
    successor_workspace: str
    carry_allowed: bool
    reservation_id: str
    preparation: Any
    evidence_wire: str | None


class _NonInvokingProvider:
    """Provider adapter that refuses to start a model turn.

    The completion pass reuses the already-completed provider result (prompt
    steps) or the script step output (bash/python steps). When the refreshed
    context needs a live declaration-recovery turn, this refusal fails that
    recovery closed so the stage stays held instead of publishing past an
    unsettled turn.
    """

    def invoke(self, *args: object, **kwargs: object) -> Any:
        raise RuntimeError("host-owned workflow completion must not invoke a provider")


def _drop_uncoverable_stale_submission(
    *,
    artifacts_dir: str,
    staged_id: str,
) -> bool:
    """Drop a stale submission the refreshed context cannot honor, if legal.

    A submission accepted for an earlier step goes stale when a later step
    dirties new ground: the commit executor would reject it and the stage
    would hold. When the refreshed publication (which binds the staged
    review) requires no submission — every dirty obligation may be
    carried — and names this stage, the stale file is removed so the
    ordinary controller path installs legal host-synthesized carry. A
    submission the refreshed context can still honor is left untouched so
    its commit intent lands before publication. Only stale submissions are
    ever removed; a valid one is never cleared to evade admission.

    Returns True when the submission file was removed.
    """
    from sase.finalizers.commit_carry import carry_action_allowed_for_handoff
    from sase.finalizers.declaration import (
        FinalizerDeclarationError,
        final_submission_is_current,
        load_latest_finalizer_submission,
        publish_final_context,
        require_artifacts_dir,
    )
    from sase.finalizers.declaration_manifest_io import FINAL_SUBMISSION_FILENAME
    from sase.finalizers.declaration_store import accepted_context_from_submission

    try:
        publication = publish_final_context(artifacts_dir=artifacts_dir)
    except FinalizerDeclarationError:
        return False
    handoff = publication.context.handoff
    if handoff is None or handoff.staged_ref != staged_id:
        return False
    if publication.submission_required:
        return False
    if not carry_action_allowed_for_handoff(handoff):
        return False
    try:
        if final_submission_is_current(artifacts_dir=artifacts_dir):
            return False
        root = require_artifacts_dir(artifacts_dir, "workflow review completion")
        submission = load_latest_finalizer_submission(root)
        accepted = accepted_context_from_submission(
            submission,
            fallback=publication.context,
        )
    except FinalizerDeclarationError:
        return False
    accepted_by_id = {
        obligation.obligation_id: obligation
        for obligation in accepted.obligations
        if obligation.kind == "repository"
    }
    uncoverable = False
    for obligation in publication.context.obligations:
        if obligation.kind != "repository":
            continue
        accepted_obligation = accepted_by_id.get(obligation.obligation_id)
        if accepted_obligation is None:
            uncoverable = True
            break
        expected = accepted_obligation.digest
        if expected and expected != obligation.digest:
            uncoverable = True
            break
    if not uncoverable:
        return False
    # Re-verify staleness immediately before removing: a concurrently
    # accepted submission wins over the stale file.
    try:
        if final_submission_is_current(artifacts_dir=artifacts_dir):
            return False
    except FinalizerDeclarationError:
        return False
    try:
        (root / FINAL_SUBMISSION_FILENAME).unlink()
    except OSError:
        return False
    return True


def invoke_provider_for_review(
    prompt: str,
    *,
    agent_type: str,
    artifacts_dir: str,
    workflow: str | None = None,
    branch_or_workspace: str | None = None,
    directives: Any | None = None,
    launch_selection: Any | None = None,
    authored_local_request: str | None = None,
    continuation_segments: Sequence[Any] = (),
) -> tuple[Any, Any]:
    """Invoke the provider for a reviewed prompt step, deferring finalizers.

    Returns the ``(AIMessage, ProviderEvidence)`` pair. The evidence is
    recorded by the deferred :func:`invoke_agent` branch from the live
    provider-turn nonce and the completed response bytes; it is taken
    exactly once under a fresh token, so an agent review cannot stage
    without a completed provider turn at its own step.
    """
    from sase.llm_provider import invoke_agent
    from sase.llm_provider.deferred import take_deferred_provider_evidence

    token = uuid4().hex
    response = invoke_agent(
        prompt,
        agent_type=agent_type,
        artifacts_dir=artifacts_dir,
        workflow=workflow,
        branch_or_workspace=branch_or_workspace,
        skip_preprocessing=True,
        directives=directives,
        launch_selection=launch_selection,
        authored_local_request=authored_local_request,
        continuation_segments=continuation_segments,
        defer_finalizers=True,
        evidence_token=token,
    )
    evidence = take_deferred_provider_evidence(token)
    if evidence is None:
        raise WorkflowCompletionError(
            "deferred provider turn recorded no completed-provider evidence"
        )
    return response, evidence


def prepare_workflow_review(
    *,
    identity: WorkflowReviewIdentity,
    output: Any,
    artifacts_dir: str,
    has_output: bool = False,
    output_types: Mapping[str, str] | None = None,
    timeout_seconds: float = 3600,
    provider_evidence: Any | None = None,
) -> PreparedWorkflowReview:
    """Prepare a configured review from completed step output.

    Agent steps require *provider_evidence* from
    :func:`invoke_provider_for_review`; script steps carry none. The HITL
    gate spec hardcodes a manual policy, so preparation must never resolve
    to synchronous auto: an auto resolution would skip the review.
    """
    from sase.gate_turn.staged_contract import (
        collect_staged_gate_creator,
        discard_staged_gate_snapshot,
        prepare_staged_gate,
    )
    from sase.macro.workflow_hitl_gate import workflow_hitl_shell_spec_for_staging

    if identity.step_type not in WORKFLOW_REVIEW_STEP_TYPES:
        raise WorkflowCompletionError(
            f"unknown workflow review step type: {identity.step_type!r}"
        )
    if not identity.workflow.strip() or not identity.step.strip():
        raise WorkflowCompletionError(
            "workflow review must name its originating workflow and step"
        )
    evidence_wire: str | None = None
    if identity.step_type == "agent":
        if provider_evidence is None:
            raise WorkflowCompletionError(
                "agent workflow reviews require completed-provider evidence"
            )
        evidence_wire = provider_evidence.to_wire()
        if not evidence_wire.strip():
            raise WorkflowCompletionError(
                "agent workflow reviews require completed-provider evidence"
            )
    admission = HostStageAdmission(
        identity=HostStageIdentity(
            workflow=identity.workflow,
            step=identity.step,
            step_type=identity.step_type,
        ),
        provider_evidence=evidence_wire,
    )
    reservation_id = acquire_staging_reservation(
        artifacts_dir=artifacts_dir,
        command=WORKFLOW_REVIEW_COMMAND,
        host=admission,
    )
    preparation = None
    try:
        spec = workflow_hitl_shell_spec_for_staging(
            step_name=identity.step,
            step_type=identity.step_type,
            output=output,
            workflow_name=identity.workflow,
            artifacts_dir=artifacts_dir,
            has_output=has_output,
            output_types=output_types,
            timeout_seconds=timeout_seconds,
        )
        creator = collect_staged_gate_creator(artifacts_dir=artifacts_dir)
        preparation = prepare_staged_gate(
            spec,
            creator=creator,
            artifacts_dir=artifacts_dir,
        )
        if preparation.auto_execute:
            raise WorkflowCompletionError(
                "workflow reviews cannot resolve to synchronous auto execution"
            )
        if preparation.record is None:
            raise WorkflowCompletionError(
                "workflow review preparation produced no staged record"
            )
        return PreparedWorkflowReview(
            identity=identity,
            request_id=preparation.request_id,
            staged_id=preparation.staged_id,
            successor_workspace=preparation.successor_workspace,
            carry_allowed=preparation.carry_allowed,
            reservation_id=reservation_id,
            preparation=preparation,
            evidence_wire=evidence_wire,
        )
    except BaseException:
        if preparation is not None:
            discard_staged_gate_snapshot(artifacts_dir, preparation.staged_id)
        try:
            release_staging_reservation(
                reservation_id,
                artifacts_dir=artifacts_dir,
            )
        except StagedHandoffError:
            pass
        raise


def stage_workflow_review(
    review: PreparedWorkflowReview,
    *,
    artifacts_dir: str,
    provider_content: str | None = None,
) -> None:
    """Persist an admitted review before workflow cleanup runs.

    Frozen gate resources and the real provider response are durable before
    finally/post-step cleanup can change their source files. Finalizers run
    later through :func:`settle_workflow_review`.
    """
    from sase.gate_turn.staged_contract import discard_staged_gate_snapshot

    # A write failure discards the prepared snapshots and releases the
    # reservation. Once the staged record commits, later failures keep it held.
    try:
        write_staged_handoff(
            review.preparation.record,
            artifacts_dir=artifacts_dir,
            command=WORKFLOW_REVIEW_COMMAND,
            reservation_id=review.reservation_id,
            host=HostStageAdmission(
                identity=HostStageIdentity(
                    workflow=review.identity.workflow,
                    step=review.identity.step,
                    step_type=review.identity.step_type,
                ),
                provider_evidence=review.evidence_wire,
            ),
        )
    except BaseException:
        discard_staged_gate_snapshot(artifacts_dir, review.staged_id)
        try:
            release_staging_reservation(
                review.reservation_id,
                artifacts_dir=artifacts_dir,
            )
        except StagedHandoffError:
            pass
        raise
    if review.identity.step_type == "agent" and provider_content is not None:
        write_staged_handoff_response(
            review.staged_id,
            provider_content,
            artifacts_dir=artifacts_dir,
        )


def settle_workflow_review(
    review: PreparedWorkflowReview,
    *,
    artifacts_dir: str,
    provider_content: str | None = None,
    original_prompt: str = "",
    model_tier: Any = "large",
    suppress_output: bool = True,
    model_override: str | None = None,
) -> Any:
    """Run ordinary finalizers after cleanup with the staged review bound.

    A finalizer failure leaves the stage held: the runner's adoption epilogue
    must hold publication, never publish past an unsettled turn. On success
    the refreshed finalizer context must name the staged review.
    """
    from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
    from sase.finalizers.controller import run_finalizers
    from sase.finalizers.declaration import mint_finalizer_turn_nonce
    from sase.finalizers.declaration_manifest_io import load_latest_finalizer_context
    from sase.llm_provider.types import InvokeResult

    # A submission accepted for an earlier step cannot cover new ground
    # dirtied by a later step. When carry is legal, drop the uncoverable
    # stale file so the controller installs host-synthesized carry naming
    # this stage; otherwise the commit executor would reject it and the
    # stage would hold. Honorable declarations are left untouched.
    _drop_uncoverable_stale_submission(
        artifacts_dir=artifacts_dir,
        staged_id=review.staged_id,
    )
    mark_lifecycle_phase(artifacts_dir, "finalizing")
    mint_finalizer_turn_nonce()
    try:
        result = run_finalizers(
            provider=_NonInvokingProvider(),
            original_prompt=original_prompt,
            invoke_result=InvokeResult(content=provider_content or ""),
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
        )
    except BaseException:
        # Leave the stage held: finalizer failure prevents publication.
        raise
    context = load_latest_finalizer_context(Path(artifacts_dir))
    handoff = context.handoff
    if handoff is None or handoff.staged_ref != review.staged_id:
        # Leave the stage held: something removed or replaced the staged
        # record mid-flight, so the adoption epilogue must hold it.
        raise WorkflowCompletionError(
            "refreshed finalizer context does not name the staged review"
        )
    return result


def complete_workflow_review(
    review: PreparedWorkflowReview,
    *,
    artifacts_dir: str,
    provider_content: str | None = None,
    original_prompt: str = "",
    model_tier: Any = "large",
    suppress_output: bool = True,
    model_override: str | None = None,
) -> Any:
    """Stage a review and immediately settle it for compatibility callers."""
    stage_workflow_review(
        review,
        artifacts_dir=artifacts_dir,
        provider_content=provider_content,
    )
    return settle_workflow_review(
        review,
        artifacts_dir=artifacts_dir,
        provider_content=provider_content,
        original_prompt=original_prompt,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
    )


__all__ = [
    "PreparedWorkflowReview",
    "WORKFLOW_REVIEW_COMMAND",
    "WORKFLOW_REVIEW_STEP_TYPES",
    "WorkflowCompletionError",
    "WorkflowReviewIdentity",
    "complete_workflow_review",
    "invoke_provider_for_review",
    "prepare_workflow_review",
    "settle_workflow_review",
    "stage_workflow_review",
]
