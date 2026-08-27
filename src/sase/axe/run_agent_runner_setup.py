"""Pre-execution setup helpers for ``run_agent_runner``.

Contains the bookkeeping that runs before the agent's execution loop:
artifacts directory + initial workflow_state.json, prompt preprocessing,
retry-spawn handoff loading, retry-chain ancestry recording, telemetry spawn
counters, and the home-mode running marker.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from sase.artifacts import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)
from sase.axe.run_agent_retry_spawn import (
    ENV_RETRY_ATTEMPT,
    ENV_RETRY_CHAIN_ROOT_TIMESTAMP,
    ENV_RETRY_HANDOFF,
    ENV_RETRY_OF_TIMESTAMP,
    RetryHandoff,
)
from sase.axe.runner_workspace import (
    prepare_launch_workspace_repos,
    prepare_workspace,
)
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.process_identity import process_identity_token
from sase.telemetry import flush_metrics
from sase.telemetry.metrics import (
    AGENT_ACTIVE,
    AGENT_SPAWNS,
    WORKSPACE_ACTIVE,
)

if TYPE_CHECKING:
    from sase.linked_repos import LinkedRepoResolution


def _without_hidden_sidecars(
    resolution: "LinkedRepoResolution",
) -> "LinkedRepoResolution":
    """Defensively remove hidden sidecars from launch-facing metadata."""

    from sase._linked_repo_config import HIDDEN_SIDECAR_ROLES
    from sase.linked_repos import LinkedRepoResolution

    def is_hidden(repo: Any) -> bool:
        if repo.kind != "sidecar":
            return False
        if repo.name in HIDDEN_SIDECAR_ROLES:
            return True
        return bool(
            repo.slug == repo.name
            and any(repo.name.endswith(f"--{role}") for role in HIDDEN_SIDECAR_ROLES)
        )

    visible = tuple(repo for repo in resolution.repos if not is_hidden(repo))
    if visible == resolution.repos:
        return resolution
    return LinkedRepoResolution(visible, resolution.warnings)


def _guard_workspace_not_occupied(
    *,
    checkout_dir: str,
    project_file: str,
    workspace_num: int,
    project_name: str,
    workflow_name: str,
    artifacts_timestamp: str | None,
) -> None:
    """Refuse to destructively prepare *checkout_dir* if another live agent
    holds it.

    Raises ``WorkspaceOccupiedError`` (a ``RuntimeError``) on conflict,
    which flows into the runner's normal failure/done-marker path like any
    other setup exception.
    """
    from sase.core.occupancy_guard import (
        OccupancyCaller,
        WorkspaceOccupiedError,
        ensure_workspace_not_occupied,
    )

    try:
        ensure_workspace_not_occupied(
            checkout_dir,
            project_file=project_file,
            caller=OccupancyCaller(
                pid=os.getpid(),
                workspace_num=workspace_num,
                project=project_name,
                workflow=workflow_name,
                artifacts_timestamp=artifacts_timestamp,
            ),
        )
    except WorkspaceOccupiedError:
        raise


def prepare_workspace_if_needed(
    *,
    workspace_dir: str,
    workspace_num: int,
    cl_name: str,
    update_target: str,
    project_name: str,
    is_home_mode: bool,
    retry_handoff: object | None,
    project_file: str = "",
    workflow_name: str = "",
    artifacts_timestamp: str | None = None,
) -> frozenset[str]:
    """Prepare a non-home workspace unless this runner must preserve it."""
    if not update_target or is_home_mode:
        return frozenset()

    if retry_handoff is not None:
        print(
            "=== Skipping workspace prep (retry-spawn child) — "
            "parent's in-progress edits preserved ==="
        )
        print()
        return frozenset()

    _guard_workspace_not_occupied(
        checkout_dir=workspace_dir,
        project_file=project_file,
        workspace_num=workspace_num,
        project_name=project_name,
        workflow_name=workflow_name,
        artifacts_timestamp=artifacts_timestamp,
    )

    print("=== Preparing Workspace ===")
    if not prepare_workspace(
        workspace_dir,
        cl_name,
        update_target,
        backup_suffix="ace",
        project_basename=project_name,
    ):
        raise RuntimeError("Failed to prepare workspace")
    fresh_sidecars = prepare_launch_workspace_repos(workspace_dir, workspace_num)
    print("===========================")
    print()
    return fresh_sidecars


def prepare_linked_repo_workspaces_if_needed(
    *,
    resolution: "LinkedRepoResolution",
    cl_name: str,
    fresh_sidecar_paths: frozenset[str] = frozenset(),
    primary_workspace_dir: str = "",
    workspace_num: int = 0,
    project_name: str = "",
    project_file: str = "",
    workflow_name: str = "",
    artifacts_timestamp: str | None = None,
) -> None:
    """Materialize and prepare host-scoped linked repo workspaces for a launch."""
    resolution = _without_hidden_sidecars(resolution)
    repos = [
        repo
        for repo in resolution.repos
        if repo.auto_clone
        and repo.workspace_dir
        and repo.workspace_dir != repo.primary_dir
    ]
    if not repos:
        return

    from sase.vcs_provider import VCS_DEFAULT_REVISION

    print("=== Preparing Linked Repo Workspaces ===")
    for repo in repos:
        name = repo.name
        normalized_workspace = str(Path(repo.workspace_dir).expanduser().resolve())
        if repo.kind == "sidecar" and normalized_workspace in fresh_sidecar_paths:
            print(f"Using freshly cloned sidecar {name}: {repo.workspace_dir}")
            continue

        from sase.linked_repos import materialize_linked_repo_workspace

        sidecar_was_missing = repo.kind == "sidecar" and not os.path.lexists(
            repo.workspace_dir
        )
        try:
            workspace_dir = materialize_linked_repo_workspace(
                primary_dir=repo.primary_dir,
                workspace_dir=repo.workspace_dir,
                workspace_num=repo.workspace_num,
                expected_remote_url=(
                    repo.remote_url if repo.kind == "sidecar" else None
                ),
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to materialize linked repo {name!r} workspace: "
                f"{repo.workspace_dir}: {exc}"
            ) from exc
        if sidecar_was_missing:
            print(f"Using freshly cloned sidecar {name}: {workspace_dir}")
            continue
        # Linked-repo checkouts share their parent workspace's claim and
        # occupant record — there is no separate per-repo claim to check.
        if not primary_workspace_dir.strip():
            raise ValueError(
                "primary_workspace_dir is required before preparing retained "
                f"linked repo {name!r}"
            )
        _guard_workspace_not_occupied(
            checkout_dir=primary_workspace_dir,
            project_file=project_file,
            workspace_num=workspace_num,
            project_name=project_name,
            workflow_name=workflow_name,
            artifacts_timestamp=artifacts_timestamp,
        )
        print(f"Preparing linked repo {name}: {workspace_dir}")
        if not prepare_workspace(
            workspace_dir,
            cl_name,
            VCS_DEFAULT_REVISION,
            backup_suffix=f"linked-{name}",
        ):
            raise RuntimeError(
                f"Failed to prepare linked repo {name!r} workspace: {workspace_dir}"
            )
    from sase.linked_repos import apply_linked_repo_env

    apply_linked_repo_env(os.environ, resolution)
    print("========================================")
    print()


def setup_artifacts_directory(
    *,
    timestamp: str,
    project_file: str,
    cl_name: str,
    is_home_mode: bool,
) -> tuple[str, str, str]:
    """Compute project name, artifacts paths, and seed ``workflow_state.json``.

    Returns ``(project_name, artifacts_timestamp, artifacts_dir)``. The
    initial ``workflow_state.json`` is written so the TUI can merge this
    entry as a WORKFLOW immediately, before ``WorkflowExecutor.execute()``
    overwrites it later.
    """
    if is_home_mode:
        project_name = "home"
    else:
        project_name = os.path.basename(os.path.dirname(project_file))
    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    artifacts_dir = create_artifacts_directory(
        "ace-run",
        project_name=project_name,
        timestamp=timestamp,
    )

    pid = os.getpid()
    initial_state: dict[str, object] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"patch_name": cl_name, "cl_name": cl_name},
        "artifacts_dir": artifacts_dir,
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "appears_as_agent": True,
    }
    with open(
        os.path.join(artifacts_dir, "workflow_state.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(initial_state, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)

    return project_name, artifacts_timestamp, artifacts_dir


def preprocess_prompt_xprompts(
    prompt: str, artifacts_dir: str
) -> tuple[str, str | None, str]:
    """Resolve aliases, save raw, expand xprompt references.

    Returns ``(prompt, vcs_tag, raw_resolved_prompt)``. The VCS workflow tag
    and raw prompt are captured after alias resolution but before xprompt
    expansion so follow-up naming and chat-resume decisions can use the
    original top-level references.
    """
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt import resolve_xprompt_aliases
    from sase.xprompt._parsing import extract_vcs_workflow_tag
    from sase.xprompt.processor import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    prompt = resolve_xprompt_aliases(prompt)
    raw_resolved_prompt = prompt
    vcs_tag = extract_vcs_workflow_tag(prompt)

    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Capture launch-boundary xprompt usage (e.g. #plan) into the shared
    # xprompts.json before expansion erases the references. Use the same
    # alias-resolved text persisted to raw_xprompt.md so the collector's
    # alias/VCS-underscore handling matches the expansion path. The root
    # agent row reads this file; workflow steps only write step-specific
    # files (see write_used_xprompts step_only). Best-effort: metadata
    # capture must never take down a detached agent launch.
    try:
        from sase.xprompt.used_xprompts import (
            SASE_LAUNCH_SWARM_XPROMPTS,
            write_used_xprompts,
        )

        encoded_swarm_xprompts = os.environ.get(SASE_LAUNCH_SWARM_XPROMPTS)
        swarm_xprompts = (
            json.loads(encoded_swarm_xprompts) if encoded_swarm_xprompts else None
        )
        if swarm_xprompts is not None and (
            not isinstance(swarm_xprompts, list)
            or not all(isinstance(name, str) for name in swarm_xprompts)
        ):
            raise ValueError(
                f"{SASE_LAUNCH_SWARM_XPROMPTS} must be a JSON array of strings"
            )
        write_used_xprompts(
            artifacts_dir,
            prompt,
            swarm_xprompts=swarm_xprompts,
        )
    except Exception as e:
        print(f"Warning: Failed to write xprompt metadata: {e}", file=sys.stderr)

    prompt = process_xprompt_references(
        prompt,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
    )
    return prompt, vcs_tag, raw_resolved_prompt


def expand_deferred_launch_xprompts(
    prompt: str,
    artifacts_dir: str,
    *,
    extra_xprompts: dict[str, Any] | None = None,
) -> str:
    """Expand launch-deferred fork references after dependency admission.

    Ordinary xprompts are expanded first in case a refreshed definition now
    introduces a fork.  Embedded workflow expansion is then restricted to the
    launch-deferred set so VCS and completion workflows keep their established
    execution timing inside the agent workflow.

    ``SASE_ARTIFACTS_DIR`` is set to *artifacts_dir* for the duration of this
    call and restored afterward (this run's own value is not published by
    ``publish_phase_env()`` until later in ``run_execution_loop()``). A bare
    ``#fork`` resolves its parent through
    ``_resolve_default_agent_name(exclude_artifacts_dir=...)``, which reads
    ``SASE_ARTIFACTS_DIR`` to exclude the run being launched from its own
    resolution; without this scoping that self-exclusion silently no-ops and
    a named run can resolve `#fork` to itself. The restore is scoped narrowly
    here rather than calling ``publish_phase_env()`` early, which also sets
    ``SASE_AGENT_TIMESTAMP`` and would change the unset/inherited snapshot
    that ``run_execution_loop()`` takes of that variable before publishing it.
    """
    from sase.main.query_handler import expand_embedded_workflows_in_query
    from sase.xprompt.processor import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    prompt = process_xprompt_references(
        prompt,
        extra_xprompts=extra_xprompts,
    )

    previous_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
    try:
        prompt, embedded_workflows = expand_embedded_workflows_in_query(
            prompt,
            artifacts_dir,
            only_workflow_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            preserve_existing_xprompt_metadata=True,
        )
    finally:
        if previous_artifacts_dir is None:
            os.environ.pop("SASE_ARTIFACTS_DIR", None)
        else:
            os.environ["SASE_ARTIFACTS_DIR"] = previous_artifacts_dir

    workflows_with_post_steps = [
        result.workflow_name for result in embedded_workflows if result.post_steps
    ]
    if workflows_with_post_steps:
        names = ", ".join(sorted(set(workflows_with_post_steps)))
        raise RuntimeError("Launch-deferred workflows cannot have post-steps: " + names)
    return prompt


def write_submitted_xprompt_artifact(artifacts_dir: str, submitted_xprompt: str) -> str:
    """Persist the launch-boundary prompt without alias or xprompt expansion."""
    path = os.path.join(artifacts_dir, "submitted_xprompt.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(submitted_xprompt)
    return path


def load_retry_handoff_from_env() -> RetryHandoff | None:
    """Load retry-spawn handoff (if any) and print a summary."""
    retry_handoff_path = os.environ.get(ENV_RETRY_HANDOFF)
    if not retry_handoff_path:
        return None
    handoff = RetryHandoff.read_from_path(retry_handoff_path)
    if handoff is not None:
        print("=== Retry-Spawn Handoff Loaded ===")
        print(f"  parent: {handoff.parent_timestamp}")
        print(f"  retry attempt: #{handoff.retry_attempt}")
        print(f"  chain root: {handoff.chain_root_timestamp}")
        print(f"  category: {handoff.error_category}")
        print("==================================")
        print()
    return handoff


def print_agent_start_banner(
    *, cl_name: str, workspace_dir: str, workflow_name: str, prompt: str
) -> None:
    print("Starting agent run")
    print(f"Patch: {cl_name}")
    print(f"Workspace: {workspace_dir}")
    print(f"Workflow: {workflow_name}")
    print()
    print("=== Prompt ===")
    print(prompt)
    print("==============")
    print()


def enter_agent_workspace(workspace_dir: str, workspace_num: int = 1) -> None:
    """Chdir into the agent workspace and install per-clone ignore entries."""
    os.chdir(workspace_dir)
    os.environ["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir
    from sase.sdd.env import set_sdd_dir_env

    set_sdd_dir_env(
        os.environ,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )

    # Keep runtime state and host-scoped linked clones untracked in this clone.
    # ``.git/info/exclude`` is git's per-clone ignore file honored by
    # ``git clean`` even before the tracked project .gitignore is initialized.
    from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

    ensure_git_info_exclude_entry(workspace_dir, ".sase/")
    ensure_git_info_exclude_entry(workspace_dir, "/sase/repos/")


def build_output_variable_namespaces(wait_names: list[str]) -> dict[str, Any]:
    from sase.agent.output_variable_context import (
        SASE_AGENT_VAR_UPSTREAMS_ENV,
        build_agent_output_variable_context,
    )

    return build_agent_output_variable_context(
        upstreams_json=os.environ.get(SASE_AGENT_VAR_UPSTREAMS_ENV),
        wait_names=wait_names,
    )


def apply_retry_chain_to_meta(
    *,
    retry_handoff: RetryHandoff | None,
    agent_meta: dict[str, Any],
    artifacts_dir: str,
) -> dict[str, Any]:
    """Record retry-chain ancestry into ``agent_meta.json``.

    With a real handoff: writes parent/attempt/root/category pointers so
    the TUI loader can render the chain. Without a handoff: honors the
    env-var fallback (used by tests).
    """
    if retry_handoff is not None:
        agent_meta["retry_of_timestamp"] = retry_handoff.parent_timestamp
        agent_meta["retry_attempt"] = retry_handoff.retry_attempt
        agent_meta["retry_chain_root_timestamp"] = retry_handoff.chain_root_timestamp
        agent_meta["retry_error_category"] = retry_handoff.error_category
        write_agent_meta(artifacts_dir, agent_meta)
        return agent_meta

    env_retry_attempt = os.environ.get(ENV_RETRY_ATTEMPT)
    env_retry_of = os.environ.get(ENV_RETRY_OF_TIMESTAMP)
    env_retry_root = os.environ.get(ENV_RETRY_CHAIN_ROOT_TIMESTAMP)
    if not (env_retry_attempt and env_retry_of):
        return agent_meta
    try:
        agent_meta["retry_attempt"] = int(env_retry_attempt)
        agent_meta["retry_of_timestamp"] = env_retry_of
        if env_retry_root:
            agent_meta["retry_chain_root_timestamp"] = env_retry_root
        write_agent_meta(artifacts_dir, agent_meta)
        return agent_meta
    except ValueError:
        return agent_meta


def refresh_linked_repos_for_workspace(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    artifacts_dir: str,
    agent_meta: dict[str, Any],
) -> "LinkedRepoResolution":
    """Refresh linked-repo env/meta after a workspace claim changes."""
    from sase.linked_repos import (
        apply_linked_repo_env,
        resolve_linked_repos_for_project,
    )

    resolution = resolve_linked_repos_for_project(
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        materialize=False,
    )
    resolution = _without_hidden_sidecars(resolution)
    apply_linked_repo_env(os.environ, resolution)
    agent_meta["workspace_dir"] = workspace_dir
    if resolution.repos:
        # Canonical key plus the deprecated alias for existing readers.
        agent_meta["linked_repos"] = resolution.to_jsonable()
        agent_meta["sibling_repos"] = resolution.to_jsonable()
    write_agent_meta(artifacts_dir, agent_meta)
    return resolution


def capture_sdd_base_sha(workspace_dir: str, workspace_num: int) -> str | None:
    """Return the sidecar SDD repo HEAD to bound finalize-time scans."""
    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(workspace_dir, workspace_num)
    except Exception:
        return None

    if store.is_in_tree:
        return None

    repo_root = Path(store.repo_root).expanduser()
    if not (repo_root / ".git").exists():
        return None

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def write_agent_meta(artifacts_dir: str, agent_meta: dict[str, Any]) -> None:
    write_agent_meta_atomic(
        artifacts_dir,
        agent_meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )


def bump_spawn_telemetry(
    *,
    agent_llm_provider: str | None,
    project_name: str,
    is_home_mode: bool,
    workflow_name: str,
    timestamp: str,
) -> None:
    """Increment spawn/active gauges and flush immediately.

    These live in the runner (not in launcher.py) because
    ``init_telemetry()`` has already run in this process and
    ``agent_llm_provider`` is now known from directives. The flush is
    forced because the atexit flush only fires after gauges decrement to 0.
    """
    AGENT_SPAWNS.labels(
        llm_provider=agent_llm_provider or "", project=project_name
    ).inc()
    AGENT_ACTIVE.labels(
        llm_provider=agent_llm_provider or "", project=project_name
    ).inc()
    if not is_home_mode:
        WORKSPACE_ACTIVE.labels(project=project_name).inc()
    flush_metrics(
        job="agent_runner",
        grouping_key={"workflow": workflow_name, "instance": timestamp},
    )


def write_home_running_marker(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    prompt: str,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_vcs_provider: str | None,
    workspace_dir: str,
) -> str:
    """Write ``running.json`` for home-mode agents (no workspace tracking).

    Returns the path written, so the caller can clean it up at shutdown.
    """
    running_marker_path = os.path.join(artifacts_dir, "running.json")
    pid = os.getpid()
    running_marker: dict[str, Any] = {
        "patch_name": cl_name,
        "cl_name": cl_name,
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "timestamp": timestamp,
        "prompt": prompt,
        "workspace_dir": workspace_dir,
    }
    if agent_model:
        running_marker["model"] = agent_model
    if agent_llm_provider:
        running_marker["llm_provider"] = agent_llm_provider
    if agent_vcs_provider:
        running_marker["vcs_provider"] = agent_vcs_provider
    with open(running_marker_path, "w", encoding="utf-8") as f:
        json.dump(running_marker, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    return running_marker_path
