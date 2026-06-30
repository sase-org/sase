"""Accepted-plan follow-up handling for the agent execution loop."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.run_agent_exec_plan import (
    agent_name_for_suffix,
    record_workflow_metadata,
)
from sase.axe.run_agent_exec_plan_artifacts import get_embedded_workflow_refs
from sase.axe.run_agent_exec_plan_sdd import (
    build_epic_plan_ref,
    build_saved_plan_ref,
    build_sdd_plan_ref,
    commit_sdd_files_for_exec_plan,
    infer_epic_legend_bead_id,
    plan_kind_for_action,
)
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
)
from sase.llm_provider.config import format_model_directive_value
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)


def _accepted_plan_action_for_meta(plan_result: Any) -> str:
    if plan_result.action == "approve" and not plan_result.run_coder:
        return "commit"
    if (
        plan_result.action == "approve"
        and plan_result.commit_plan
        and plan_result.run_coder
    ):
        return "tale"
    return str(plan_result.action)


def _commit_sdd_files(
    workspace_dir: str, plan_name: str, *, plan_kind: str = "tales"
) -> bool:
    return commit_sdd_files_for_exec_plan(
        workspace_dir,
        plan_name,
        plan_kind=plan_kind,
        logger=logger,
        subprocess_run=subprocess.run,
    )


@dataclass(frozen=True)
class _FollowupModel:
    """The follow-up agent's model directive prefix and the meta to record.

    ``model_prefix`` is prepended to the generated follow-up prompt (e.g.
    ``"%model:codex/gpt-5.5\n"`` or ``"%model:@worker\n"``).  ``meta`` is the
    ``(provider_or_none, model)`` to write into the follow-up's
    ``agent_meta.json`` so the recorded model matches the directive; it is
    ``None`` when the inherited planner metadata is already correct and the
    rewrite should be skipped.
    """

    model_prefix: str
    meta: tuple[str | None, str] | None = None


def _resolve_model_meta(model_directive: str) -> tuple[str | None, str]:
    """Resolve a ``%model`` directive value to ``(provider_or_none, model)``."""
    from sase.llm_provider.registry import resolve_model_provider
    from sase.xprompt.effort import split_model_effort

    clean_model, _ = split_model_effort(model_directive)
    return resolve_model_provider(clean_model)


def _resolve_followup_model(
    plan_result: Any,
    ctx: AgentExecContext,
) -> _FollowupModel:
    """Decide the follow-up agent's ``%model`` prefix and recorded metadata.

    Precedence:

    1. An explicit approval picker model (``plan_result.coder_model``) other
       than the literal ``"worker"`` wins; its meta is recorded unless it
       equals the planner's model (the inherited meta is already correct).
    2. Otherwise — no picker model, or the picker chose ``"worker"`` — the
       worker lane is resolved from the planner's *concrete*
       provider/model (``ctx.agent_llm_provider``/``ctx.agent_model``) so the
       handoff preserves the planner's primary context rather than re-reading
       the current global worker lane later. The generated prefix is a
       concrete ``%model:<provider>/<model>``.
    3. If the planner is missing provider/model metadata, fall back to the
       ``%model:@worker`` alias, resolved from the current effective
       worker lane at launch time.

    A ``%model`` directive embedded in a custom coder prompt is handled by the
    caller and supersedes this result.
    """
    coder_model = plan_result.coder_model
    if coder_model and coder_model.strip() != "worker":
        prefix = f"%model:{format_model_directive_value(coder_model)}\n"
        if coder_model == ctx.agent_model:
            return _FollowupModel(model_prefix=prefix)
        return _FollowupModel(
            model_prefix=prefix, meta=_resolve_model_meta(coder_model)
        )

    primary_provider = (ctx.agent_llm_provider or "").strip()
    primary_model = (ctx.agent_model or "").strip()
    if primary_provider and primary_model:
        from sase.llm_provider import resolve_worker_provider_model_for_primary

        resolution = resolve_worker_provider_model_for_primary(
            primary_provider,
            primary_model,
        )
        return _FollowupModel(
            model_prefix=f"%model:{resolution.provider}/{resolution.model}\n",
            meta=(resolution.provider, resolution.model),
        )

    return _FollowupModel(
        model_prefix=f"%model:{format_model_directive_value('worker')}\n",
        meta=_resolve_model_meta("worker"),
    )


def _write_followup_model_meta(state: LoopState, followup: _FollowupModel) -> None:
    """Record the follow-up agent's resolved model in its ``agent_meta.json``."""
    if followup.meta is None:
        return
    resolved_provider, resolved_model = followup.meta
    update_meta_field(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update_meta_field(
            state.current_artifacts_dir, "llm_provider", resolved_provider
        )


def _write_followup_effort_meta(state: LoopState, followup_prompt: str) -> None:
    """Record the follow-up agent's resolved reasoning effort, when set."""
    from sase.llm_provider.config import resolve_effective_effort
    from sase.llm_provider.preprocessing import preprocess_prompt_early

    result = preprocess_prompt_early(followup_prompt)
    reasoning_effort, _ = resolve_effective_effort(result.directives)
    if reasoning_effort:
        update_meta_field(
            state.current_artifacts_dir, "reasoning_effort", reasoning_effort
        )


def _plan_followup_base_meta(base_meta: dict[str, Any]) -> dict[str, Any]:
    """Return parent metadata minus effort for accepted plan-chain handoffs.

    Accepted coder/epic/legend follow-ups resolve effort from their own final
    prompt. Dropping the inherited value here lets an unset follow-up omit
    ``reasoning_effort`` instead of accidentally displaying the planner's
    explicit effort.
    """
    if "reasoning_effort" not in base_meta:
        return base_meta
    return {key: value for key, value in base_meta.items() if key != "reasoning_effort"}


def handle_accepted_plan(
    plan_result: Any,
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Persist SDD files for an accepted plan and spawn its follow-up agent.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    update_meta_field(state.current_artifacts_dir, "plan_approved", True)
    update_meta_field(
        state.current_artifacts_dir,
        "plan_action",
        _accepted_plan_action_for_meta(plan_result),
    )
    source_plan_agent_name = agent_name_for_suffix(
        ctx, state.current_role_suffix or PLAN_CHAIN_PLAN_SUFFIX
    )

    # Write SDD files (spec + plan) to project
    from sase.sdd.beads import get_effective_sdd_config
    from sase.sdd.files import (
        commit_sdd_files,
        ensure_bare_git_sdd_initialized,
        expand_prompt_for_spec,
        get_sdd_dir,
        write_sdd_files,
    )

    sdd_plan_name: str | None = None
    sdd_plan_path: Path | None = None
    sdd_commit_paths: list[Path] = []
    version_controlled = True  # safe default (VC path is the no-op path)
    sdd_dir = Path(ctx.workspace_dir)
    try:
        version_controlled = get_effective_sdd_config(ctx.workspace_dir)
        sdd_dir = get_sdd_dir(ctx.workspace_dir, ctx.workspace_num, version_controlled)
        if version_controlled:
            ensure_bare_git_sdd_initialized(
                ctx.workspace_dir,
                commit=True,
                push=False,
            )
        sdd_plan_name = os.path.splitext(os.path.basename(plan_result.plan_file))[0]
        try:
            expanded = expand_prompt_for_spec(state.current_prompt)
        except Exception:
            logger.warning(
                "Spec prompt expansion failed, using raw prompt", exc_info=True
            )
            expanded = state.current_prompt
        plan_kind = plan_kind_for_action(plan_result.action)
        sdd_prompt_path_obj, sdd_plan_path = write_sdd_files(
            sdd_dir,
            sdd_plan_name,
            expanded,
            plan_result.plan_file,
            plan_kind=plan_kind,
        )
        sdd_commit_paths = [sdd_prompt_path_obj, sdd_plan_path]
        state.sdd_spec_path = str(sdd_prompt_path_obj)
        record_workflow_metadata(
            state.current_artifacts_dir,
            {
                "sdd_prompt_path": str(sdd_prompt_path_obj),
                "sdd_plan_path": str(sdd_plan_path),
            },
        )
        if not version_controlled:
            commit_sdd_files(
                sdd_dir,
                f"Add SDD files for {sdd_plan_name}",
                paths=sdd_commit_paths,
            )
    except Exception:
        logger.warning("SDD file generation failed", exc_info=True)

    # Unified SDD commit: epics always need committed files (the #gh
    # pre-step wipes uncommitted files); other actions respect commit_plan.
    should_commit = (
        plan_result.commit_plan
        if plan_result.action not in ("epic", "legend")
        else True
    )
    required_sdd_commit_succeeded = True
    if should_commit and sdd_plan_name:
        if version_controlled:
            plan_kind = plan_kind_for_action(plan_result.action)
            required_sdd_commit_succeeded = _commit_sdd_files(
                ctx.workspace_dir,
                sdd_plan_name,
                plan_kind=plan_kind,
            )
        else:
            commit_sdd_files(
                sdd_dir,
                f"Add SDD files for {sdd_plan_name}",
                paths=sdd_commit_paths,
            )
    elif should_commit:
        required_sdd_commit_succeeded = False
    plan_committed = bool(
        should_commit
        and sdd_plan_path is not None
        and sdd_plan_path.exists()
        and required_sdd_commit_succeeded
    )
    update_meta_field(state.current_artifacts_dir, "plan_committed", plan_committed)

    if not plan_result.run_coder and plan_result.action not in ("epic", "legend"):
        return "plan_committed"

    # VCS workflow tag prefix for follow-up agents
    vcs_prefix = ctx.vcs_tag or ""

    # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
    # #commit) to append after the main prompt so their post-steps
    # run after the follow-up agent.
    embedded_refs = get_embedded_workflow_refs(state.current_artifacts_dir, ctx.vcs_tag)

    # Decide the follow-up model: an explicit picker model wins; otherwise the
    # worker lane is resolved from the planner's concrete provider/model so the
    # handoff keeps the planner's primary context.
    followup_model = _resolve_followup_model(plan_result, ctx)
    model_prefix = followup_model.model_prefix
    followup_base_meta = _plan_followup_base_meta(ctx.agent_meta)

    if plan_result.action in ("epic", "legend"):
        # Ensure beads are initialized before spawning epic agent
        from sase.sdd.beads import ensure_beads_initialized

        ensure_beads_initialized(ctx.workspace_dir, ctx.workspace_num)
        legend_bead_id = (
            infer_epic_legend_bead_id(
                sdd_plan_path=sdd_plan_path,
                workspace_dir=ctx.workspace_dir,
                sdd_dir=sdd_dir,
            )
            if plan_result.action == "epic"
            else None
        )

        # Epic/legend: spawn a follow-up agent to create the container bead.
        state.current_role_suffix = (
            PLAN_CHAIN_EPIC_SUFFIX
            if plan_result.action == "epic"
            else PLAN_CHAIN_LEGEND_SUFFIX
        )
        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            followup_base_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=plan_chain_agent_name(
                ctx.agent_name, state.current_role_suffix
            )
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
            relationships={
                "plan_path": plan_result.plan_file,
                "sdd_prompt_path": str(state.sdd_spec_path)
                if state.sdd_spec_path
                else None,
                "sdd_plan_path": str(sdd_plan_path) if sdd_plan_path else None,
                "plan_committed": plan_committed,
                "legend_bead_id": (
                    legend_bead_id if plan_result.action == "epic" else None
                ),
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": source_plan_agent_name,
            },
        )
        update_meta_field(
            state.current_artifacts_dir,
            "epic_started_at" if plan_result.action == "epic" else "legend_started_at",
            datetime.now(UTC).isoformat(),
        )
        _write_followup_model_meta(state, followup_model)
        if plan_result.action == "epic":
            plan_ref = build_epic_plan_ref(
                sdd_plan_path=sdd_plan_path if plan_committed else None,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                sdd_plan_name=sdd_plan_name if plan_committed else None,
                version_controlled=version_controlled,
                fallback_plan_file=plan_result.plan_file,
            )
            legend_bead_id = infer_epic_legend_bead_id(
                sdd_plan_path=sdd_plan_path,
                workspace_dir=ctx.workspace_dir,
                sdd_dir=sdd_dir,
            )
            if legend_bead_id:
                plan_ref = f"{plan_ref},{legend_bead_id}"
            xprompt_name = "bd/new_epic"
        else:
            plan_ref = build_sdd_plan_ref(
                sdd_plan_path=sdd_plan_path if plan_committed else None,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                sdd_plan_name=sdd_plan_name if plan_committed else None,
                version_controlled=version_controlled,
                fallback_plan_file=plan_result.plan_file,
                plan_kind="legends",
            )
            xprompt_name = "bd/new_legend"
        state.current_prompt = (
            f"{model_prefix}{vcs_prefix}#{xprompt_name}:{plan_ref}\n{embedded_refs}"
        )
        _write_followup_effort_meta(state, state.current_prompt)
    else:
        # Approve: spawn coder with plan as prompt
        state.current_role_suffix = PLAN_CHAIN_CODER_SUFFIX

        # Point SASE_PLAN at the committed in-repo plan file only when the
        # approval committed that file. No-commit approvals must hand off the
        # archived plan because VCS workflow pre-steps may stash local SDD files.
        if plan_committed and sdd_plan_path:
            os.environ["SASE_PLAN"] = str(sdd_plan_path)
        else:
            os.environ["SASE_PLAN"] = plan_result.plan_file

        state.agent_step += 1
        if state.agent_step == 2 and ctx.agent_name:
            promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)
        state.current_artifacts_dir = create_followup_artifacts(
            ctx.project_name,
            followup_base_meta,
            state.current_role_suffix,
            convert_timestamp_to_artifacts_format(ctx.timestamp),
            workspace_num=ctx.workspace_num,
            agent_name_override=plan_chain_agent_name(
                ctx.agent_name,
                state.current_role_suffix,
            )
            if ctx.agent_name
            else None,
            workflow_name=ctx.agent_name,
            relationships={
                "plan_path": plan_result.plan_file,
                "sdd_prompt_path": str(state.sdd_spec_path)
                if state.sdd_spec_path
                else None,
                "sdd_plan_path": str(sdd_plan_path) if sdd_plan_path else None,
                "plan_committed": plan_committed,
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": source_plan_agent_name,
            },
        )
        coder_extra = ""
        if plan_result.coder_prompt:
            coder_extra = f"\n\nAdditional instructions:\n{plan_result.coder_prompt}"
            # If the custom prompt contains its own %model/%m directive,
            # skip the inherited model prefix to avoid a duplicate error and
            # record that directive's model in the follow-up meta below: it
            # is what the coder actually runs with.
            if model_prefix:
                from sase.xprompt._exceptions import DirectiveError
                from sase.xprompt.directives import (
                    extract_prompt_directives,
                    has_model_directive,
                )

                if has_model_directive(plan_result.coder_prompt):
                    coder_prompt_model = extract_prompt_directives(
                        plan_result.coder_prompt
                    )[1].model
                    if not coder_prompt_model:
                        raise DirectiveError(
                            "Custom coder prompt model directive requires a model"
                        )
                    model_prefix = ""
                    followup_model = _FollowupModel(
                        model_prefix="",
                        meta=_resolve_model_meta(coder_prompt_model),
                    )
        _write_followup_model_meta(state, followup_model)
        # By default the coder starts with a fresh context window; the plan
        # file itself is the hand-off artifact. Set SASE_CODER_INHERIT_PLANNER_CHAT=1
        # to prepend #fork:<base>--plan so the coder inherits the planner's
        # full chat transcript.
        resume_prefix = ""
        if ctx.agent_name and os.environ.get("SASE_CODER_INHERIT_PLANNER_CHAT") == "1":
            planner_name = plan_chain_agent_name(ctx.agent_name, PLAN_CHAIN_PLAN_SUFFIX)
            resume_prefix = f"#fork:{planner_name} "

        if plan_committed:
            coder_plan_ref = build_saved_plan_ref(
                sdd_plan_path=sdd_plan_path,
                sdd_dir=sdd_dir,
                workspace_dir=ctx.workspace_dir,
                version_controlled=version_controlled,
                fallback_plan_file=plan_result.plan_file,
            )
        else:
            coder_plan_ref = plan_result.plan_file

        state.current_prompt = (
            f"{model_prefix}{resume_prefix}{vcs_prefix}"
            f"@{coder_plan_ref}\n\n"
            "The above plan has been reviewed and approved. "
            f"Implement it now.{coder_extra}\n{embedded_refs}"
        )
        _write_followup_effort_meta(state, state.current_prompt)

    # A ``/sase_questions`` interruption from this follow-up phase must rebuild
    # from the exact code/epic/legend prompt (with its resolved ``%model``
    # directive), not the initial planner prompt.
    state.question_base_prompt = state.current_prompt
    return None  # continue loop
