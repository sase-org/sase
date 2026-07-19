"""Low-level detached subprocess spawning for agents."""

import logging
import os
import sys
from functools import lru_cache

from sase.agent.launch_types import AgentLaunchResult
from sase.core.paths import sase_projects_dir

log = logging.getLogger(__name__)


def _remove_inherited_sase_codex_home(env: dict[str, str]) -> None:
    """Drop CODEX_HOME when it points at a SASE-managed temporary Codex home."""
    codex_home = env.get("CODEX_HOME")
    if not codex_home:
        return

    from sase.llm_provider.codex import is_sase_managed_codex_home

    if is_sase_managed_codex_home(codex_home):
        env.pop("CODEX_HOME", None)


def _remove_inherited_workspace_preallocation_env(env: dict[str, str]) -> None:
    """Drop stale workspace preallocation env inherited from a parent launch."""
    suffixes = ("_PRE_ALLOCATED", "_WORKSPACE_NUM", "_WORKSPACE_DIR")
    for key in list(env):
        if key.startswith("SASE_") and key.endswith(suffixes):
            env.pop(key, None)


def _remove_inherited_agent_identity_env(env: dict[str, str]) -> None:
    """Drop all stale per-agent context unless this launch supplies it.

    This includes deferred-workspace controls and cross-agent variable context;
    every legitimate ``SASE_AGENT_*`` value is restored from ``env_delta``
    after the ambient environment has been scrubbed.
    """
    from sase.agent.env_hygiene import scrub_agent_identity_env

    scrub_agent_identity_env(env)


def _remove_inherited_multi_agent_prompt_env(env: dict[str, str]) -> None:
    """Drop stale multi-agent prompt file context inherited from a parent agent."""
    from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_FILE_ENV

    env.pop(MULTI_AGENT_PROMPT_FILE_ENV, None)


def _remove_inherited_model_alias_overrides(
    env: dict[str, str],
    extra_env: dict[str, str] | None,
) -> None:
    """Keep family overrides off unrelated nested subprocess launches."""
    from sase.llm_provider.launch_alias_overrides import (
        SASE_MODEL_ALIAS_OVERRIDES_ENV,
    )

    if not extra_env or SASE_MODEL_ALIAS_OVERRIDES_ENV not in extra_env:
        env.pop(SASE_MODEL_ALIAS_OVERRIDES_ENV, None)


def _remove_inherited_linked_repo_env(env: dict[str, str]) -> None:
    """Drop stale linked-repo mappings inherited from parent agents."""
    from sase.linked_repos import scrub_linked_repo_env

    scrub_linked_repo_env(env)


