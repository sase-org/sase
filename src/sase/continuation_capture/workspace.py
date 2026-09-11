"""Workspace-facts capture and execution identity helpers."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import time
from typing import TYPE_CHECKING, Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

from ._constants import WORKSPACE_FACTS_FILENAME
from ._storage import (
    continuation_root,
    local_ref,
    read_json_object,
    safe_identifier,
    sha_text,
    update_agent_meta_fields,
    write_json_atomic,
    record_capture_error,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


def persist_workspace_facts_best_effort(
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Persist host/workspace facts before an agent turn can terminate."""

    try:
        return persist_workspace_facts(ctx, state)
    except Exception as exc:
        record_capture_error(ctx.artifacts_dir, "workspace_facts", exc)
        return None


def persist_workspace_facts(ctx: AgentExecContext, state: LoopState) -> str:
    """Persist a local workspace-facts checkpoint and return its ref."""

    artifacts_dir = state.current_artifacts_dir or ctx.artifacts_dir
    root = continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    facts: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "workspace_facts",
        "project": ctx.project_name,
        "run_id": run_id(ctx, artifacts_dir),
        "agent_name": _agent_name(ctx, artifacts_dir),
        "cwd": os.getcwd(),
        "workspace_dir": ctx.workspace_dir,
        "workspace_num": ctx.workspace_num,
        "current_artifacts_dir": state.current_artifacts_dir,
        "root_artifacts_dir": ctx.artifacts_dir,
        "cl_name": ctx.cl_name,
        "vcs_tag": ctx.vcs_tag,
        "prompt_sha256": sha_text(state.current_prompt),
        "recorded_at_epoch": time.time(),
    }
    try:
        facts["machine_name"] = socket.gethostname()
    except OSError:
        pass
    path = root / WORKSPACE_FACTS_FILENAME
    workspace_ref = local_ref(WORKSPACE_FACTS_FILENAME)
    write_json_atomic(path, facts)
    update_agent_meta_fields(
        artifacts_dir,
        {
            "continuation_workspace_ref": workspace_ref,
            "continuation_workspace_facts_path": str(path),
        },
    )
    state.continuation_workspace_ref = workspace_ref
    return workspace_ref


def owner(
    ctx: AgentExecContext,
    artifacts_dir: str | os.PathLike[str],
) -> dict[str, str]:
    owner = {
        "project": safe_identifier(ctx.project_name or "unknown"),
        "run_id": safe_identifier(run_id(ctx, artifacts_dir)),
        "agent_name": safe_identifier(_agent_name(ctx, artifacts_dir)),
        "workspace_id": safe_identifier(str(ctx.workspace_num)),
    }
    try:
        owner["machine_name"] = safe_identifier(socket.gethostname())
    except OSError:
        pass
    return owner


def run_id(ctx: AgentExecContext, artifacts_dir: str | os.PathLike[str]) -> str:
    value = ctx.artifacts_timestamp or Path(artifacts_dir).name
    return str(value or "run")


def _agent_name(
    ctx: AgentExecContext,
    artifacts_dir: str | os.PathLike[str],
) -> str:
    if ctx.agent_name:
        return ctx.agent_name
    meta = read_json_object(Path(artifacts_dir) / "agent_meta.json")
    name = meta.get("name")
    if isinstance(name, str) and name:
        return name
    return "agent"


__all__ = [
    "persist_workspace_facts",
    "persist_workspace_facts_best_effort",
]
