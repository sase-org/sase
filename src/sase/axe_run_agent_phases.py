"""Lifecycle phase functions for the agent runner.

Functions for directive extraction, dependency waiting, workspace
management, done marker construction, and stop time recording.
"""

import json
import os
import sys
import time
from typing import Any, NamedTuple

from sase.axe_runner_utils import was_killed


class _AgentInfo(NamedTuple):
    """Result of directive extraction and metadata writing."""

    name: str | None
    wait_names: list[str]
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    hidden: bool
    approve: bool
    plan: bool
    meta: dict[str, Any]


def extract_directives_and_write_meta(
    prompt: str,
    workspace_dir: str,
    artifacts_dir: str,
) -> _AgentInfo:
    """Extract prompt directives and write agent_meta.json.

    Expands xprompt references, extracts directives (model, name, etc.),
    resolves LLM/VCS providers, writes metadata, and claims agent name.

    Returns _AgentInfo with all extracted info.
    """
    from sase.llm_provider.registry import (
        get_default_provider_name,
        get_provider,
        resolve_model_provider,
    )
    from sase.vcs_provider._registry import detect_vcs
    from sase.xprompt import process_xprompt_references
    from sase.xprompt.directives import extract_prompt_directives

    # Parse user-prompt frontmatter to extract local xprompts.
    from sase.multi_prompt import parse_multi_prompt

    multi = parse_multi_prompt(prompt)
    prompt_body = "\n---\n".join(multi.segments)

    # Merge env-var-delivered local xprompts (from multi-prompt launcher)
    # with frontmatter-defined ones.  Frontmatter takes precedence.
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
    if env_xprompts_path:
        try:
            from sase.multi_prompt_launcher import deserialize_local_xprompts

            env_xprompts = deserialize_local_xprompts(env_xprompts_path)
            # Frontmatter xprompts take precedence over env-delivered ones.
            multi.local_xprompts = {**env_xprompts, **multi.local_xprompts}
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    # Expand xprompts before extracting directives so that
    # directives embedded in xprompts (e.g. %model:#pro inside
    # #mentor) are discovered for agent metadata.
    # Also collect hook commands from expanded xprompts.
    xprompt_hooks: list[str] = []
    expanded_for_directives = process_xprompt_references(
        prompt_body,
        extra_xprompts=multi.local_xprompts or None,
        hooks_collector=xprompt_hooks,
    )
    _, directives = extract_prompt_directives(expanded_for_directives)

    # Write collected xprompt hooks to a temp file so the stop hook can
    # find and run them.  The path is passed via SASE_XPROMPT_HOOKS_FILE.
    if xprompt_hooks:
        import tempfile

        hooks_fd, hooks_path = tempfile.mkstemp(
            prefix="sase_xprompt_hooks_", suffix=".json"
        )
        with os.fdopen(hooks_fd, "w") as hf:
            json.dump(xprompt_hooks, hf)
        os.environ["SASE_XPROMPT_HOOKS_FILE"] = hooks_path

    agent_name = directives.name
    if agent_name is None:
        from sase.agent_names import get_next_auto_name

        agent_name = get_next_auto_name()

    agent_model = directives.model
    if agent_model:
        resolved_provider, agent_model = resolve_model_provider(agent_model)
        agent_llm_provider = resolved_provider or get_default_provider_name()
    else:
        agent_llm_provider = get_default_provider_name()
        provider = get_provider()
        agent_model = provider.resolve_model_name()

    vcs_name = detect_vcs(workspace_dir)
    if vcs_name:
        from sase.workspace_provider import get_display_name_by_vcs

        agent_vcs_provider = get_display_name_by_vcs(vcs_name)
    else:
        agent_vcs_provider = None

    # Build agent_meta dict
    agent_meta: dict[str, Any] = {"pid": os.getpid()}
    if agent_name:
        agent_meta["name"] = agent_name
    if directives.wait:
        agent_meta["wait_for"] = directives.wait
    if agent_model:
        agent_meta["model"] = agent_model
    if agent_llm_provider:
        agent_meta["llm_provider"] = agent_llm_provider
    if agent_vcs_provider:
        agent_meta["vcs_provider"] = agent_vcs_provider
    if directives.approve:
        agent_meta["approve"] = True
    if directives.hide:
        agent_meta["hidden"] = True
    if directives.plan:
        agent_meta["plan"] = True

    # Write agent_meta.json
    if agent_meta:
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(agent_meta, f, indent=2)

        if agent_name:
            from sase.agent_names import claim_agent_name

            claim_agent_name(agent_name, artifacts_dir)
            os.environ["SASE_AGENT_NAME"] = agent_name

    return _AgentInfo(
        name=agent_name,
        wait_names=directives.wait,
        model=agent_model,
        llm_provider=agent_llm_provider,
        vcs_provider=agent_vcs_provider,
        hidden=bool(directives.hide),
        approve=bool(directives.approve),
        plan=bool(directives.plan),
        meta=agent_meta,
    )


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
) -> None:
    """Wait for named agent dependencies to complete.

    Writes waiting.json, polls for ready.json, then updates agent_meta.json
    with run_started_at. Exits with SIGTERM code if killed during wait.
    """
    waiting_path = os.path.join(artifacts_dir, "waiting.json")
    waiting_data = {
        "waiting_for": wait_names,
        "cl_name": cl_name,
        "timestamp": timestamp,
    }
    with open(waiting_path, "w", encoding="utf-8") as f:
        json.dump(waiting_data, f, indent=2)

    print(f"Waiting for agents: {', '.join(wait_names)}")

    # Poll for ready.json (written by wait_checks lumberjack chop)
    ready_path = os.path.join(artifacts_dir, "ready.json")
    _WAIT_POLL_INTERVAL = 2  # seconds
    _WAIT_MAX_TIMEOUT = 86400  # 24 hours
    wait_elapsed = 0.0
    while not os.path.exists(ready_path):
        if was_killed():
            break
        if wait_elapsed >= _WAIT_MAX_TIMEOUT:
            print(
                "Wait timeout exceeded, proceeding anyway",
                file=sys.stderr,
            )
            break
        time.sleep(_WAIT_POLL_INTERVAL)
        wait_elapsed += _WAIT_POLL_INTERVAL

    # Clean up wait markers
    for path in (waiting_path, ready_path):
        try:
            os.unlink(path)
        except OSError:
            pass

    if was_killed():
        print("Agent killed while waiting", file=sys.stderr)
        sys.exit(128 + 15)  # SIGTERM

    print("All dependencies satisfied, proceeding with workflow")

    # Record actual run start time in agent_meta.json so the
    # thinking panel can filter out JSONL files from the wait period.
    from datetime import UTC, datetime

    agent_meta["run_started_at"] = datetime.now(UTC).isoformat()
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(agent_meta, f, indent=2)


