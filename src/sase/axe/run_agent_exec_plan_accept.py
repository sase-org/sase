"""Accepted-plan follow-up handling for the agent execution loop."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_exec_plan import (
    agent_name_for_suffix,
    record_workflow_metadata,
)
from sase.axe.run_agent_exec_plan_accept_models import (
    FollowupModel as _FollowupModel,
    custom_coder_prompt_model as _custom_coder_prompt_model,
    plan_followup_base_meta as _plan_followup_base_meta,
    resolve_followup_model as _resolve_followup_model,
    resolve_model_alias_provenance as _resolve_model_alias_provenance,
    resolve_model_meta as _resolve_model_meta,
)

# Re-exported so successor model-meta writers honor accept-module test doubles.
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_successor import (
    SuccessorRequest,
    continue_as_successor,
    write_followup_model_meta as _write_followup_model_meta,
)
from sase.axe.run_agent_exec_plan_accept_sdd import (
    accepted_plan_action_for_meta as _accepted_plan_action_for_meta,
    epic_launch_is_host_owned as _epic_launch_is_host_owned,
    notify_epic_launch_failure as _notify_epic_launch_failure,
    publish_planner_prompt_archive as _publish_planner_prompt_archive,
    record_epic_store_failure,
    require_usable_sdd_store as _require_usable_sdd_store,
    store_failure_detail as _store_failure_detail,
)
from sase.axe.run_agent_exec_plan_artifacts import (
    get_embedded_workflow_refs,
    store_followup_prompt_artifact,
)
from sase.axe.run_agent_exec_plan_sdd import (
    build_saved_plan_ref,
    commit_sdd_files_for_exec_plan,
    plan_tier_for_action,
)
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
)

# Re-exported so successor model-meta writers honor accept-module test doubles.
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)

_store_followup_prompt_artifact = store_followup_prompt_artifact


def _commit_sdd_files(
    workspace_dir: str, plan_name: str, *, plan_tier: str = "tale"
) -> bool:
    return commit_sdd_files_for_exec_plan(
        workspace_dir,
        plan_name,
        plan_tier=plan_tier,
        logger=logger,
        subprocess_run=subprocess.run,
    )


def _write_followup_effort_meta(state: LoopState, followup_prompt: str) -> None:
    """Record the follow-up agent's resolved reasoning effort, when set."""
    from sase.llm_provider.config import resolve_effective_effort
    from sase.llm_provider.preprocessing import preprocess_prompt_early
    from sase.llm_provider.registry import resolve_model_provider_with_effort

    result = preprocess_prompt_early(followup_prompt)
    alias_effort: str | None = None
    if result.directives.model:
        _, _, alias_effort = resolve_model_provider_with_effort(
            result.directives.model,
            result.directives.model_alias_overrides,
        )
    reasoning_effort, _ = resolve_effective_effort(result.directives, alias_effort)
    if reasoning_effort:
        update_meta_field(
            state.current_artifacts_dir, "reasoning_effort", reasoning_effort
        )


def _record_epic_store_failure(
    plan_result: Any,
    ctx: AgentExecContext,
    state: LoopState,
    store_unusable_error: str,
) -> str | None:
    return record_epic_store_failure(
        plan_result,
        ctx,
        state,
        store_unusable_error,
        update_meta=update_meta_field,
        notify_failure=_notify_epic_launch_failure,
        log=logger,
    )


