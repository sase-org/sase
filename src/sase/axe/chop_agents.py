"""Durable registry for agents launched from axe chops."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.time import get_timezone

from . import state

ENV_CHOP_LUMBERJACK = "SASE_CHOP_LUMBERJACK"
ENV_CHOP_NAME = "SASE_CHOP_NAME"
ENV_CHOP_RUN_ID = "SASE_CHOP_RUN_ID"
ENV_CHOP_PROMPT_HASH = "SASE_CHOP_PROMPT_HASH"


@dataclass(frozen=True)
class _ChopAgentRecord:
    """One agent process launched by a lumberjack chop."""

    lumberjack_name: str
    chop_name: str
    prompt_hash: str
    pid: int
    project_file: str
    project_name: str
    workspace_num: int
    workflow_name: str
    cl_name: str
    artifacts_timestamp: str
    started_at: str
    run_id: str = ""


def prompt_hash(prompt: str) -> str:
    """Return a stable hash for a prompt after whitespace normalization."""
    normalized = "\n".join(line.rstrip() for line in prompt.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chop_agent_env_from_process_env(
    env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Extract chop launch metadata from an environment mapping."""
    source = os.environ if env is None else env
    lumberjack_name = source.get(ENV_CHOP_LUMBERJACK)
    chop_name = source.get(ENV_CHOP_NAME)
    run_id = source.get(ENV_CHOP_RUN_ID)
    if not lumberjack_name or not chop_name or not run_id:
        return None
    result = {
        "lumberjack_name": lumberjack_name,
        "chop_name": chop_name,
        "run_id": run_id,
    }
    if source.get(ENV_CHOP_PROMPT_HASH):
        result["prompt_hash"] = source[ENV_CHOP_PROMPT_HASH]
    return result


