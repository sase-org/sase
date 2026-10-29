"""Prompt, launch, and display preparation for ordinary LLM invocations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sase.continuation_capture import (
    ContinuationSegmentCapture,
    record_prepared_prompt_capture_best_effort,
)
from sase.core.time import generate_timestamp
from sase.macro.directives import PromptDirectives

from .config import resolve_effective_effort
from .launch_selection import LaunchSelection, resolve_launch_selection
from .postprocessing import save_prompt_to_file
from .types import LLMInvocationOptions, LoggingContext, ModelTier


@dataclass(frozen=True, slots=True)
class _PreparedInvocation:
    """Values resolved before the ordinary provider invocation begins."""

    query: str
    context: LoggingContext
    model_override: str | None
    provider_name: str | None
    invocation_options: LLMInvocationOptions
    routing_context: Any
    agent_type_with_tier: str
    start_timestamp: str


def prepare_invocation(
    prompt: str,
    *,
    agent_type: str,
    model_tier: ModelTier,
    iteration: int | None,
    workflow_tag: str | None,
    artifacts_dir: str | None,
    workflow: str | None,
    suppress_output: bool,
    timestamp: str | None,
    is_home_mode: bool,
    branch_or_workspace: str | None,
    decision_counts: dict[str, Any] | None,
    provider_name: str | None,
    skip_preprocessing: bool,
    directives: PromptDirectives | None,
    launch_selection: LaunchSelection | None,
    authored_local_request: str | None,
    continuation_segments: Sequence[ContinuationSegmentCapture],
    model_tier_label: str,
    preprocess_prompt_fn: Callable[..., Any],
    print_decision_counts_fn: Callable[..., Any],
    print_prompt_and_response_fn: Callable[..., Any],
) -> _PreparedInvocation:
    """Resolve prompt directives, routing, display labels, and artifacts."""
    context = LoggingContext(
        agent_type=agent_type,
        iteration=iteration,
        workflow_tag=workflow_tag,
        artifacts_dir=artifacts_dir,
        suppress_output=suppress_output,
        workflow=workflow,
        timestamp=timestamp,
        is_home_mode=is_home_mode,
        branch_or_workspace=branch_or_workspace,
        decision_counts=decision_counts,
    )

    if skip_preprocessing:
        query = prompt
        result_directives = directives or PromptDirectives()
    else:
        result = preprocess_prompt_fn(prompt, is_home_mode=is_home_mode)
        query = result.prompt
        result_directives = result.directives
        continuation_segments = result.continuation_segments
        authored_local_request = prompt
    if artifacts_dir:
        record_prepared_prompt_capture_best_effort(
            artifacts_dir,
            authored_local_request=authored_local_request or prompt,
            materialized_prompt=query,
            segments=continuation_segments,
        )
        from sase.continuation_baseline import (
            measure_provider_preprocess,
            record_shadow_measurement,
        )

        record_shadow_measurement(
            artifacts_dir,
            measure_provider_preprocess(
                query,
                model_tier=model_tier,
                model_override=result_directives.model,
                provider_name=provider_name,
            ),
        )
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan

    finalizer_plan = resolve_and_persist_finalizer_plan(
        result_directives,
        artifacts_dir=artifacts_dir,
    )
    if finalizer_plan is not None and artifacts_dir:
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(
            artifacts_dir,
            "finalizers",
            finalizer_plan.agent_meta_projection(),
        )
        from sase.finalizers.status_summary import FinalizerStatusTracker

        FinalizerStatusTracker(artifacts_dir).seal_planned(
            plan_digest=finalizer_plan.plan.plan_digest,
            instance_ids=list(finalizer_plan.selected_instances),
        )
    model_override = result_directives.model
    model_alias_overrides = dict(result_directives.model_alias_overrides)
    if model_alias_overrides and artifacts_dir:
        from .launch_alias_overrides import export_launch_alias_overrides

        export_launch_alias_overrides(model_alias_overrides)
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(
            artifacts_dir,
            "model_alias_overrides",
            model_alias_overrides,
        )

    from .registry import capture_provider_routing_context

    routing_context = capture_provider_routing_context()
    if launch_selection is not None:
        provider_name = launch_selection.provider
        model_override = launch_selection.model
        effective_effort = launch_selection.reasoning_effort
        effort_explicit = launch_selection.effort_explicit
    else:
        selection = resolve_launch_selection(
            result_directives,
            model_alias_overrides,
            model_tier=model_tier,
            provider_name=provider_name,
            consume=True,
            routing_context=routing_context,
        )
        if selection is not None:
            provider_name = selection.provider
            model_override = selection.model
            effective_effort = selection.reasoning_effort
            effort_explicit = selection.effort_explicit
        else:
            effective_effort, effort_explicit = resolve_effective_effort(
                result_directives, None
            )

    invocation_options = LLMInvocationOptions(
        reasoning_effort=effective_effort,
        explicit=effort_explicit,
    )
    if model_override:
        agent_type_with_tier = f"{agent_type} [{model_override}]"
    else:
        agent_type_with_tier = f"{agent_type} [{model_tier_label}]"

    if not suppress_output and decision_counts is not None:
        print_decision_counts_fn(decision_counts)
    if not suppress_output:
        print_prompt_and_response_fn(
            prompt=query,
            response="",
            agent_type=agent_type_with_tier,
            iteration=iteration,
            show_prompt=True,
            show_response=False,
        )

    start_timestamp = timestamp or generate_timestamp()
    if artifacts_dir:
        save_prompt_to_file(
            prompt=query,
            artifacts_dir=artifacts_dir,
            agent_type=agent_type,
            iteration=iteration,
        )
    return _PreparedInvocation(
        query=query,
        context=context,
        model_override=model_override,
        provider_name=provider_name,
        invocation_options=invocation_options,
        routing_context=routing_context,
        agent_type_with_tier=agent_type_with_tier,
        start_timestamp=start_timestamp,
    )
