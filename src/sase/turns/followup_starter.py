"""Starter-settlement waits and fork-target helpers for turn follow-ups."""

from __future__ import annotations

import json
import time
from pathlib import Path

from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.plan_chain import (
    AGENT_SESSION_ROLE_KEY,
    LEGACY_AGENT_FAMILY_ROLE_KEY,
    agent_session_base,
)

#: How long to wait for the starter's own ``done.json`` before composing the
#: follow-up prompt without a ``#fork:`` prefix.
DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS = 60.0
STARTER_SETTLE_POLL_SECONDS = 0.5


def fork_target_for_settled_starter(
    *,
    starter_name: str | None,
    agent_session_name: str | None,
    settled: bool,
    prefer_exact_starter: bool = False,
) -> str | None:
    """Return the transcript target a settled follow-up should fork."""
    if not settled:
        return None
    starter = _clean_str(starter_name)
    if prefer_exact_starter and starter:
        return starter
    agent_session = _clean_str(agent_session_name)
    if agent_session:
        return agent_session
    if not starter:
        return None
    return agent_session_base(starter) or starter


def starter_identity(
    project_name: str,
    parent_timestamp: object,
) -> tuple[str | None, str | None]:
    """Return ``(starter_name, starter_role)`` for a parent timestamp."""
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return None, None
    return (
        _read_meta_str(starter_dir, "name"),
        _read_meta_str(starter_dir, AGENT_SESSION_ROLE_KEY),
    )


def wait_for_starter_artifacts_dir(
    starter_artifacts_dir: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = STARTER_SETTLE_POLL_SECONDS,
) -> bool:
    """Poll a known starter artifacts directory for its terminal marker."""
    done_path = Path(starter_artifacts_dir) / "done.json"
    deadline = time.monotonic() + timeout_seconds
    while not done_path.exists() and time.monotonic() < deadline:
        time.sleep(poll_seconds)
    return done_path.exists()


def wait_for_starter(
    project_name: str,
    parent_timestamp: object,
    *,
    timeout_seconds: float,
    poll_seconds: float = STARTER_SETTLE_POLL_SECONDS,
) -> bool:
    """Poll for the starter's terminal marker before forking its chat."""
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return False
    return wait_for_starter_artifacts_dir(
        starter_dir, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds
    )


def wait_for_followup_started(
    artifacts_dir: str,
    pid: int | None,
    *,
    timeout_seconds: float = DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    poll_seconds: float = STARTER_SETTLE_POLL_SECONDS,
) -> bool:
    """Poll for a launched follow-up to claim its runner slot."""
    artifacts_path = Path(artifacts_dir)
    done_path = artifacts_path / "done.json"
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    interval = max(0.01, poll_seconds)

    while True:
        if _meta_has_run_started_at(artifacts_path):
            return True
        if done_path.exists():
            return False
        if pid is not None and not _pid_is_running(pid):
            return _meta_has_run_started_at(artifacts_path)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))


def _starter_artifacts_dir(project_name: str, parent_timestamp: object) -> str | None:
    """Return the starter artifact path for *parent_timestamp*, if valid."""
    if not isinstance(parent_timestamp, str) or not parent_timestamp:
        return None
    return str(canonical_agent_artifact_path(project_name, "ace-run", parent_timestamp))


def _meta_has_run_started_at(artifacts_dir: Path) -> bool:
    """Return whether an artifact meta file has recorded runner startup."""
    meta_path = artifacts_dir / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return False
    return bool(data.get("run_started_at")) if isinstance(data, dict) else False


def _pid_is_running(pid: int) -> bool:
    from sase.ace.hooks.processes import is_process_running

    return is_process_running(pid)


def _read_meta_str(artifacts_dir: str, key: str) -> str | None:
    """Read one string key from an artifact's ``agent_meta.json``."""
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    if value is None and key == AGENT_SESSION_ROLE_KEY and isinstance(data, dict):
        # legacy agent-family spelling: pre-rename agent_meta.json files.
        value = data.get(LEGACY_AGENT_FAMILY_ROLE_KEY)
    return value if isinstance(value, str) and value else None


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "STARTER_SETTLE_POLL_SECONDS",
    "fork_target_for_settled_starter",
    "starter_identity",
    "wait_for_followup_started",
    "wait_for_starter",
    "wait_for_starter_artifacts_dir",
]