def agent_meta_from_chop_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return agent_meta.json fields corresponding to chop env metadata."""
    metadata = _chop_agent_env_from_process_env(env)
    if metadata is None:
        return {}
    meta = {
        "chop_lumberjack": metadata["lumberjack_name"],
        "chop_name": metadata["chop_name"],
        "chop_run_id": metadata["run_id"],
    }
    prompt_hash_value = metadata.get("prompt_hash")
    if prompt_hash_value:
        meta["chop_prompt_hash"] = prompt_hash_value
    return meta


def _registry_path(lumberjack_name: str) -> Path:
    jack_state_dir = state.JACK_STATE_DIR
    default_dir = Path.home() / ".sase" / "axe" / "lumberjacks"
    if jack_state_dir == default_dir:
        jack_state_dir = Path("~/.sase/axe/lumberjacks").expanduser()
    return jack_state_dir / lumberjack_name / "agent_chops.json"


def _read_records(lumberjack_name: str) -> list[_ChopAgentRecord]:
    path = _registry_path(lumberjack_name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []

    records: list[_ChopAgentRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            records.append(_ChopAgentRecord(**item))
        except (TypeError, ValueError):
            continue
    return records


def _write_records(lumberjack_name: str, records: list[_ChopAgentRecord]) -> None:
    path = _registry_path(lumberjack_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(record) for record in records], f, indent=2)
    temp_path.replace(path)


def _artifacts_dir(record: _ChopAgentRecord) -> Path | None:
    if not record.project_name or not record.artifacts_timestamp:
        return None
    return (
        Path("~/.sase/projects").expanduser()
        / record.project_name
        / "artifacts"
        / "ace-run"
        / record.artifacts_timestamp
    )


def _has_done_marker(record: _ChopAgentRecord) -> bool:
    artifacts_dir = _artifacts_dir(record)
    return bool(artifacts_dir and (artifacts_dir / "done.json").exists())


def _is_live_record(record: _ChopAgentRecord) -> bool:
    return is_process_running(record.pid) and not _has_done_marker(record)


def _prune_chop_agent_records(lumberjack_name: str) -> list[_ChopAgentRecord]:
    """Drop dead or completed records and return the remaining live records."""
    records = _read_records(lumberjack_name)
    live = [record for record in records if _is_live_record(record)]
    if live != records:
        _write_records(lumberjack_name, live)
    return live


def get_live_chop_agent_records(
    lumberjack_name: str,
    *,
    chop_name: str | None = None,
    prompt_hash_value: str | None = None,
) -> list[_ChopAgentRecord]:
    """Return live registry records, optionally filtered by chop/prompt."""
    records = _prune_chop_agent_records(lumberjack_name)
    if chop_name is not None:
        records = [record for record in records if record.chop_name == chop_name]
    if prompt_hash_value is not None:
        records = [
            record for record in records if record.prompt_hash == prompt_hash_value
        ]
    return records


def _record_chop_agent_launch(
    *,
    lumberjack_name: str,
    chop_name: str,
    pid: int,
    project_file: str,
    project_name: str,
    workspace_num: int,
    workflow_name: str,
    cl_name: str,
    timestamp: str,
    prompt: str = "",
    prompt_hash_value: str = "",
    run_id: str = "",
    started_at: str | None = None,
) -> _ChopAgentRecord:
    """Append or update a registry record for a chop-launched agent."""
    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    record = _ChopAgentRecord(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        prompt_hash=prompt_hash_value or prompt_hash(prompt),
        pid=pid,
        project_file=project_file,
        project_name=project_name,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        cl_name=cl_name,
        artifacts_timestamp=artifacts_timestamp,
        started_at=started_at or datetime.now(get_timezone()).isoformat(),
        run_id=run_id,
    )

    records = [
        existing
        for existing in _prune_chop_agent_records(lumberjack_name)
        if not (
            existing.pid == pid
            or (
                run_id and existing.run_id == run_id and existing.chop_name == chop_name
            )
        )
    ]
    records.append(record)
    _write_records(lumberjack_name, records)
    return record


def record_chop_agent_launch_from_env(
    *,
    pid: int,
    project_file: str,
    project_name: str,
    workspace_num: int,
    workflow_name: str,
    cl_name: str,
    timestamp: str,
    prompt: str,
    env: dict[str, str] | None = None,
) -> _ChopAgentRecord | None:
    """Record a launch when the current process is running under a chop."""
    metadata = _chop_agent_env_from_process_env(env)
    if metadata is None:
        return None
    return _record_chop_agent_launch(
        lumberjack_name=metadata["lumberjack_name"],
        chop_name=metadata["chop_name"],
        run_id=metadata["run_id"],
        prompt_hash_value=metadata.get("prompt_hash", ""),
        pid=pid,
        project_file=project_file,
        project_name=project_name,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        cl_name=cl_name,
        timestamp=timestamp,
        prompt=prompt,
    )


def record_chop_agent_launch_result(
    *,
    result: Any,
    prompt: str,
    env: dict[str, str],
) -> _ChopAgentRecord | None:
    """Record an ``AgentLaunchResult`` from chop env metadata if possible."""
    metadata = _chop_agent_env_from_process_env(env)
    if metadata is None:
        return None
    timestamp = getattr(result, "timestamp", "")
    if not isinstance(timestamp, str) or not timestamp:
        return None
    return _record_chop_agent_launch(
        lumberjack_name=metadata["lumberjack_name"],
        chop_name=metadata["chop_name"],
        run_id=metadata["run_id"],
        prompt_hash_value=metadata.get("prompt_hash", ""),
        pid=int(result.pid),
        project_file=str(getattr(result, "project_file", "")),
        project_name=str(getattr(result, "project_name", "")),
        workspace_num=int(getattr(result, "workspace_num", 0)),
        workflow_name=str(getattr(result, "workflow_name", "")),
        cl_name=str(getattr(result, "cl_name", "")),
        timestamp=timestamp,
        prompt=prompt,
    )
