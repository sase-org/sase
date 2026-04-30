"""Pre-execution setup helpers for ``run_agent_runner``.

Contains the bookkeeping that runs before the agent's execution loop:
artifacts directory + initial workflow_state.json, prompt preprocessing,
retry-spawn handoff loading, dynamic memory injection, retry-chain
ancestry recording, telemetry spawn counters, and the home-mode running
marker.
"""

import json
import os
from typing import Any

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
from sase.axe.runner_utils import prepare_workspace
from sase.telemetry import push_metrics
from sase.telemetry.metrics import (
    AGENT_ACTIVE,
    AGENT_SPAWNS,
    WORKSPACE_ACTIVE,
)


def prepare_workspace_if_needed(
    *,
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    project_name: str,
    is_home_mode: bool,
    retry_handoff: object | None,
) -> None:
    """Prepare a non-home workspace unless this runner must preserve it."""
    if not update_target or is_home_mode:
        return

    if retry_handoff is not None:
        print(
            "=== Skipping workspace prep (retry-spawn child) — "
            "parent's in-progress edits preserved ==="
        )
        print()
        return

    print("=== Preparing Workspace ===")
    if not prepare_workspace(
        workspace_dir,
        cl_name,
        update_target,
        backup_suffix="ace",
        project_basename=project_name,
    ):
        raise RuntimeError("Failed to prepare workspace")
    print("===========================")
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

    initial_state: dict[str, object] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": cl_name},
        "artifacts_dir": artifacts_dir,
        "pid": os.getpid(),
        "appears_as_agent": True,
    }
    with open(
        os.path.join(artifacts_dir, "workflow_state.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(initial_state, f, indent=2)

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
    from sase.xprompt import resolve_xprompt_aliases
    from sase.xprompt._parsing import extract_vcs_workflow_tag
    from sase.xprompt.processor import process_xprompt_references

    prompt = resolve_xprompt_aliases(prompt)
    raw_resolved_prompt = prompt
    vcs_tag = extract_vcs_workflow_tag(prompt)

    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    prompt = process_xprompt_references(prompt)
    return prompt, vcs_tag, raw_resolved_prompt


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


def apply_dynamic_memory(prompt: str, project_name: str, artifacts_dir: str) -> str:
    """Generate dynamic memory and append the ``### DYNAMIC MEMORY`` section.

    Writes the ``dynamic_memory.json`` artifact and prints a user-visible
    summary. Returns the (possibly augmented) prompt.

    On-disk dynamic memory files written here may be wiped by
    embedded-workflow pre-steps (e.g. ``hg clean``); ``preprocess_prompt_late()``
    re-writes them right before file-reference validation.
    """
    from sase.memory.dynamic import (
        format_dynamic_memory_section,
        generate_dynamic_memory,
    )

    dynamic_result = generate_dynamic_memory(prompt, project_name)
    if not dynamic_result.matched:
        return prompt

    artifact = [
        {
            "name": m.name,
            "keywords_matched": m.keywords_matched,
            "content": m.content,
        }
        for m in dynamic_result.matched
    ]
    with open(
        os.path.join(artifacts_dir, "dynamic_memory.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(artifact, f, indent=2)

    print("=== Dynamic Memory ===")
    for m in dynamic_result.matched:
        kws = ", ".join(m.keywords_matched)
        print(f"  + {m.name}  (matched: {kws})")
    print("======================")
    print()

    return prompt + "\n\n" + format_dynamic_memory_section(dynamic_result)


def apply_retry_chain_to_meta(
    *,
    retry_handoff: RetryHandoff | None,
    agent_meta: dict[str, Any],
    artifacts_dir: str,
) -> None:
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
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(agent_meta, f, indent=2)
        return

    env_retry_attempt = os.environ.get(ENV_RETRY_ATTEMPT)
    env_retry_of = os.environ.get(ENV_RETRY_OF_TIMESTAMP)
    env_retry_root = os.environ.get(ENV_RETRY_CHAIN_ROOT_TIMESTAMP)
    if not (env_retry_attempt and env_retry_of):
        return
    try:
        agent_meta["retry_attempt"] = int(env_retry_attempt)
        agent_meta["retry_of_timestamp"] = env_retry_of
        if env_retry_root:
            agent_meta["retry_chain_root_timestamp"] = env_retry_root
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(agent_meta, f, indent=2)
    except ValueError:
        pass


def bump_spawn_telemetry(
    *,
    agent_llm_provider: str | None,
    project_name: str,
    is_home_mode: bool,
    workflow_name: str,
    timestamp: str,
) -> None:
    """Increment spawn/active gauges and push immediately.

    These live in the runner (not in launcher.py) because
    ``init_telemetry()`` has already run in this process and
    ``agent_llm_provider`` is now known from directives. The push is
    forced because the atexit push only fires after gauges decrement to 0.
    """
    AGENT_SPAWNS.labels(
        llm_provider=agent_llm_provider or "", project=project_name
    ).inc()
    AGENT_ACTIVE.labels(
        llm_provider=agent_llm_provider or "", project=project_name
    ).inc()
    if not is_home_mode:
        WORKSPACE_ACTIVE.labels(project=project_name).inc()
    push_metrics(
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
    running_marker: dict[str, Any] = {
        "cl_name": cl_name,
        "pid": os.getpid(),
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
    return running_marker_path
