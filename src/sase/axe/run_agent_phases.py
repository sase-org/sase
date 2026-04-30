"""Lifecycle phase functions for the agent runner.

Functions for directive extraction, dependency waiting, workspace
management, done marker construction, and stop time recording.
"""

import json
import os
import sys
import time
from typing import Any, NamedTuple

from sase.axe.runner_utils import was_killed
from sase.axe.chop_agents import agent_meta_from_chop_env


class _AgentInfo(NamedTuple):
    """Result of directive extraction and metadata writing."""

    name: str | None
    wait_names: list[str]
    wait_duration: float | None
    wait_until: str | None
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    hidden: bool
    approve: bool
    plan: bool
    tag: str | None
    meta: dict[str, Any]
    local_xprompts: dict[str, Any]


def extract_directives_and_write_meta(
    prompt: str,
    workspace_dir: str,
    artifacts_dir: str,
    cl_name: str | None = None,
    *,
    raw_resolved_prompt: str | None = None,
) -> _AgentInfo:
    """Extract prompt directives and write agent_meta.json.

    Expands xprompt references, extracts directives (model, name, etc.),
    resolves LLM/VCS providers, writes metadata, and claims agent name.

    Returns _AgentInfo with all extracted info.
    """
    from sase.llm_provider.registry import (
        get_default_provider_name,
        resolve_model_provider,
    )
    from sase.llm_provider.temporary_override import (
        resolve_effective_default_provider_model,
    )
    from sase.vcs_provider._registry import detect_vcs
    from sase.xprompt import process_xprompt_references
    from sase.xprompt.directives import extract_prompt_directives

    # Parse user-prompt frontmatter to extract local xprompts.
    from sase.agent.multi_prompt import parse_multi_prompt

    multi = parse_multi_prompt(prompt)
    prompt_body = "\n---\n".join(multi.segments)

    # Merge env-var-delivered local xprompts (from multi-prompt launcher)
    # with frontmatter-defined ones.  Frontmatter takes precedence.
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
    if env_xprompts_path:
        try:
            from sase.agent.multi_prompt_launcher import deserialize_local_xprompts

            env_xprompts = deserialize_local_xprompts(env_xprompts_path)
            # Frontmatter xprompts take precedence over env-delivered ones.
            multi.local_xprompts = {**env_xprompts, **multi.local_xprompts}
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        finally:
            try:
                os.unlink(env_xprompts_path)
            except OSError:
                pass

    # Expand xprompts before extracting directives so that
    # directives embedded in xprompts (e.g. %model:#pro inside
    # #mentor) are discovered for agent metadata.
    expanded_for_directives = process_xprompt_references(
        prompt_body,
        extra_xprompts=multi.local_xprompts or None,
    )
    _, directives = extract_prompt_directives(expanded_for_directives)

    auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")

    agent_name = directives.name
    resume_name: str | None = None
    if not directives.name_explicit and not auto_dismiss:
        from sase.agent.names import first_resume_agent_name

        resume_name = first_resume_agent_name(raw_resolved_prompt)

    repeat_name = os.environ.get("SASE_REPEAT_NAME")
    name_requires_lock = bool(resume_name)

    from contextlib import AbstractContextManager, nullcontext

    name_lock_context: AbstractContextManager[None]
    if name_requires_lock:
        from sase.agent.names import agent_name_allocation_lock

        name_lock_context = agent_name_allocation_lock()
    else:
        name_lock_context = nullcontext()

    agent_model = directives.model
    if agent_model:
        resolved_provider, agent_model = resolve_model_provider(agent_model)
        agent_llm_provider = resolved_provider or get_default_provider_name()
    else:
        agent_llm_provider, agent_model = resolve_effective_default_provider_model()

    vcs_name = detect_vcs(workspace_dir)
    if vcs_name:
        from sase.workspace_provider import get_display_name_by_vcs

        agent_vcs_provider = get_display_name_by_vcs(vcs_name)
    else:
        agent_vcs_provider = None

    with name_lock_context:
        if not directives.name_explicit and resume_name is not None:
            from sase.agent.names import allocate_resume_name

            agent_name = allocate_resume_name(resume_name)
        if agent_name is None:
            agent_name = repeat_name
        if agent_name is None and not auto_dismiss:
            from sase.agent.names import get_next_auto_name

            agent_name = get_next_auto_name()

        # Build agent_meta dict
        agent_meta: dict[str, Any] = {"pid": os.getpid()}
        if agent_name:
            agent_meta["name"] = agent_name
        if directives.wait:
            agent_meta["wait_for"] = directives.wait
        if directives.wait_duration is not None:
            agent_meta["wait_duration"] = directives.wait_duration
        if directives.wait_until is not None:
            agent_meta["wait_until"] = directives.wait_until
        if agent_model:
            agent_meta["model"] = agent_model
        if agent_llm_provider:
            agent_meta["llm_provider"] = agent_llm_provider
        if agent_vcs_provider:
            agent_meta["vcs_provider"] = agent_vcs_provider
        if directives.approve:
            agent_meta["approve"] = True
        if directives.hide or auto_dismiss:
            agent_meta["hidden"] = True
        if directives.plan:
            agent_meta["plan"] = True
        if directives.tag:
            agent_meta["tag"] = directives.tag
        agent_meta.update(agent_meta_from_chop_env())

        # Write agent_meta.json
        if agent_meta:
            meta_path = os.path.join(artifacts_dir, "agent_meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(agent_meta, f, indent=2)

            if agent_name:
                from sase.agent.names import claim_agent_name

                claim_agent_name(
                    agent_name, artifacts_dir, explicit=directives.name_explicit
                )
                os.environ["SASE_AGENT_NAME"] = agent_name

    # Persist the %tag directive into ~/.sase/agent_tags.json so the Agents
    # tab picks it up at load time.  The agent's identity is
    # (agent_type=WORKFLOW, cl_name, raw_suffix) — matching how run-agents
    # are loaded via the workflow loader.
    if directives.tag and cl_name:
        from sase.ace.agent_tags import (
            load_agent_tags,
            save_agent_tags,
            set_tag,
        )
        from sase.ace.tui.models.agent import AgentType

        raw_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
        identity = (AgentType.WORKFLOW, cl_name, raw_suffix)
        store = load_agent_tags()
        set_tag(store, identity, directives.tag)
        save_agent_tags(store)

    return _AgentInfo(
        name=agent_name,
        wait_names=directives.wait,
        wait_duration=directives.wait_duration,
        wait_until=directives.wait_until,
        model=agent_model,
        llm_provider=agent_llm_provider,
        vcs_provider=agent_vcs_provider,
        hidden=bool(directives.hide or auto_dismiss),
        approve=bool(directives.approve),
        plan=bool(directives.plan),
        tag=directives.tag,
        meta=agent_meta,
        local_xprompts=multi.local_xprompts,
    )


def _remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    target = dt_cls.fromisoformat(wait_until)
    return max(0.0, (target - dt_cls.now()).total_seconds())


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    duration: float | None = None,
    wait_until: str | None = None,
) -> None:
    """Wait for named agent dependencies, a duration, or an absolute time.

    When *wait_names* is non-empty, writes waiting.json, polls for ready.json,
    then updates agent_meta.json with run_started_at.  When *duration* is set,
    the agent won't start before that many seconds have elapsed — even if all
    named dependencies finish earlier.  When *wait_until* is set (ISO 8601
    timestamp), the agent won't start before that wall-clock time.

    Exits with SIGTERM code if killed during wait.
    """
    _WAIT_POLL_INTERVAL = 2  # seconds
    _WAIT_MAX_TIMEOUT = 86400  # 24 hours

    if wait_names:
        # --- Agent-name dependency path (with optional duration/time floor) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        waiting_data: dict[str, Any] = {
            "waiting_for": wait_names,
            "cl_name": cl_name,
            "timestamp": timestamp,
        }
        if duration is not None:
            waiting_data["wait_duration"] = duration
        if wait_until is not None:
            waiting_data["wait_until"] = wait_until
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(waiting_data, f, indent=2)

        parts = [f"agents: {', '.join(wait_names)}"]
        if duration is not None:
            parts.append(f"duration: {duration:.0f}s")
        if wait_until is not None:
            parts.append(f"until: {wait_until}")
        print(f"Waiting for {' and '.join(parts)}")

        # Poll for ready.json (written by wait_checks lumberjack chop)
        ready_path = os.path.join(artifacts_dir, "ready.json")
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

        # If a duration floor is set and we finished early, sleep the remainder
        if duration is not None and wait_elapsed < duration and not was_killed():
            remaining = duration - wait_elapsed
            print(
                f"Dependencies satisfied, sleeping {remaining:.0f}s for duration floor"
            )
            while remaining > 0 and not was_killed():
                sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
                time.sleep(sleep_time)
                remaining -= sleep_time

        # If an absolute-time floor is set, sleep until the target
        if wait_until is not None and not was_killed():
            remaining = _remaining_until(wait_until)
            if remaining > 0:
                print(f"Dependencies satisfied, waiting until {wait_until}")
                while remaining > 0 and not was_killed():
                    sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
                    time.sleep(sleep_time)
                    remaining = _remaining_until(wait_until)

        # Clean up wait markers
        for path in (waiting_path, ready_path):
            try:
                os.unlink(path)
            except OSError:
                pass
    elif wait_until is not None:
        # --- Absolute-time-only path (no agent-name dependencies) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        until_waiting_data: dict[str, Any] = {
            "waiting_for": [],
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_until": wait_until,
        }
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(until_waiting_data, f, indent=2)

        print(f"Waiting until: {wait_until}")
        remaining = _remaining_until(wait_until)
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            time.sleep(sleep_time)
            remaining = _remaining_until(wait_until)

        # Clean up waiting.json
        try:
            os.unlink(waiting_path)
        except OSError:
            pass
    else:
        # --- Duration-only path (no agent-name dependencies) ---
        assert duration is not None

        # Write waiting.json so TUI can detect WAITING status
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        dur_waiting_data: dict[str, Any] = {
            "waiting_for": [],
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_duration": duration,
        }
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(dur_waiting_data, f, indent=2)

        print(f"Waiting for duration: {duration:.0f}s")
        remaining = duration
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time

        # Clean up waiting.json
        try:
            os.unlink(waiting_path)
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


