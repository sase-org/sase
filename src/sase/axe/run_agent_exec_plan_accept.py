"""Accepted-plan follow-up handling for the agent execution loop."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.bead.epic_launch import build_epic_launch_argv
from sase.axe.run_agent_exec_plan import (
    agent_name_for_suffix,
    record_workflow_metadata,
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
from sase.llm_provider.config import (
    CODER_MODEL_ALIAS_NAME,
    coder_model_alias_for_provider,
    format_model_directive_value,
    role_model_directive_value,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

logger = logging.getLogger(__name__)

_EPIC_ID_LINE = re.compile(r"^Epic:\s+(\S+)\s*$")
_EPIC_OUTPUT_TAIL_LINES = 40
_store_followup_prompt_artifact = store_followup_prompt_artifact


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
    workspace_dir: str, plan_name: str, *, plan_tier: str = "tale"
) -> bool:
    return commit_sdd_files_for_exec_plan(
        workspace_dir,
        plan_name,
        plan_tier=plan_tier,
        logger=logger,
        subprocess_run=subprocess.run,
    )


def _commit_sdd_spec(workspace_dir: str, plan_name: str) -> bool:
    """Commit only the planner-owned prompt snapshot for an epic."""
    return commit_sdd_files_for_exec_plan(
        workspace_dir,
        plan_name,
        plan_tier="epic",
        include_plan=False,
        logger=logger,
        subprocess_run=subprocess.run,
    )


@dataclass(frozen=True)
class _FollowupModel:
    """The follow-up agent's model directive prefix and the meta to record.

    ``model_prefix`` is prepended to the generated follow-up prompt (e.g.
    ``"%model:codex/gpt-5.6-sol\n"`` or ``"%model:@claude_coder\n"``).  ``meta`` is
    the ``(provider_or_none, model)`` to write into the follow-up's
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


def _resolve_coder_alias_followup(ctx: AgentExecContext) -> _FollowupModel:
    """Route a coder follow-up through the planner provider's coder alias.

    Emits ``%model:@<planner_provider>_coder`` when the planner recorded its
    provider (e.g. ``%model:@claude_coder`` for a Claude-authored plan, or
    ``%model:@codex_coder`` for a Codex one), and the generic ``%model:@coder``
    when planner provider metadata is missing. The recorded meta resolves the
    alias chain to the concrete ``(provider, model)`` the launch will actually
    use so display and behavior stay in sync.
    """
    planner_provider = (ctx.agent_llm_provider or "").strip()
    alias = (
        coder_model_alias_for_provider(planner_provider)
        if planner_provider
        else CODER_MODEL_ALIAS_NAME
    )
    directive = role_model_directive_value(alias)
    return _FollowupModel(
        model_prefix=f"%model:{directive}\n",
        meta=_resolve_model_meta(directive),
    )