def claim_deferred_workspace(
    project_file: str,
    project_name: str,
    workflow_name: str,
    cl_name: str,
    artifacts_timestamp: str,
) -> tuple[int, str]:
    """Allocate a real workspace after deferred workspace wait completes.

    Releases the placeholder workspace_num=0 claim, allocates a new
    workspace, sets pre-allocation env vars, and claims the workspace.

    Returns (workspace_num, workspace_dir).
    """
    from sase.running_field import (
        claim_workspace as claim_ws,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    # Release the placeholder workspace_num=0 claim
    release_workspace(project_file, 0, workflow_name, cl_name)

    # Allocate a real workspace
    vcs_wf_type = os.environ.get("SASE_AGENT_VCS_WORKFLOW_TYPE")
    if vcs_wf_type:
        from sase.workspace_provider import (
            get_pre_allocated_env_prefix,
            get_workspace_directory as ws_get_dir,
        )

        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir = ws_get_dir(
            vcs_wf_type,
            workspace_num,
            project_name,
            os.getcwd(),
        )

        # Set pre-allocation env vars for embedded workflows
        prefix = get_pre_allocated_env_prefix(vcs_wf_type)
        if prefix:
            os.environ[f"{prefix}_PRE_ALLOCATED"] = "1"
            os.environ[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
            os.environ[f"{prefix}_WORKSPACE_DIR"] = workspace_dir
    else:
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir, _ = get_workspace_directory_for_num(workspace_num, project_name)

    # Claim the real workspace
    if not claim_ws(
        project_file,
        workspace_num,
        workflow_name,
        os.getpid(),
        cl_name,
        artifacts_timestamp=artifacts_timestamp,
    ):
        print(
            f"Failed to claim workspace #{workspace_num}",
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(workspace_dir)
    print(f"Claimed workspace #{workspace_num}: {workspace_dir}")
    return workspace_num, workspace_dir


def build_done_marker(
    cl_name: str,
    project_file: str,
    timestamp: str,
    artifacts_timestamp: str,
    workspace_num: int,
    output_path: str,
    outcome: str,
    *,
    agent_name: str | None = None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = None,
    agent_vcs_provider: str | None = None,
    agent_hidden: bool = False,
    response_path: str | None = None,
    step_output: dict[str, Any] | None = None,
    diff_path: str | None = None,
    plan_path: str | None = None,
    error: str | None = None,
    traceback_str: str | None = None,
    retry_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a done marker dict for writing to done.json."""
    marker: dict[str, Any] = {
        "cl_name": cl_name,
        "project_file": project_file,
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": outcome,
        "workspace_num": workspace_num,
        "output_path": output_path,
    }
    if agent_name:
        marker["name"] = agent_name
    if agent_model:
        marker["model"] = agent_model
    if agent_llm_provider:
        marker["llm_provider"] = agent_llm_provider
    if agent_vcs_provider:
        marker["vcs_provider"] = agent_vcs_provider
    if agent_hidden:
        marker["hidden"] = True
    # Completed outcome always includes result fields (even if None)
    if outcome == "completed":
        marker["response_path"] = response_path
        marker["step_output"] = step_output
        marker["diff_path"] = diff_path
        marker["plan_path"] = plan_path
    # Failed outcome includes error details
    if error:
        marker["error"] = error
    if traceback_str:
        marker["traceback"] = traceback_str
    if retry_metadata:
        marker["retry_metadata"] = retry_metadata
    return marker


def record_stop_time(*artifacts_dirs: str | None) -> None:
    """Record stopped_at timestamp in agent_meta.json for each artifacts dir."""
    from datetime import UTC, datetime as dt_cls

    stopped_at = dt_cls.now(UTC).isoformat()
    for ad in set(artifacts_dirs):
        if ad is None:
            continue
        meta_p = os.path.join(ad, "agent_meta.json")
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta_data = json.load(f)
            meta_data["stopped_at"] = stopped_at
            with open(meta_p, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, indent=2)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
