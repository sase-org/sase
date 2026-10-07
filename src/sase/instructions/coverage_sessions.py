"""Observable root sessions and their start timestamps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.instructions import _runs as runs


def parse_time(value: object) -> datetime | None:
    """Parse an ISO timestamp or epoch to UTC, or ``None``."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first_json_timestamp(path: Path, *, max_lines: int = 10) -> datetime | None:
    """Return the first ``timestamp`` field in a JSONL file, or ``None``."""
    try:
        with open(path, encoding="utf-8") as stream:
            for _ in range(max_lines):
                line = stream.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for key in ("timestamp", "build_timestamp_utc"):
                    parsed = parse_time(event.get(key))
                    if parsed is not None:
                        return parsed
    except OSError:
        return None
    return None


def claude_session_start(session_path: Path) -> datetime | None:
    """Return a Claude root transcript's first event timestamp."""
    return _first_json_timestamp(session_path)


def codex_session_start(rollout_path: Path) -> datetime | None:
    """Return a Codex rollout's ``session_meta`` timestamp."""
    try:
        with open(rollout_path, encoding="utf-8") as stream:
            first = stream.readline()
    except OSError:
        return None
    try:
        event = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    payload = event.get("payload")
    if isinstance(payload, dict):
        parsed = parse_time(payload.get("timestamp"))
        if parsed is not None:
            return parsed
    return _first_json_timestamp(rollout_path)


def grok_session_start(session_dir: Path) -> datetime | None:
    """Return a Grok session dir's build timestamp (mtime fallback)."""
    context = runs.read_json_object(session_dir / "prompt_context.json")
    parsed = parse_time(context.get("build_timestamp_utc"))
    if parsed is not None:
        return parsed
    try:
        return datetime.fromtimestamp(session_dir.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def muse_session_start(log_path: Path) -> datetime | None:
    """Return a Muse session log's first timestamp (mtime fallback)."""
    found = _first_json_timestamp(log_path)
    if found is not None:
        return found
    try:
        return datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


@dataclass(frozen=True)
class RootSession:
    """One observable root session and its start."""

    provider: str
    run_name: str
    artifact_dir: str
    workspace_dir: str
    session_id: str
    session_start: datetime | None
    partial: bool = False


def root_sessions(scored_runs: list[runs.ScoredRun]) -> list[RootSession]:
    """List observable root sessions with starts for *scored_runs*."""
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    found: list[RootSession] = []
    for run in scored_runs:
        if run.provider == "claude":
            for path in runs.find_claude_sessions(run):
                found.append(
                    RootSession(
                        provider="claude",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=path.stem,
                        session_start=claude_session_start(path),
                    )
                )
        elif run.provider == "codex":
            for path in runs.find_codex_sessions(run):
                found.append(
                    RootSession(
                        provider="codex",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=path.stem,
                        session_start=codex_session_start(path),
                    )
                )
        elif run.provider == "grok":
            for directory in runs.find_grok_sessions(run):
                found.append(
                    RootSession(
                        provider="grok",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=directory.name,
                        session_start=grok_session_start(directory),
                    )
                )
        elif run.provider == "muse":
            session_id = runs.find_muse_session_id(run)
            if session_id is None:
                continue
            log_path = find_muse_session_log(session_id)
            found.append(
                RootSession(
                    provider="muse",
                    run_name=run.name,
                    artifact_dir=run.artifact_dir,
                    workspace_dir=run.workspace_dir,
                    session_id=session_id,
                    session_start=(
                        muse_session_start(log_path) if log_path is not None else None
                    ),
                )
            )
    return found


__all__ = [
    "RootSession",
    "claude_session_start",
    "codex_session_start",
    "grok_session_start",
    "muse_session_start",
    "parse_time",
    "root_sessions",
]
