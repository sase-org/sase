"""Shared builders for continuation replay hydration tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_continuation_replay_hydration_*`` split modules can share
them without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.continuation_capture import (
    persist_agent_delta,
    persist_monitor_result,
    record_prepared_prompt_capture,
)
from sase.continuation_capture.models import ContinuationPublishResult
from tests.history.test_continuation_replay import (
    _agent_member,
    _monitor_member,
    _write_agent_node,
    _write_json,
    _write_monitor_result_node,
)

ORIGINAL_CONSTRAINT_SENTINEL = "ORIGINAL_CONSTRAINT_SENTINEL"


def agent_member(tmp_path: Path, suffix: str, name: str) -> dict[str, object]:
    """Build an agent session member pointing at *suffix* artifacts."""
    return _agent_member(tmp_path, suffix, name)


def monitor_member(
    artifacts_dir: Path,
    *,
    name: str = "acme--mon",
    log_tail: str = "SECRET_MONITOR_TAIL\n",
    next_output: str = "tail",
    status: str = "failed",
    exit_code: int | None = 7,
) -> dict[str, object]:
    """Build a monitor proc member for *artifacts_dir*."""
    return _monitor_member(
        artifacts_dir,
        name=name,
        log_tail=log_tail,
        next_output=next_output,
        status=status,
        exit_code=exit_code,
    )


def write_agent_node(
    artifacts_dir: Path,
    *,
    name: str,
    node_id: str,
    parents: Sequence[str] = (),
    prompt: str,
    response: str | None,
    checkpoint: Mapping[str, Any] | None = None,
) -> None:
    """Write an agent-delta node plus manifest and ``agent_meta.json``."""
    _write_agent_node(
        artifacts_dir,
        name=name,
        node_id=node_id,
        parents=parents,
        prompt=prompt,
        response=response,
        checkpoint=checkpoint,
    )


def write_json(path: Path, payload: Mapping[str, Any]) -> str:
    """Write *payload* as sorted JSON and return its sha256 hex digest."""
    return _write_json(path, payload)


def write_monitor_result_node(
    artifacts_dir: Path,
    *,
    parents: Sequence[str] = (),
    next_output: str = "tail",
    status: str = "failed",
    exit_code: int | None = 7,
) -> None:
    """Write a monitor-result node for prefix-reset and replay tests."""
    _write_monitor_result_node(
        artifacts_dir,
        parents=parents,
        next_output=next_output,
        status=status,
        exit_code=exit_code,
    )


def publish_agent_delta(
    tmp_path: Path,
    artifacts_dir: Path,
    *,
    name: str,
    prompt: str,
    response: str,
    parents: Sequence[str] = (),
    status: str = "completed",
    segments: Sequence[Any] = (),
) -> ContinuationPublishResult:
    """Publish an agent delta through the production capture path."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "continuation_parent_node_ids": list(parents),
    }
    _write_json(artifacts_dir / "agent_meta.json", meta)
    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp=artifacts_dir.name,
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts_dir),
        artifacts_timestamp=artifacts_dir.name,
        vcs_tag=None,
        agent_name=name,
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta=dict(meta),
        local_macros={},
    )
    record_prepared_prompt_capture(
        artifacts_dir,
        authored_local_request=prompt,
        materialized_prompt=prompt,
        segments=segments,
        update_meta=False,
    )
    state = LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=str(artifacts_dir),
        loop_outcome="completed" if status == "completed" else status,
        sdd_spec_path=None,
        original_prompt=prompt,
    )
    return persist_agent_delta(
        ctx,
        state,
        status=status,  # type: ignore[arg-type]
        final_response=response,
    )


def publish_monitor(
    artifacts_dir: Path,
    *,
    parents: Sequence[str],
    starter_artifacts_dir: Path | None = None,
    status: str = "completed",
    exit_code: int = 0,
    next_output: str = "none",
) -> str:
    """Publish a monitor result through the production capture path."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "name": f"chain--mon-{artifacts_dir.name}",
        "monitor_id": f"mon-{artifacts_dir.name}",
        "monitor_command": "just check",
        "monitor_execution_argv": ["just", "check"],
        "monitor_cwd": "/workspace/acme",
        "monitor_next_output": next_output,
        "monitor_state": status,
        "monitor_next_action": "continue the work",
        "run_started_at": "2026-09-11T10:00:00Z",
        "workspace_dir": "/workspace/acme",
        "workspace_num": 1,
        "continuation_parent_node_ids": list(parents),
        "project_name": "proj",
    }
    if starter_artifacts_dir is not None:
        meta["monitor_starter_artifacts_dir"] = str(starter_artifacts_dir)
        meta["monitor_starter_agent"] = "starter"
    published = persist_monitor_result(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state=status,
        exit_code=exit_code,
        elapsed_seconds=1.0,
        stopped_at="2026-09-11T10:00:01Z",
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "/tmp/monitor.log",
            "total_observed_bytes": 12,
            "retained_ranges": [{"start": 0, "end": 12}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    _write_json(artifacts_dir / "agent_meta.json", meta)
    return published.node_id