def _overwrite_project_dir_env(env: dict[str, str], workspace_dir: str) -> None:
    """Bind project-dir env vars to the spawned child's actual workspace.

    The parent's ``os.environ`` may carry stale values from
    ``apply_chdir_output()`` workflow mutations; without this rewrite they
    would shadow the child's true workspace when ``_resolve_codex_project_dir``
    consults env before cwd.
    """
    if workspace_dir:
        env["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir
    env.pop("CODEX_PROJECT_DIR", None)


@lru_cache(maxsize=1)
def _get_runner_script() -> str:
    import importlib.util

    _spec = importlib.util.find_spec("sase.axe.run_agent_runner")
    assert _spec is not None and _spec.origin is not None
    return os.path.abspath(_spec.origin)


def _preallocated_workspace_env(
    vcs_ref: tuple[str, str] | None,
    *,
    workspace_num: int,
    workspace_dir: str,
) -> dict[str, str]:
    if vcs_ref is None:
        return {}

    from sase.workspace_provider import get_pre_allocated_env_prefix

    prefix = get_pre_allocated_env_prefix(vcs_ref[0])
    if not prefix:
        return {}
    return {
        f"{prefix}_PRE_ALLOCATED": "1",
        f"{prefix}_WORKSPACE_NUM": str(workspace_num),
        f"{prefix}_WORKSPACE_DIR": workspace_dir,
    }


def spawn_agent_subprocess(
    *,
    cl_name: str,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    workflow_name: str,
    prompt: str,
    timestamp: str,
    update_target: str = "",
    project_name: str = "",
    history_sort_key: str = "",
    is_home_mode: bool = False,
    vcs_ref: tuple[str, str] | None = None,
    deferred_workspace: bool = False,
    local_xprompts_file: str | None = None,
    extra_env: dict[str, str] | None = None,
    retry_transfer_from_pid: int | None = None,
) -> AgentLaunchResult:
    """Spawn a detached background agent process.

    This is the low-level entry point: all parameters must already be
    resolved by the caller.  The TUI uses this directly.

    When ``retry_transfer_from_pid`` is set, the function transfers an
    existing workspace claim (held by the given PID) atomically to the new
    child instead of attempting a fresh ``claim_workspace`` -- used by the
    spawn-on-retry flow so the workspace slot stays continuously held.

    Raises:
        RuntimeError: If workspace claiming/transfer fails (process is
            terminated before the error is raised).
    """
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.artifacts import (
        convert_timestamp_to_artifacts_format,
        launch_artifacts_dir,
    )
    from sase.axe.chop_agents import record_chop_agent_launch_from_env
    from sase.core.agent_launch_facade import (
        prepare_agent_launch,
        safe_launch_name,
        spawn_prepared_agent_process,
    )
    from sase.core.agent_launch_wire import (
        AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        AgentLaunchRequestWire,
    )
    from sase.core.paths import get_sase_tmpdir, sharded_path
    from sase.running_field import (
        WorkspaceClaimError,
        claim_workspace,
        transfer_workspace_claim,
    )

    timer = LaunchTimingRecorder(
        "agent_launch_spawn",
        {
            "project_name": project_name,
            "cl_name": cl_name,
            "workspace_num": workspace_num,
            "home_mode": is_home_mode,
            "deferred_workspace": deferred_workspace,
        },
        durable=True,
    )

    # Resolve runner script path without importing the module (its top-level
    # code calls signal.signal() which fails from non-main threads).
    with timer.stage("runner_script_resolution"):
        runner_script = _get_runner_script()

    # Compute the output shard root in Python because sharding is still a
    # host-side policy. Rust owns the deterministic filename/path assembly.
    with timer.stage("output_path_derive"):
        output_filename = f"{safe_launch_name(cl_name)}_ace-run-{timestamp}.txt"
        output_path_hint = sharded_path("workflows", output_filename)
        output_root = os.path.dirname(output_path_hint)

    with timer.stage("linked_repo_resolution"):
        from sase.linked_repos import (
            LinkedRepoResolution,
            resolve_linked_repos_for_project,
        )

        linked_resolution = (
            LinkedRepoResolution(())
            if deferred_workspace
            else resolve_linked_repos_for_project(
                project_file=project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                materialize=False,
            )
        )

    request = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name=cl_name,
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        prompt=prompt,
        timestamp=timestamp,
        update_target=update_target,
        project_name=project_name,
        history_sort_key=history_sort_key,
        is_home_mode=is_home_mode,
        vcs_workflow_type=None if vcs_ref is None else vcs_ref[0],
        vcs_ref=None if vcs_ref is None else vcs_ref[1],
        deferred_workspace=deferred_workspace,
        local_xprompts_file=local_xprompts_file,
        extra_env=extra_env or {},
        retry_transfer_from_pid=retry_transfer_from_pid,
    )

    with timer.stage("launch_prepare", prompt_len=len(prompt)):
        prepared = prepare_agent_launch(
            request,
            python_executable=sys.executable,
            runner_script=runner_script,
            sase_tmpdir=get_sase_tmpdir(),
            output_root=output_root,
            preallocated_env=_preallocated_workspace_env(
                vcs_ref,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
            ),
        )

    # Build subprocess environment (copy to avoid mutating os.environ)
    with timer.stage("env_shape"):
        subprocess_env = dict(os.environ)
        _remove_inherited_sase_codex_home(subprocess_env)
        _remove_inherited_workspace_preallocation_env(subprocess_env)
        _remove_inherited_agent_identity_env(subprocess_env)
        _remove_inherited_multi_agent_prompt_env(subprocess_env)
        _remove_inherited_model_alias_overrides(subprocess_env, extra_env)
        _remove_inherited_linked_repo_env(subprocess_env)
        subprocess_env.update(prepared.env_delta)
        from sase.linked_repos import apply_linked_repo_env

        apply_linked_repo_env(subprocess_env, linked_resolution)
        _overwrite_project_dir_env(subprocess_env, workspace_dir)
        from sase.sdd.env import set_sdd_dir_env

        set_sdd_dir_env(
            subprocess_env,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
        )

    resolved_project_name = project_name or (
        "home" if is_home_mode else os.path.basename(os.path.dirname(project_file))
    )

    def _claim_spawned_child(pid: int) -> bool:
        # Claim workspace so agent appears in Agents tab while running.
        # For deferred-workspace agents (%wait), claim with workspace_num=0
        # so the agent appears in the TUI but doesn't reserve a real workspace.
        # For retry spawns, transfer an existing claim atomically so the slot
        # stays continuously held across the parent->child handoff.
        with timer.stage("workspace_claim"):
            return _claim_or_prepare_home_project(pid)

    def _claim_or_prepare_home_project(pid: int) -> bool:
        if prepared.claim_request is not None:
            artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
            claim_request = prepared.claim_request
            claim_num = claim_request.workspace_num
            if claim_request.transfer_from_pid is not None:
                result = transfer_workspace_claim(
                    claim_request.project_file,
                    claim_num,
                    from_pid=claim_request.transfer_from_pid,
                    to_pid=pid,
                    new_workflow=claim_request.workflow_name,
                    new_artifacts_timestamp=artifacts_timestamp,
                    cl_name=claim_request.cl_name,
                )
                if not result.success:
                    timer.finish(outcome="claim_failed")
                    raise WorkspaceClaimError(
                        f"Failed to transfer workspace #{claim_num} from "
                        f"pid {claim_request.transfer_from_pid}: "
                        f"{result.error or 'unknown reason'}",
                        workspace_num=claim_num,
                    )
            else:
                result = claim_workspace(
                    claim_request.project_file,
                    claim_num,
                    claim_request.workflow_name,
                    pid,
                    claim_request.cl_name,
                    artifacts_timestamp=artifacts_timestamp,
                )
                if not result.success:
                    timer.finish(outcome="claim_failed")
                    raise WorkspaceClaimError(
                        f"Failed to claim workspace #{claim_num}: "
                        f"{result.error or 'unknown reason'}",
                        workspace_num=claim_num,
                    )
        else:
            # Ensure home project directory and file exist
            from sase.ace.changespec.project_spec_path import (
                active_project_spec_filename,
                legacy_active_project_spec_filename,
            )

            home_project_dir = str(sase_projects_dir() / "home")
            os.makedirs(home_project_dir, exist_ok=True)
            canonical_home = os.path.join(
                home_project_dir, active_project_spec_filename("home")
            )
            legacy_home = os.path.join(
                home_project_dir, legacy_active_project_spec_filename("home")
            )
            # Treat the legacy `.gp` file as satisfying the existence check so
            # users mid-migration are not forced through a one-shot rename.
            if not os.path.exists(canonical_home) and not os.path.exists(legacy_home):
                with open(canonical_home, "w", encoding="utf-8") as f:
                    f.write("")
        return True

    # Spawn detached subprocess. Rust owns the process creation and will
    # terminate the child if the Python claim/home callback raises.
    with timer.stage("subprocess_spawn"):
        pid = spawn_prepared_agent_process(
            prepared,
            env=subprocess_env,
            claim_callback=_claim_spawned_child,
        )

    with timer.stage("chop_registry_record"):
        try:
            record_chop_agent_launch_from_env(
                pid=pid,
                project_file=project_file,
                project_name=resolved_project_name,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                cl_name=cl_name,
                timestamp=timestamp,
                prompt=prompt,
                env=subprocess_env,
            )
        except Exception:
            log.exception("Failed to record chop launch metadata for pid %s", pid)

    timer.finish(outcome="ok", pid=pid)
    planned_agent_name = (extra_env or {}).get("SASE_AGENT_PLANNED_NAME") or None
    return AgentLaunchResult(
        pid=pid,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        output_path=prepared.output_path,
        project_file=project_file,
        project_name=resolved_project_name,
        workflow_name=workflow_name,
        cl_name=cl_name,
        timestamp=timestamp,
        artifacts_dir=launch_artifacts_dir(resolved_project_name, timestamp),
        agent_name=planned_agent_name,
    )
