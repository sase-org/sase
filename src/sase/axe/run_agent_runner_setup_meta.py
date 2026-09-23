"""Artifacts, agent-meta, retry-chain, and telemetry setup helpers.

Seeds the artifacts directory and ``workflow_state.json``, records retry
ancestry into ``agent_meta.json``, loads retry-spawn handoffs, bumps spawn
telemetry, and writes the home-mode running marker.
"""

import json
import os
from typing import Any

from sase.artifacts import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_retry_spawn import (
    ENV_RETRY_ATTEMPT,
    ENV_RETRY_CHAIN_ROOT_TIMESTAMP,
    ENV_RETRY_HANDOFF,
    ENV_RETRY_OF_TIMESTAMP,
    RetryHandoff,
)
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

__all__ = [
    "apply_retry_chain_to_meta",
    "bump_spawn_telemetry",
    "load_retry_handoff_from_env",
    "setup_artifacts_directory",
    "write_agent_meta",
    "write_home_running_marker",
]


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


def write_agent_meta(artifacts_dir: str, agent_meta: dict[str, Any]) -> None:
    write_agent_meta_atomic(
        artifacts_dir,
        agent_meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
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