def resolve_wait_chat_paths(wait_names: list[str]) -> list[str]:
    """Resolve each waited-for agent name to its ``~/.sase/chats/`` transcript path.

    Called after :func:`wait_for_dependencies` returns, so each completed
    agent should have a ``done.json`` with a ``response_path`` field.  Names
    that can't be resolved or whose agent has no ``response_path`` (e.g. the
    agent failed or crashed before saving a transcript) are skipped with a
    warning; order of the remaining names is preserved, including duplicates.
    """
    from sase.agent.names import find_named_agent
    from sase.output import print_status

    resolved: list[str] = []
    for name in wait_names:
        agent = find_named_agent(name, only_done=True)
        if agent is None:
            print_status(
                f"wait_chats: no done agent found for '{name}' — skipping",
                "warning",
            )
            continue
        done_path = os.path.join(agent.artifacts_dir, "done.json")
        try:
            with open(done_path, encoding="utf-8") as f:
                done_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            print_status(
                f"wait_chats: cannot read done.json for '{name}' ({exc}) — skipping",
                "warning",
            )
            continue
        response_path = done_data.get("response_path")
        if not response_path:
            print_status(
                f"wait_chats: agent '{name}' has no response_path — skipping",
                "warning",
            )
            continue
        resolved.append(str(response_path))
    return resolved