def _resolve_followup_model(
    plan_result: Any,
    ctx: AgentExecContext,
) -> _FollowupModel:
    """Decide the follow-up agent's ``%model`` prefix and recorded metadata.

    Precedence:

    1. An explicit approval picker model (``plan_result.coder_model``) other
       than the legacy ``"worker"`` sentinel wins; its meta is recorded unless
       it equals the planner's model (the inherited meta is already correct).
    2. Otherwise coder follow-ups (``approve`` / ``tale``) route through the
       planner provider's coder alias (``%model:@<planner_provider>_coder``, or
       ``%model:@coder`` when planner provider metadata is missing).

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

    return _resolve_coder_alias_followup(ctx)


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


def _plan_followup_base_meta(base_meta: dict[str, Any]) -> dict[str, Any]:
    """Return parent metadata minus effort for accepted plan-chain handoffs.

    Accepted coder follow-ups resolve effort from their own final prompt.
    Dropping the inherited value here lets an unset follow-up omit
    ``reasoning_effort`` instead of accidentally displaying the planner's
    explicit effort.
    """
    if "reasoning_effort" not in base_meta:
        return base_meta
    return {key: value for key, value in base_meta.items() if key != "reasoning_effort"}


@dataclass(frozen=True)
class _EpicLaunchResult:
    returncode: int
    epic_bead_id: str | None
    output_tail: tuple[str, ...]


def _run_epic_launch_subprocess(
    *,
    workspace_dir: str,
    plan_file: str,
) -> _EpicLaunchResult:
    """Stream the canonical epic command and parse its stable epic-id line."""
    argv = build_epic_launch_argv(plan_file)
    tail: deque[str] = deque(maxlen=_EPIC_OUTPUT_TAIL_LINES)
    epic_bead_id: str | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        message = f"{type(exc).__name__}: {exc}"
        return _EpicLaunchResult(-1, None, (message,))

    if process.stdout is not None:
        for raw_line in process.stdout:
            print(raw_line, end="", flush=True)
            line = raw_line.rstrip("\r\n")
            tail.append(line)
            match = _EPIC_ID_LINE.fullmatch(line)
            if match is not None:
                epic_bead_id = match.group(1)
    returncode = process.wait()
    if returncode == 0 and epic_bead_id is None:
        tail.append("epic launch completed without the required 'Epic: <id>' line")
        returncode = 1
    return _EpicLaunchResult(returncode, epic_bead_id, tuple(tail))


def _notify_epic_launch_failure(
    ctx: AgentExecContext,
    plan_file: str,
    output_tail: tuple[str, ...],
) -> None:
    """Best-effort error notification with a direct resume command."""
    argv = build_epic_launch_argv(plan_file)
    resume_command = shlex.join(argv)
    notes = [
        f"Epic launch failed for {Path(plan_file).name}",
        f"Resume with: {resume_command}",
    ]
    if output_tail:
        notes.append(f"Last output: {output_tail[-1]}")
    try:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="user-agent",
            cl_name=ctx.cl_name,
            success=False,
            notes=notes,
            action="ViewErrorReport",
            action_data={
                "error_report_path": ctx.output_path,
                "cl_name": ctx.cl_name,
                **({"agent_name": ctx.agent_name} if ctx.agent_name else {}),
            },
            extra_files=[ctx.output_path] if Path(ctx.output_path).is_file() else None,
        )
    except Exception:
        logger.warning("Failed to send epic-launch error notification", exc_info=True)


def _require_usable_sdd_store(repo_root: Path) -> None:
    """Validate a materialized SDD repository before any accepted-plan write."""
    if not (repo_root / ".git").exists():
        return
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    with store_git_write_lock(repo_root) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root.resolve()} could not acquire its store "
                "write lock; the approved plan was not copied"
            )
        require_sdd_repository_health(repo_root)


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

    # The planner always owns its prompt snapshot. For epics, the canonical
    # ``sase bead work`` command exclusively owns the plan file itself.
    from sase.sdd.files import (
        commit_sdd_store_files,
        ensure_bare_git_sdd_initialized,
        expand_prompt_for_spec,
        write_sdd_files,
        write_sdd_spec,
    )
    from sase.sdd.store import materialize_sdd_store

    is_epic = plan_result.action == "epic"
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
        try:
            expanded = expand_prompt_for_spec(state.current_prompt)
        except Exception:
            logger.warning(
                "Spec prompt expansion failed, using raw prompt", exc_info=True
            )
            expanded = state.current_prompt
        if is_epic:
            sdd_prompt_path_obj, sdd_plan_path = write_sdd_spec(
                sdd_dir,
                sdd_plan_name,
                expanded,
                plans_root=sdd_store.kind_root("plans"),
            )
            sdd_commit_paths = [sdd_prompt_path_obj]
        else:
            plan_tier = plan_tier_for_action(plan_result.action)
            sdd_prompt_path_obj, sdd_plan_path = write_sdd_files(
                sdd_dir,
                sdd_plan_name,
                expanded,
                plan_result.plan_file,
                plan_tier=plan_tier,
                plans_root=sdd_store.kind_root("plans"),
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
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if is_epic and isinstance(
            exc, (SddMaterializationError, SddRepositoryHealthError)
        ):
            store_unusable_error = str(exc) or type(exc).__name__
            logger.error("Approved epic SDD store is unusable: %s", exc)
        else:
            logger.warning("SDD file generation failed", exc_info=True)

    if is_epic and store_unusable_error is not None:
        update_meta_field(
            state.current_artifacts_dir,
            "epic_launch_error",
            store_unusable_error,
        )
        _notify_epic_launch_failure(
            ctx,
            plan_result.plan_file,
            (store_unusable_error,),
        )
        return "epic_launch_failed"

    # Epic prompt snapshots are committed independently so they cannot race
    # the host command's plan archive/link commits.
    should_commit = plan_result.commit_plan if not is_epic else True
    required_sdd_commit_succeeded = True
    try:
        if should_commit and sdd_plan_name and sdd_prompt_path_obj is not None:
            if sdd_in_tree:
                required_sdd_commit_succeeded = (
                    _commit_sdd_spec(ctx.workspace_dir, sdd_plan_name)
                    if is_epic
                    else _commit_sdd_files(
                        ctx.workspace_dir,
                        sdd_plan_name,
                        plan_tier=plan_tier_for_action(plan_result.action),
                    )
                )
            elif sdd_store is not None:
                required_sdd_commit_succeeded = commit_sdd_store_files(
                    sdd_store,
                    (
                        f"Add SDD prompt for {sdd_plan_name}"
                        if is_epic
                        else f"Add SDD files for {sdd_plan_name}"
                    ),
                    paths=sdd_commit_paths,
                    push_after_commit=True,
                )
            else:
                required_sdd_commit_succeeded = False
        elif should_commit:
            required_sdd_commit_succeeded = False
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if is_epic and isinstance(
            exc, (SddMaterializationError, SddRepositoryHealthError)
        ):
            store_unusable_error = str(exc) or type(exc).__name__
            required_sdd_commit_succeeded = False
        else:
            raise

    if is_epic and store_unusable_error is not None:
        update_meta_field(
            state.current_artifacts_dir,
            "epic_launch_error",
            store_unusable_error,
        )
        _notify_epic_launch_failure(
            ctx,
            plan_result.plan_file,
            (store_unusable_error,),
        )
        return "epic_launch_failed"
    plan_committed = bool(
        not is_epic
        and should_commit
        and sdd_plan_path is not None
        and sdd_plan_path.exists()
        and required_sdd_commit_succeeded
    )
    if not is_epic:
        update_meta_field(state.current_artifacts_dir, "plan_committed", plan_committed)

    if not plan_result.run_coder and plan_result.action != "epic":
        return "plan_committed"

    if plan_result.action == "epic":
        if not required_sdd_commit_succeeded:
            logger.warning(
                "Approved epic prompt snapshot could not be committed; "
                "continuing with the canonical plan launch"
            )

        if getattr(plan_result, "epic_launch_owner", None) == "host":
            return "epic_approved"

        launch_result = _run_epic_launch_subprocess(
            workspace_dir=ctx.workspace_dir,
            plan_file=plan_result.plan_file,
        )
        if launch_result.returncode == 0 and launch_result.epic_bead_id is not None:
            update_meta_field(state.current_artifacts_dir, "plan_committed", True)
            update_meta_field(
                state.current_artifacts_dir,
                "epic_started_at",
                datetime.now(UTC).isoformat(),
            )
            update_meta_field(
                state.current_artifacts_dir,
                "epic_bead_id",
                launch_result.epic_bead_id,
            )
            return "epic_approved"

        tail_text = "\n".join(launch_result.output_tail) or "(no output)"
        logger.error(
            "Epic launch failed with exit code %d. Output tail:\n%s",
            launch_result.returncode,
            tail_text,
        )
        update_meta_field(
            state.current_artifacts_dir,
            "epic_launch_error",
            launch_result.output_tail[-1]
            if launch_result.output_tail
            else f"exit code {launch_result.returncode}",
        )
        _notify_epic_launch_failure(
            ctx, plan_result.plan_file, launch_result.output_tail
        )
        return "epic_launch_failed"

    # VCS workflow tag prefix for coder follow-up agents
    vcs_prefix = ctx.vcs_tag or ""

    # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
    # #commit) to append after the main prompt so their post-steps
    # run after the follow-up agent.
    embedded_refs = get_embedded_workflow_refs(state.current_artifacts_dir, ctx.vcs_tag)

    # Decide the coder follow-up model: an explicit picker model wins; otherwise
    # route through the planner provider's coder alias (``@<provider>_coder``).
    followup_model = _resolve_followup_model(plan_result, ctx)
    model_prefix = followup_model.model_prefix
    followup_base_meta = _plan_followup_base_meta(ctx.agent_meta)

    # Approve: spawn coder with plan as prompt
    state.current_role_suffix = PLAN_CHAIN_CODER_SUFFIX

    # Point SASE_PLAN at the committed in-repo plan file only when the approval
    # committed that file. No-commit approvals must hand off the archived plan
    # because VCS workflow pre-steps may stash local SDD files.
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
        # If the custom prompt contains its own %model/%m directive, skip the
        # inherited model prefix to avoid a duplicate error and record that
        # directive's model in the follow-up meta below: it is what the coder
        # actually runs with.
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
    # By default the coder starts with a fresh context window; the plan file
    # itself is the hand-off artifact. Set SASE_CODER_INHERIT_PLANNER_CHAT=1 to
    # prepend #fork:<base>--plan so the coder inherits the planner's full chat.
    resume_prefix = ""
    if ctx.agent_name and os.environ.get("SASE_CODER_INHERIT_PLANNER_CHAT") == "1":
        planner_name = plan_chain_agent_name(ctx.agent_name, PLAN_CHAIN_PLAN_SUFFIX)
        resume_prefix = f"#fork:{planner_name} "

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

    state.current_prompt = (
        f"{model_prefix}{resume_prefix}{vcs_prefix}"
        f"@{coder_plan_ref}\n\n"
        "The above plan has been reviewed and approved. "
        f"Implement it now.{coder_extra}\n{embedded_refs}"
    )
    _write_followup_effort_meta(state, state.current_prompt)
    _store_followup_prompt_artifact(
        state.current_artifacts_dir,
        state.current_prompt,
        label="Full coder prompt",
    )

    # A ``/sase_questions`` interruption from this follow-up phase must rebuild
    # from the exact code prompt (with its resolved ``%model`` directive), not
    # the initial planner prompt.
    state.question_base_prompt = state.current_prompt
    return None  # continue loop
