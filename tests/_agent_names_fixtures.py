"""Shared helpers for sase.agent.names tests.

Not a conftest so files opt in by importing the helpers directly.
"""

import json
from pathlib import Path

# A PID that is guaranteed not to exist (beyond kernel PID_MAX_LIMIT)
DEAD_PID = 99_999_999


def make_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    *,
    done: bool = False,
    outcome: str | None = None,
    pid: int | None = None,
    appears_as_agent: bool | None = None,
    parent_timestamp: str | None = None,
    plan_chain_parent_timestamp: str | None = None,
    role_suffix: str | None = None,
    workflow_name: str | None = None,
) -> Path:
    """Create a fake agent artifact directory with agent_meta.json."""
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name, "model": "test"}
    if pid is not None:
        meta["pid"] = pid
    if parent_timestamp is not None:
        meta["parent_timestamp"] = parent_timestamp
    if plan_chain_parent_timestamp is not None:
        meta["plan_chain_parent_timestamp"] = plan_chain_parent_timestamp
    if role_suffix is not None:
        meta["role_suffix"] = role_suffix
    if workflow_name is not None:
        meta["workflow_name"] = workflow_name
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if done:
        done_data: dict[str, object] = {}
        if outcome:
            done_data["outcome"] = outcome
        (artifact_dir / "done.json").write_text(json.dumps(done_data))
    if appears_as_agent is not None:
        wf_data: dict[str, object] = {
            "workflow_name": "test",
            "appears_as_agent": appears_as_agent,
        }
        (artifact_dir / "workflow_state.json").write_text(json.dumps(wf_data))
    return artifact_dir
