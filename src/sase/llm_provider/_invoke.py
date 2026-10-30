"""Main invoke_agent() orchestrator for the LLM provider abstraction layer.

This is the provider-agnostic orchestration layer that delegates the actual
LLM call to a pluggable provider.
"""

import os
import subprocess
import time
from collections.abc import Sequence
from typing import Any, Literal, cast

from sase.continuation_capture import (
    ContinuationSegmentCapture,
)
from sase.env_contracts import (
    SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV,
    SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV,
)
from ._instruction_boundary import invoke_with_instructions
from ._invoke_errors import finalize_staged_after_provider_error
from .deferred import (
    ProviderEvidence,
    digest_response,
    record_deferred_provider_evidence,
)
from ._invoke_provider_setup import (
    prepare_provider_invocation,
    provider_sync_ceiling_seconds as _provider_sync_ceiling_seconds,
)
from ._invoke_setup import prepare_invocation
from .messages import AIMessage
from sase.output import print_decision_counts, print_prompt_and_response
from sase.telemetry.metrics import (
    LLM_CACHE_READ_TOKENS,
    LLM_ERRORS,
    LLM_INPUT_TOKENS,
    LLM_INVOCATION_DURATION,
    LLM_INVOCATIONS,
    LLM_OUTPUT_TOKENS,
)

from .postprocessing import (
    postprocess_error,
    postprocess_success,
)
from .preprocessing import preprocess_prompt
from sase.macro.directives import PromptDirectives
from .gate_intent_guard import raise_if_gate_intent_lost
from .launch_selection import LaunchSelection
from .registry import (
    LLM_EXEC_PROVIDER_ENV,
    get_default_provider_name,
    get_provider,
    resolve_execution_provider_name,
)
from .usage_limit_disable import handle_possible_usage_limit
from .types import (
    MODEL_SIZE_TO_TIER,
    MODEL_TIER_TO_LABEL,
    LLMInvocationError,
    ModelTier,
)


def _record_deferred_evidence(
    *,
    agent_type: str,
    artifacts_dir: str | None,
    evidence_token: str | None,
    response_content: str,
) -> None:
    """Stash completed-provider evidence for the host completion seam.

    The nonce is read from the live provider-turn environment before the
    ``finally`` block below restores it, binding the evidence to the turn
    whose response just completed. Without an artifacts directory there is
    no finalizer turn to complete later, so no evidence is recorded.
    """
    if not artifacts_dir or not evidence_token:
        return
    nonce = (os.environ.get("SASE_FINAL_TURN_NONCE") or "").strip()
    digest, chars = digest_response(response_content)
    record_deferred_provider_evidence(
        evidence_token,
        ProviderEvidence(
            agent_type=agent_type,
            turn_nonce=nonce,
            response_sha256=digest,
            response_chars=chars,
        ),
    )


