"""Post-admission launch phase for ``run_agent_runner``.

Runs once the agent has cleared dependency and runner-slot admission: claims
the real workspace, prepares repos and markers, then drives the execution loop
in ``axe.run_agent_exec``.
"""

from __future__ import annotations

import os
from typing import Any

from sase.axe.clan_summary_script import (
    POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
    resolve_clan_summary_script,
)
from sase.axe.run_agent_directive_metadata import (
    epic_work_environment_from_metadata,
)
from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_phases import (
    claim_deferred_workspace,
    persist_refreshed_clan_summary,
    resolve_agent_refs_in_prompt,
    resolve_wait_chat_paths,
)
from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.axe.run_agent_runner_bootstrap import RunnerBootstrap
from sase.axe.run_agent_runner_finalize import classify_exec_success
from sase.axe.run_agent_runner_setup import (
    build_output_variable_namespaces,
    capture_sdd_base_sha,
    prepare_linked_repo_workspaces_if_needed,
    prepare_workspace_if_needed,
    refresh_linked_repos_for_workspace,
    write_agent_meta,
    write_home_running_marker,
)
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.axe.source_skew import preload_post_gate_modules
from sase.bead.claims import clear_bead_claim_marker
from sase.dev_update.code_swap_lock import code_swap_advisory_reader_lock
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_FILE_ENV


def _prepare_workspace_and_repos(
    state: RunnerRunState,
    bootstrap: RunnerBootstrap,
) -> None:
    """Claim the real workspace (if deferred) and materialize its repos."""
    deferred = bootstrap.deferred_workspace and not state.is_home_mode
    if deferred:
        state.workspace_num, state.workspace_dir = claim_deferred_workspace(
            state.project_file,
            state.project_name,
            state.workflow_name,
            state.cl_name,
            state.artifacts_timestamp,
        )

    fresh_sidecar_paths = prepare_workspace_if_needed(
        workspace_dir=state.workspace_dir,
        workspace_num=state.workspace_num,
        cl_name=state.cl_name,
        update_target=state.update_target,
        project_name=state.project_name,
        is_home_mode=state.is_home_mode,
        retry_handoff=bootstrap.retry_handoff,
    )

    # A deferred claim always rebinds linked repos to the workspace it just
    # took; a direct claim only needs the refresh when it is about to prepare
    # sidecar workspaces for an update target.
    prepares_sidecars = bool(state.update_target) and bootstrap.retry_handoff is None
    needs_refresh = deferred or (prepares_sidecars and not state.is_home_mode)
    if not needs_refresh:
        return

    linked_repo_resolution = refresh_linked_repos_for_workspace(
        project_file=state.project_file,
        workspace_dir=state.workspace_dir,
        workspace_num=state.workspace_num,
        artifacts_dir=state.artifacts_dir,
        agent_meta=bootstrap.agent_meta,
    )
    if prepares_sidecars:
        prepare_linked_repo_workspaces_if_needed(
            resolution=linked_repo_resolution,
            cl_name=state.cl_name,
            fresh_sidecar_paths=fresh_sidecar_paths,
        )


def _refresh_clan_summary(
    state: RunnerRunState,
    bootstrap: RunnerBootstrap,
) -> None:
    """Re-resolve the clan summary now that the workspace is prepared."""
    resolution = bootstrap.info.clan_summary_resolution
    if resolution is None:
        return

    summary_environment = {
        **os.environ,
        **epic_work_environment_from_metadata(bootstrap.agent_meta),
    }
    refreshed_clan_summary = resolve_clan_summary_script(
        resolution.script,
        workspace_dir=state.workspace_dir,
        clan_name=resolution.clan_name,
        clan_generation=resolution.clan_generation,
        clan_tribe=resolution.clan_tribe,
        agent_log_path=state.output_path,
        artifacts_dir=state.artifacts_dir,
        attempt_label=POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
        environment=summary_environment,
    )
    if refreshed_clan_summary:
        persist_refreshed_clan_summary(
            state.artifacts_dir,
            bootstrap.agent_meta,
            refreshed_clan_summary,
        )


def _promote_bead_claim(
    state: RunnerRunState,
    bootstrap: RunnerBootstrap,
) -> None:
    """Promote this run's bead from a waiting claim to a launched claim."""
    bead_id = bootstrap.info.bead_id
    if bead_id is None:
        return
    if state.agent_name is None:
        raise RuntimeError(
            f"Cannot claim bead '{bead_id}' without a resolved agent name"
        )
    if bootstrap.force_reuse_bead_association is None:
        claim_bead_for_agent_launch(
            agent_name=state.agent_name,
            bead_id=bead_id,
            workspace_dir=state.workspace_dir,
            workspace_num=state.workspace_num,
            artifacts_dir=state.artifacts_dir,
        )
    else:
        claim_bead_for_agent_launch(
            agent_name=state.agent_name,
            bead_id=bead_id,
            workspace_dir=state.workspace_dir,
            workspace_num=state.workspace_num,
            artifacts_dir=state.artifacts_dir,
            force_reuse_prior_owner=(bootstrap.force_reuse_bead_association.owner_name),
        )
    bootstrap.agent_meta["bead_claim_promoted"] = True
    write_agent_meta(state.artifacts_dir, bootstrap.agent_meta)
    clear_bead_claim_marker(state.artifacts_dir)
    state.held_bead_claim = None