def handle_accepted_plan(
    plan_result: Any,
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Persist SDD files for an accepted plan and spawn its follow-up agent.

    Returns a loop-outcome string to break the loop, or ``None`` to continue.
    """
    if plan_result.action == "epic":
        from sase.plan_approval_actions import require_plan_approval_validation

        require_plan_approval_validation(plan_result.plan_file, "epic")

    update_meta_field(state.current_artifacts_dir, "plan_approved", True)
    update_meta_field(
        state.current_artifacts_dir,
        "plan_action",
        _accepted_plan_action_for_meta(plan_result),
    )
    source_plan_agent_name = agent_name_for_suffix(
        ctx, state.current_role_suffix or PLAN_CHAIN_PLAN_SUFFIX
    )

    # The planner always owns its prompt archive entry. For epics, the canonical
    # ``sase bead work`` command exclusively owns the plan file itself.
    from sase.sdd.files import (
        commit_sdd_store_files,
        ensure_bare_git_sdd_initialized,
        expand_prompt_for_spec,
        get_yyyymm,
        write_sdd_files,
        write_sdd_spec,
    )
    from sase.sdd.store import materialize_sdd_store

    is_epic = plan_result.action == "epic"
    raw_saved_plan = getattr(plan_result, "saved_plan_path", None)
    published_plan_path = (
        Path(raw_saved_plan)
        if isinstance(raw_saved_plan, str) and raw_saved_plan.strip()
        else None
    )
    sdd_store: Any | None = None
    sdd_plan_name: str | None = None
    sdd_plan_path: Path | None = None
    sdd_prompt_path_obj: Path | None = None
    sdd_commit_paths: list[Path] = []
    sdd_in_tree = True  # safe default (in-tree path is the no-op path)
    sdd_sidecar_storage = False
    sdd_dir = Path(ctx.workspace_dir)
    store_unusable_error: str | None = None
    try:
        sdd_store = materialize_sdd_store(ctx.workspace_dir, ctx.workspace_num)
        _require_usable_sdd_store(sdd_store.repo_root)
        sdd_in_tree = sdd_store.is_in_tree
        sdd_sidecar_storage = sdd_store.is_sidecar_storage
        sdd_dir = sdd_store.sdd_dir
        if sdd_in_tree:
            ensure_bare_git_sdd_initialized(
                ctx.workspace_dir,
                commit=True,
                push=False,
            )
        sdd_plan_name = os.path.splitext(os.path.basename(plan_result.plan_file))[0]
        archive_month = get_yyyymm()
        try:
            expanded = expand_prompt_for_spec(state.current_prompt)
        except Exception:
            logger.warning(
                "Spec prompt expansion failed, using raw prompt", exc_info=True
            )
            expanded = state.current_prompt
        if source_plan_agent_name is not None:
            sdd_prompt_path_obj = _publish_planner_prompt_archive(
                ctx,
                state,
                agent_name=source_plan_agent_name,
                prompt_content=expanded,
                plan_name=sdd_plan_name,
                yyyymm=archive_month,
            )
        else:
            logger.warning(
                "Planner prompt archive publication skipped: agent name unavailable"
            )
        if is_epic:
            sdd_prompt_path_obj, sdd_plan_path = write_sdd_spec(
                sdd_dir,
                sdd_plan_name,
                expanded,
                plans_root=sdd_store.kind_root("plans"),
                prompt_path=sdd_prompt_path_obj,
                yyyymm=archive_month,
            )
        elif published_plan_path is not None:
            # Approval already published the canonical tale plan. Consume that
            # path instead of writing and committing a second copy.
            sdd_plan_path = published_plan_path
        else:
            plan_tier = plan_tier_for_action(plan_result.action)
            sdd_prompt_path_obj, sdd_plan_path = write_sdd_files(
                sdd_dir,
                sdd_plan_name,
                expanded,
                plan_result.plan_file,
                plan_tier=plan_tier,
                plans_root=sdd_store.kind_root("plans"),
                store=sdd_store,
                prompt_path=sdd_prompt_path_obj,
                yyyymm=archive_month,
            )
            sdd_commit_paths = [sdd_plan_path]
        state.sdd_spec_path = (
            str(sdd_prompt_path_obj) if sdd_prompt_path_obj is not None else None
        )
        record_workflow_metadata(
            state.current_artifacts_dir,
            {
                "sdd_prompt_path": (
                    str(sdd_prompt_path_obj)
                    if sdd_prompt_path_obj is not None
                    else None
                ),
                "sdd_plan_path": str(sdd_plan_path),
            },
        )
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if is_epic and isinstance(
            exc, (SddMaterializationError, SddRepositoryHealthError)
        ):
            store_unusable_error = _store_failure_detail(exc)
            logger.error(
                "Approved epic SDD publication failed: %s", store_unusable_error
            )
        else:
            logger.warning("SDD file generation failed", exc_info=True)

    if is_epic and store_unusable_error is not None:
        outcome = _record_epic_store_failure(
            plan_result, ctx, state, store_unusable_error
        )
        if outcome is not None:
            return outcome
        # Host-owned: degraded, not failed. Every block between here and the
        # epic return is ``not is_epic``-gated, so the unset ``sdd_store`` /
        # ``sdd_plan_path`` are never dereferenced on the way out.
        store_unusable_error = None

    # Planner prompts are committed by the agents-sidecar archive publisher.
    # Tale plans already published at approval time must not get a second
    # "Add SDD files" commit from this runner.
    should_commit = plan_result.commit_plan if not is_epic else True
    required_sdd_commit_succeeded = True
    try:
        if (
            should_commit
            and sdd_plan_name
            and not is_epic
            and published_plan_path is None
        ):
            if sdd_in_tree:
                required_sdd_commit_succeeded = _commit_sdd_files(
                    ctx.workspace_dir,
                    sdd_plan_name,
                    plan_tier=plan_tier_for_action(plan_result.action),
                )
            elif sdd_store is not None:
                required_sdd_commit_succeeded = bool(
                    commit_sdd_store_files(
                        sdd_store,
                        (
                            f"Add SDD prompt for {sdd_plan_name}"
                            if is_epic
                            else f"Add SDD files for {sdd_plan_name}"
                        ),
                        paths=sdd_commit_paths,
                        push_after_commit=True,
                    )
                )
            else:
                required_sdd_commit_succeeded = False
        elif should_commit and not is_epic and published_plan_path is None:
            required_sdd_commit_succeeded = False
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if is_epic and isinstance(
            exc, (SddMaterializationError, SddRepositoryHealthError)
        ):
            store_unusable_error = _store_failure_detail(exc)
            required_sdd_commit_succeeded = False
        else:
            raise

    if is_epic and store_unusable_error is not None:
        outcome = _record_epic_store_failure(
            plan_result, ctx, state, store_unusable_error
        )
        if outcome is not None:
            return outcome
        store_unusable_error = None
    plan_committed = bool(
        not is_epic
        and sdd_plan_path is not None
        and sdd_plan_path.exists()
        and (
            published_plan_path is not None
            or (should_commit and required_sdd_commit_succeeded)
        )
    )
    if not is_epic:
        update_meta_field(state.current_artifacts_dir, "plan_committed", plan_committed)

    if not plan_result.run_coder and plan_result.action != "epic":
        return "plan_committed"

    if plan_result.action == "epic":
        if not required_sdd_commit_succeeded:
            logger.warning(
                "Approved epic prompt archive entry could not be committed; "
                "the host-owned epic launch continues independently"
            )
        return "epic_approved"

    # VCS workflow tag prefix for coder follow-up agents
    vcs_prefix = ctx.vcs_tag or ""

    # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
    # #commit) to append after the main prompt so their post-steps
    # run after the follow-up agent.
    embedded_refs = get_embedded_workflow_refs(state.current_artifacts_dir, ctx.vcs_tag)

    followup_plan_file = (
        sdd_plan_path
        if plan_committed and sdd_plan_path
        else Path(plan_result.plan_file)
    )
    custom_prompt_model = _custom_coder_prompt_model(plan_result.coder_prompt)
    if custom_prompt_model is not None:
        custom_model, custom_model_alias = custom_prompt_model
        custom_model_alias_trail, custom_model_alias_origin = (
            _resolve_model_alias_provenance(custom_model)
        )
        followup_model = _FollowupModel(
            model_prefix="",
            meta=_resolve_model_meta(custom_model),
            model_alias=custom_model_alias,
            model_alias_trail=custom_model_alias_trail,
            model_alias_origin=custom_model_alias_origin,
        )
    else:
        # Decide the coder follow-up model: an explicit picker model wins; otherwise
        # route through the handoff tale's size-derived phase-worker alias.
        followup_model = _resolve_followup_model(
            plan_result,
            ctx,
            followup_plan_file=followup_plan_file,
        )
    model_prefix = followup_model.model_prefix
    followup_base_meta = _plan_followup_base_meta(ctx.agent_meta)

    # Point SASE_PLAN at the committed in-repo plan file only when the approval
    # committed that file. No-commit approvals must hand off the archived plan
    # because VCS workflow pre-steps may stash local SDD files.
    if plan_committed and sdd_plan_path:
        os.environ["SASE_PLAN"] = str(sdd_plan_path)
    else:
        os.environ["SASE_PLAN"] = plan_result.plan_file

    coder_extra = ""
    if plan_result.coder_prompt:
        coder_extra = f"\n\nAdditional instructions:\n{plan_result.coder_prompt}"

    if plan_committed:
        coder_plan_ref = build_saved_plan_ref(
            sdd_plan_path=sdd_plan_path,
            sdd_dir=sdd_dir,
            workspace_dir=ctx.workspace_dir,
            sdd_in_tree=sdd_in_tree,
            sdd_sidecar_storage=sdd_sidecar_storage,
            fallback_plan_file=plan_result.plan_file,
        )
    else:
        coder_plan_ref = plan_result.plan_file

    # The coder starts with a fresh context window; the approved plan file is
    # the hand-off artifact. It does not inherit the planner's chat.
    continue_as_successor(
        ctx,
        state,
        SuccessorRequest(
            base_meta=followup_base_meta,
            prompt=(
                f"{model_prefix}{vcs_prefix}"
                f"@{coder_plan_ref}\n\n"
                "The above plan has been reviewed and approved. "
                f"Implement it now.{coder_extra}\n{embedded_refs}"
            ),
            suffix=PLAN_CHAIN_CODER_SUFFIX,
            relationships={
                "plan_path": plan_result.plan_file,
                "sdd_prompt_path": str(state.sdd_spec_path)
                if state.sdd_spec_path
                else None,
                "sdd_plan_path": str(sdd_plan_path) if sdd_plan_path else None,
                "plan_committed": plan_committed,
                "patch_name": ctx.cl_name,
                "changespec_name": ctx.cl_name,
                "source_plan_agent_name": source_plan_agent_name,
            },
            prompt_artifact_label="Full coder prompt",
            model=followup_model,
        ),
        create_artifacts=create_followup_artifacts,
        promote=promote_to_workflow,
        store_prompt=_store_followup_prompt_artifact,
        write_model_meta=_write_followup_model_meta,
    )
    _write_followup_effort_meta(state, state.current_prompt)

    # A ``/sase_questions`` interruption from this follow-up phase must rebuild
    # from the exact code prompt (with its resolved ``%model`` directive), not
    # the initial planner prompt.
    state.question_base_prompt = state.current_prompt
    return None  # continue loop
