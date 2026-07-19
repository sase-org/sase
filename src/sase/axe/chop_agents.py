"""Durable registry for agents launched from axe chops."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.paths import sase_subdir
from sase.core.time import get_timezone

from . import state

ENV_CHOP_LUMBERJACK = "SASE_CHOP_LUMBERJACK"
ENV_CHOP_NAME = "SASE_CHOP_NAME"
ENV_CHOP_RUN_ID = "SASE_CHOP_RUN_ID"
ENV_CHOP_PROMPT_HASH = "SASE_CHOP_PROMPT_HASH"

_PROCESS_REGISTRY_LOCKS: dict[Path, threading.RLock] = {}
_PROCESS_REGISTRY_LOCKS_GUARD = threading.Lock()


def is_chop_launch_env(env: Mapping[str, str] | None) -> bool:
    """Return whether an environment marks a machine-generated chop launch."""
    return bool(env and env.get(ENV_CHOP_NAME))


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


def _prompt_hash(prompt: str) -> str:
    """Return a stable hash for a prompt after whitespace normalization."""
    normalized = "\n".join(line.rstrip() for line in prompt.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_chop_launch_env(
    *,
    lumberjack_name: str,
    chop_name: str,
    prompt: str | None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Build env vars that identify a chop-launched agent.

    The script runner supplies these values so later runner-owned proposal
    launches can reuse the durable chop-agent linkage.
    """
    env = {
        ENV_CHOP_LUMBERJACK: lumberjack_name,
        ENV_CHOP_NAME: chop_name,
        ENV_CHOP_RUN_ID: run_id or uuid.uuid4().hex,
    }
    if prompt is not None:
        env[ENV_CHOP_PROMPT_HASH] = _prompt_hash(prompt)
    return env


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
    default_dir = sase_subdir("axe") / "lumberjacks"
    if jack_state_dir == default_dir:
        jack_state_dir = default_dir
    return jack_state_dir / lumberjack_name / "agent_chops.json"


def _process_registry_lock(lock_path: Path) -> threading.RLock:
    with _PROCESS_REGISTRY_LOCKS_GUARD:
        lock = _PROCESS_REGISTRY_LOCKS.get(lock_path)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_REGISTRY_LOCKS[lock_path] = lock
        return lock


@contextmanager
def _registry_lock(lumberjack_name: str) -> Iterator[None]:
    path = _registry_path(lumberjack_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    process_lock = _process_registry_lock(lock_path)
    with process_lock:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_records_unlocked(lumberjack_name: str) -> list[_ChopAgentRecord]:
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


def _write_records_unlocked(
    lumberjack_name: str, records: list[_ChopAgentRecord]
) -> None:
    path = _registry_path(lumberjack_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([asdict(record) for record in records], f, indent=2)
            f.write("\n")
        os.replace(temp_path, path)
        replaced = True
    finally:
        if temp_path is not None and not replaced:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def get_chop_agent_records(
    lumberjack_name: str,
    *,
    chop_name: str | None = None,
    run_id: str | None = None,
) -> list[_ChopAgentRecord]:
    """Return durable records without discarding completed agents.

    Lifecycle housekeeping needs completed records long enough to inspect
    their immutable ``done.json`` markers, so this query never deletes
    terminal linkage.
    """
    with _registry_lock(lumberjack_name):
        records = _read_records_unlocked(lumberjack_name)
    if chop_name is not None:
        records = [record for record in records if record.chop_name == chop_name]
    if run_id is not None:
        records = [record for record in records if record.run_id == run_id]
    return records


def remove_chop_agent_records(
    lumberjack_name: str,
    *,
    chop_name: str,
    run_id: str,
) -> None:
    """Remove linkage after a launched chop run reaches terminal state."""
    with _registry_lock(lumberjack_name):
        records = _read_records_unlocked(lumberjack_name)
        kept = [
            record
            for record in records
            if not (record.chop_name == chop_name and record.run_id == run_id)
        ]
        if kept != records:
            _write_records_unlocked(lumberjack_name, kept)


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
        prompt_hash=prompt_hash_value or _prompt_hash(prompt),
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

    with _registry_lock(lumberjack_name):
        records = [
            existing
            for existing in _read_records_unlocked(lumberjack_name)
            if existing.pid != pid
        ]
        records.append(record)
        _write_records_unlocked(lumberjack_name, records)
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