def invoke_agent(
    prompt: str,
    *,
    agent_type: str,
    model_tier: ModelTier = "large",
    model_size: Literal["little", "big"] | None = None,
    iteration: int | None = None,
    workflow_tag: str | None = None,
    artifacts_dir: str | None = None,
    workflow: str | None = None,
    suppress_output: bool = False,
    timestamp: str | None = None,
    is_home_mode: bool = False,
    branch_or_workspace: str | None = None,
    decision_counts: dict[str, Any] | None = None,
    provider_name: str | None = None,
    skip_preprocessing: bool = False,
    directives: PromptDirectives | None = None,
    launch_selection: LaunchSelection | None = None,
    authored_local_request: str | None = None,
    continuation_segments: Sequence[ContinuationSegmentCapture] = (),
    defer_finalizers: bool = False,
    evidence_token: str | None = None,
) -> AIMessage:
    """Invoke an LLM agent with standard preprocessing, logging, and postprocessing.

    This is the main entry point for sending prompts to any configured LLM
    backend. It handles the full lifecycle:

    1. Preprocess the prompt (macro, file refs, jinja2, prettier).
    2. Display decision counts and prompt (if not suppressed).
    3. Save prompt to artifacts directory.
    4. Get provider from registry and invoke.
    5. Postprocess response (logging, chat history, audio).
    6. Return AIMessage.

    Args:
        prompt: The raw prompt to send to the agent.
        agent_type: Type of agent (e.g., "editor", "planner", "research").
        model_tier: Model tier ("large" or "small").
        model_size: Deprecated. Use ``model_tier`` instead. Maps "big" to
            "large" and "little" to "small".
        iteration: Optional iteration number.
        workflow_tag: Optional workflow tag.
        artifacts_dir: Optional artifacts directory for logging.
        workflow: Optional workflow name for chat history.
        suppress_output: If True, suppress output display.
        timestamp: Optional timestamp for chat file naming (YYmmdd_HHMMSS).
        is_home_mode: If True, skip file copying for ``@`` file references.
        branch_or_workspace: Optional branch/workspace name for chat history
            filenames. When not provided, auto-detected from the current
            working directory.
        decision_counts: Optional planning agent decision counts for display.
        provider_name: Optional provider name override (default from config).
        skip_preprocessing: If True, skip the ``preprocess_prompt()`` call
            and use the prompt as-is (caller already preprocessed).
        directives: Pre-extracted prompt directives to use when
            ``skip_preprocessing=True``.
        launch_selection: An already-resolved provider/model/effort
            selection. When supplied, ``invoke_agent()`` uses it as-is
            instead of resolving *directives* itself, so a caller that
            already consumed a pooled model alias (e.g. the workflow
            executor's prompt step) does not advance its cursor twice.
        authored_local_request: Optional raw local request corresponding to
            *prompt* when the caller already preprocessed it.
        continuation_segments: Optional local prompt provenance segments
            collected by preprocessing or workflow expansion.
        defer_finalizers: When True, return the completed provider result
            without running the finalizer controller, and stash
            completed-provider evidence under *evidence_token* for the
            host-owned workflow completion seam to take. The normal
            non-HITL path is unchanged.
        evidence_token: Caller-supplied token identifying one deferred
            provider turn. Required when *defer_finalizers* is true with an
            artifacts directory; ignored otherwise.

    Returns:
        The AIMessage response from the agent.
    """
    # Handle deprecated model_size parameter
    if model_size is not None:
        model_tier = MODEL_SIZE_TO_TIER[model_size]

    # Check for global model tier override (env var)
    tier_override = os.environ.get("SASE_MODEL_TIER_OVERRIDE") or os.environ.get(
        "SASE_MODEL_SIZE_OVERRIDE"
    )
    if tier_override:
        # Accept both old ("big"/"little") and new ("large"/"small") values
        if tier_override in MODEL_SIZE_TO_TIER:
            model_tier = MODEL_SIZE_TO_TIER[tier_override]
        elif tier_override in ("large", "small"):
            model_tier = cast(ModelTier, tier_override)

    prepared = prepare_invocation(
        prompt,
        agent_type=agent_type,
        model_tier=model_tier,
        iteration=iteration,
        workflow_tag=workflow_tag,
        artifacts_dir=artifacts_dir,
        workflow=workflow,
        suppress_output=suppress_output,
        timestamp=timestamp,
        is_home_mode=is_home_mode,
        branch_or_workspace=branch_or_workspace,
        decision_counts=decision_counts,
        provider_name=provider_name,
        skip_preprocessing=skip_preprocessing,
        directives=directives,
        launch_selection=launch_selection,
        authored_local_request=authored_local_request,
        continuation_segments=continuation_segments,
        model_tier_label=MODEL_TIER_TO_LABEL[model_tier],
        preprocess_prompt_fn=preprocess_prompt,
        print_decision_counts_fn=print_decision_counts,
        print_prompt_and_response_fn=print_prompt_and_response,
    )
    query = prepared.query
    context = prepared.context
    model_override = prepared.model_override
    provider_name = prepared.provider_name
    invocation_options = prepared.invocation_options
    routing_context = prepared.routing_context
    start_timestamp = prepared.start_timestamp

    # 7. Get provider and invoke
    requested_provider_label = provider_name or get_default_provider_name(
        routing_context=routing_context
    )
    execution_provider_label = resolve_execution_provider_name(
        requested_provider_label,
        routing_context=routing_context,
    )
    execution_override_active = bool(os.environ.get(LLM_EXEC_PROVIDER_ENV, "").strip())
    provider_lookup_name = (
        execution_provider_label if execution_override_active else provider_name
    )
    context.metadata_llm_provider = requested_provider_label
    context.metadata_model = model_override
    t0 = time.monotonic()
    previous_finalizer_nonce = os.environ.get("SASE_FINAL_TURN_NONCE")
    previous_sync_ceiling = os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
    previous_soft_ceiling = os.environ.get(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV)
    if artifacts_dir:
        from sase.finalizers.declaration import mint_finalizer_turn_nonce

        mint_finalizer_turn_nonce()
    try:
        provider, query = prepare_provider_invocation(
            provider_lookup_name=provider_lookup_name,
            execution_provider_label=execution_provider_label,
            requested_provider_label=requested_provider_label,
            routing_context=routing_context,
            query=query,
            model_tier=model_tier,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=invocation_options,
            context=context,
            get_provider_fn=get_provider,
            provider_sync_ceiling_fn=_provider_sync_ceiling_seconds,
        )
        if artifacts_dir:
            from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase

        invoke_result = invoke_with_instructions(
            provider,
            query,
            purpose="ordinary",
            artifacts_dir=artifacts_dir,
            provider_name=execution_provider_label,
            agent_type=agent_type,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=invocation_options,
        )
        if artifacts_dir:
            mark_lifecycle_phase(artifacts_dir, "provider_done")
        raise_if_gate_intent_lost(artifacts_dir)
        if defer_finalizers:
            _record_deferred_evidence(
                agent_type=agent_type,
                artifacts_dir=artifacts_dir,
                evidence_token=evidence_token,
                response_content=invoke_result.content,
            )
        else:
            if artifacts_dir:
                mark_lifecycle_phase(artifacts_dir, "finalizing")
                from sase.agent.staged_handoff import (
                    read_staged_handoff,
                    write_staged_handoff_response,
                )

                staged_handoff = read_staged_handoff(artifacts_dir)
                if staged_handoff is not None:
                    write_staged_handoff_response(
                        str(staged_handoff["staged_id"]),
                        invoke_result.content,
                        artifacts_dir=artifacts_dir,
                    )
            from sase.finalizers import run_finalizers

            invoke_result = run_finalizers(
                provider=provider,
                original_prompt=query,
                invoke_result=invoke_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=invocation_options,
            )
        response_content = invoke_result.content

        # Record success metrics
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=execution_provider_label, status="ok").inc()
        LLM_INVOCATION_DURATION.labels(provider=execution_provider_label).observe(
            elapsed
        )
        if invoke_result.usage:
            LLM_INPUT_TOKENS.labels(provider=execution_provider_label).inc(
                invoke_result.usage.get("input_tokens", 0)
            )
            LLM_OUTPUT_TOKENS.labels(provider=execution_provider_label).inc(
                invoke_result.usage.get("output_tokens", 0)
            )
            LLM_CACHE_READ_TOKENS.labels(provider=execution_provider_label).inc(
                invoke_result.usage.get("cache_read_input_tokens", 0)
            )

        # 8. Postprocess success
        postprocess_success(
            prompt=query,
            response=response_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        return AIMessage(content=response_content)

    except subprocess.CalledProcessError as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=execution_provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=execution_provider_label).observe(
            elapsed
        )
        LLM_ERRORS.labels(
            provider=execution_provider_label, error_type="CalledProcessError"
        ).inc()

        parts = [f"Error running LLM provider command (exit code {e.returncode})"]
        if e.stderr:
            parts.append(f"stderr: {e.stderr.strip()}")
        if e.output:
            parts.append(f"output: {e.output.strip()}")
        error_content = "\n".join(parts)

        handle_possible_usage_limit(
            provider=execution_provider_label,
            error_text=error_content,
            model=context.metadata_model,
            artifacts_dir=artifacts_dir,
        )

        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        if "provider" in locals():
            finalize_staged_after_provider_error(
                provider=provider,
                query=query,
                error_content=error_content,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=invocation_options,
                execution_provider_label=execution_provider_label,
            )

        raise LLMInvocationError(error_content) from e

    except LLMInvocationError as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=execution_provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=execution_provider_label).observe(
            elapsed
        )
        LLM_ERRORS.labels(
            provider=execution_provider_label, error_type="LLMInvocationError"
        ).inc()

        error_content = str(e)

        handle_possible_usage_limit(
            provider=execution_provider_label,
            error_text=error_content,
            model=context.metadata_model,
            artifacts_dir=artifacts_dir,
        )

        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        if "provider" in locals():
            finalize_staged_after_provider_error(
                provider=provider,
                query=query,
                error_content=error_content,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=invocation_options,
                execution_provider_label=execution_provider_label,
            )

        raise

    except Exception as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=execution_provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=execution_provider_label).observe(
            elapsed
        )
        LLM_ERRORS.labels(
            provider=execution_provider_label, error_type=type(e).__name__
        ).inc()

        error_content = f"Error: {str(e)}"

        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        if "provider" in locals():
            finalize_staged_after_provider_error(
                provider=provider,
                query=query,
                error_content=error_content,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=invocation_options,
                execution_provider_label=execution_provider_label,
            )

        raise LLMInvocationError(error_content) from e

    finally:
        if artifacts_dir:
            # Eager leg of starter-scoped detached runs: stop this runner's
            # unjoined detached runs before the turn ends. Best effort and
            # never raises; actively joined runs are preserved.
            try:
                from sase.tool.detach_cleanup import stop_unjoined_detached_runs

                stop_unjoined_detached_runs(artifacts_dir=artifacts_dir)
            except Exception:  # noqa: BLE001 - cleanup never fails a turn.
                pass
            if previous_finalizer_nonce is None:
                os.environ.pop("SASE_FINAL_TURN_NONCE", None)
            else:
                os.environ["SASE_FINAL_TURN_NONCE"] = previous_finalizer_nonce
        if previous_sync_ceiling is None:
            os.environ.pop(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, None)
        else:
            os.environ[SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV] = previous_sync_ceiling
        if previous_soft_ceiling is None:
            os.environ.pop(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV, None)
        else:
            os.environ[SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV] = (
                previous_soft_ceiling
            )