def resolve_agent_refs_in_prompt(prompt: str) -> tuple[str, str | None]:
    """Resolve @name agent references in VCS tags.

    Normalizes underscore VCS refs, extracts the VCS tag, checks for
    @name in the ref portion, and replaces it with the agent's changespec.

    Returns (resolved_prompt, resolved_vcs_tag).
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
        normalize_vcs_underscore_refs,
    )

    # Normalize #gh_@a -> #gh:@a so downstream only sees colon form
    prompt = normalize_vcs_underscore_refs(prompt)

    # Extract the VCS tag (handles leading %directives)
    vcs_tag = extract_vcs_workflow_tag(prompt)
    if not vcs_tag:
        return prompt, None

    # Check if the ref portion is an @name reference
    ref = extract_project_from_vcs_tag(vcs_tag)
    if not ref or not ref.startswith("@"):
        return prompt, vcs_tag

    agent_name = ref[1:]  # strip leading @
    if not agent_name:
        return prompt, vcs_tag

    # Resolve the agent reference
    from sase.agent.names import resolve_agent_changespec

    changespec = resolve_agent_changespec(agent_name)

    # Replace @name with the changespec in the VCS tag portion
    new_tag = vcs_tag.replace(f"@{agent_name}", changespec)
    resolved_prompt = prompt.replace(vcs_tag, new_tag, 1)

    # Re-extract vcs_tag from the resolved prompt
    resolved_vcs_tag = extract_vcs_workflow_tag(resolved_prompt)
    return resolved_prompt, resolved_vcs_tag


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
    markdown_pdf_paths: list[str] | None = None,
    image_paths: list[str] | None = None,
    error: str | None = None,
    traceback_str: str | None = None,
    retry_metadata: dict[str, Any] | None = None,
    retried_as_timestamp: str | None = None,
    retry_chain_root_timestamp: str | None = None,
    retry_error_category: str | None = None,
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
        marker["markdown_pdf_paths"] = markdown_pdf_paths or []
        marker["image_paths"] = image_paths or []
    # Failed outcome includes error details
    if error:
        marker["error"] = error
    if traceback_str:
        marker["traceback"] = traceback_str
    if retry_metadata:
        marker["retry_metadata"] = retry_metadata
    # Spawn-on-retry: the failing parent records a forward pointer to its
    # retry child so the loader can build the retry-chain linkage without
    # opening agent_meta.json.
    if retried_as_timestamp:
        marker["retried_as_timestamp"] = retried_as_timestamp
    if retry_chain_root_timestamp:
        marker["retry_chain_root_timestamp"] = retry_chain_root_timestamp
    if retry_error_category:
        marker["retry_error_category"] = retry_error_category
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