def _build_exec_context(
    state: RunnerRunState,
    bootstrap: RunnerBootstrap,
    *,
    vcs_tag: str | None,
    wait_chats: list[str],
    output_variable_namespaces: dict[str, Any],
) -> AgentExecContext:
    return AgentExecContext(
        cl_name=state.cl_name,
        project_file=state.project_file,
        workspace_dir=state.workspace_dir,
        output_path=state.output_path,
        workspace_num=state.workspace_num,
        timestamp=state.timestamp,
        update_target=state.update_target,
        project_name=state.project_name,
        is_home_mode=state.is_home_mode,
        artifacts_dir=state.artifacts_dir,
        artifacts_timestamp=state.artifacts_timestamp,
        vcs_tag=vcs_tag,
        agent_name=state.agent_name,
        agent_model=state.agent_model,
        agent_llm_provider=state.agent_llm_provider,
        agent_vcs_provider=state.agent_vcs_provider,
        agent_hidden=state.agent_hidden,
        agent_meta=bootstrap.agent_meta,
        local_xprompts=bootstrap.info.local_xprompts,
        multi_agent_prompt_file=os.environ.get(MULTI_AGENT_PROMPT_FILE_ENV),
        wait_chats=wait_chats,
        output_variable_namespaces=output_variable_namespaces,
    )


def launch_agent_run(state: RunnerRunState, bootstrap: RunnerBootstrap) -> None:
    """Prepare the claimed workspace and run the agent execution loop."""
    info = bootstrap.info
    _prepare_workspace_and_repos(state, bootstrap)
    _refresh_clan_summary(state, bootstrap)

    if state.is_home_mode:
        state.running_marker_path = write_home_running_marker(
            artifacts_dir=state.artifacts_dir,
            cl_name=state.cl_name,
            timestamp=state.timestamp,
            prompt=state.prompt,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            agent_vcs_provider=state.agent_vcs_provider,
            workspace_dir=state.workspace_dir,
        )

    wait_chats: list[str] = []
    if bootstrap.has_dependency_wait and info.wait_names:
        wait_chats = resolve_wait_chat_paths(info.wait_names)

    state.prompt, vcs_tag = resolve_agent_refs_in_prompt(state.prompt)

    if info.approve:
        os.environ["SASE_AGENT_AUTO_APPROVE"] = "1"

    output_variable_namespaces = build_output_variable_namespaces(info.wait_names)

    _promote_bead_claim(state, bootstrap)

    sdd_base_sha = capture_sdd_base_sha(state.workspace_dir, state.workspace_num)
    if sdd_base_sha:
        bootstrap.agent_meta["sdd_base_sha"] = sdd_base_sha
        write_agent_meta(state.artifacts_dir, bootstrap.agent_meta)

    # Everything the post-gate path (accepted plans, commits, notifications)
    # would otherwise import lazily is imported here, before the agent CLI
    # blocks on its first turn. A `sase dev update` landing mid-run then cannot
    # tear a deferred import against modules cached from the old revision.
    preload_post_gate_modules()

    # Advisory only: this never blocks `sase dev update` or the ACE update
    # preview, it just lets both name this runner as live while a swap could
    # still tear a deferred import underneath it.
    advisory_command = (state.agent_name,) if state.agent_name else ()
    with code_swap_advisory_reader_lock(op="agent.runner", command=advisory_command):
        exec_result = run_execution_loop(
            _build_exec_context(
                state,
                bootstrap,
                vcs_tag=vcs_tag,
                wait_chats=wait_chats,
                output_variable_namespaces=output_variable_namespaces,
            ),
            state.prompt,
        )
    state.exec_outcome = exec_result.outcome
    state.success = classify_exec_success(
        success=exec_result.success,
        outcome=state.exec_outcome,
    )
    state.saved_path = exec_result.saved_path
    state.diff_path = exec_result.diff_path
    state.markdown_pdf_paths = exec_result.markdown_pdf_paths
    state.markdown_source_count = exec_result.markdown_source_count
    state.image_paths = exec_result.image_paths
    state.video_paths = exec_result.video_paths
    state.current_artifacts_dir = exec_result.current_artifacts_dir
    state.step_output = exec_result.step_output
