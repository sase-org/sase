"""Antigravity conversation trajectory extraction helpers."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._tool_call_agy import (
    AgyTrajectoryStep,
    agy_trajectory_status_is_pending,
    agy_trajectory_step_is_tool_result,
    agy_trajectory_step_tool_name,
    normalize_agy_trajectory_steps,
)
from ._tool_call_io import append_jsonl, append_tool_call_collector_diagnostic

_SUPPORTED_AGY_TRAJECTORY_VERSIONS = frozenset({"1.0.10"})
_VERSION_ALLOWLIST_ENV = "SASE_AGY_TOOL_TRAJECTORY_VERSION_ALLOWLIST"
_CONVERSATIONS_DIR_ENV = "SASE_AGY_CONVERSATIONS_DIR"
_AGY_HOME_ENV_CANDIDATES = (
    "SASE_AGY_HOME",
    "ANTIGRAVITY_HOME",
    "AGY_HOME",
)
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


@dataclass(frozen=True)
class _AgyConversationSnapshot:
    """Pre-run Antigravity conversation DB state."""

    conversations_dir: Path
    cache_dir: Path
    cwd: str
    db_mtimes_ns: MappingPathMtimes
    db_max_indices: MappingPathMaxIndices


@dataclass(frozen=True)
class AgyTurnProgress:
    """Structural progress signal decoded from an Antigravity trajectory diff."""

    no_progress: bool
    reason: str
    tool_use_count: int


MappingPathMtimes = dict[Path, int]
MappingPathMaxIndices = dict[Path, int]


def prepare_agy_tool_call_extraction(
    agy_bin: str,
    *,
    cwd: str | None = None,
    artifacts_dir: str | None = None,
) -> _AgyConversationSnapshot | None:
    """Return a pre-run snapshot if trajectory extraction is enabled."""
    artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    if not _agy_version_supports_trajectory(agy_bin):
        return None

    conversations_dir = _agy_conversations_dir()
    cache_dir = conversations_dir.parent / "cache"
    return _snapshot_agy_conversations(
        conversations_dir=conversations_dir,
        cache_dir=cache_dir,
        cwd=cwd or os.getcwd(),
    )


def _snapshot_agy_conversations(
    *,
    conversations_dir: Path | None = None,
    cache_dir: Path | None = None,
    cwd: str | None = None,
) -> _AgyConversationSnapshot:
    """Snapshot Antigravity conversation DB mtimes before an ``agy`` run."""
    resolved_conversations_dir = conversations_dir or _agy_conversations_dir()
    return _AgyConversationSnapshot(
        conversations_dir=resolved_conversations_dir,
        cache_dir=cache_dir or resolved_conversations_dir.parent / "cache",
        cwd=str(Path(cwd or os.getcwd()).resolve()),
        db_mtimes_ns=_conversation_db_mtimes(resolved_conversations_dir),
        db_max_indices=_conversation_db_max_indices(resolved_conversations_dir),
    )


def append_agy_tool_call_events(
    snapshot: _AgyConversationSnapshot | None,
    *,
    artifacts_dir: str | None = None,
) -> int:
    """Append decoded Antigravity trajectory tool rows to ``tool_calls.jsonl``.

    This is intentionally best-effort. Any private-format, SQLite, association,
    or filesystem failure is recorded as a writer diagnostic when possible and
    never raised into the provider invocation path.
    """
    artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if snapshot is None or not artifacts_dir:
        return 0

    try:
        db_paths = _resolve_agy_conversation_dbs(snapshot)
        written = 0
        for db_path in db_paths:
            steps = _read_agy_trajectory_steps(
                db_path,
                after_idx=snapshot.db_max_indices.get(db_path),
            )
            records = normalize_agy_trajectory_steps(
                steps,
                conversation_id=db_path.stem,
                cwd=snapshot.cwd,
            )
            for record in records:
                append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
                written += 1
        return written
    except Exception as exc:
        append_tool_call_collector_diagnostic(
            artifacts_dir,
            reason="agy_trajectory_extraction_failed",
            raw_preview=str(exc),
        )
        return 0


def analyze_agy_turn_progress(
    snapshot: _AgyConversationSnapshot | None,
) -> AgyTurnProgress | None:
    """Return a structural no-progress signal for one ``agy --print`` turn.

    The helper is best-effort like artifact extraction. When the private
    trajectory data cannot be decoded confidently, callers should fall back to
    text classification rather than fail the provider invocation.
    """
    if snapshot is None:
        return None

    try:
        db_paths = _resolve_agy_conversation_dbs(snapshot)
        if not db_paths:
            return AgyTurnProgress(
                no_progress=True,
                reason="trajectory_no_tool_steps",
                tool_use_count=0,
            )

        steps: list[AgyTrajectoryStep] = []
        for db_path in db_paths:
            steps.extend(
                _read_agy_trajectory_steps(
                    db_path,
                    after_idx=snapshot.db_max_indices.get(db_path),
                )
            )
        return _analyze_agy_trajectory_steps_progress(steps)
    except Exception:
        return None


def _analyze_agy_trajectory_steps_progress(
    steps: list[AgyTrajectoryStep],
) -> AgyTurnProgress:
    tool_use_count = 0
    current_tool_name: str | None = None
    last_tool_pending_run_command = False

    for step in sorted(steps, key=lambda item: item.idx):
        tool_name = agy_trajectory_step_tool_name(step)
        if tool_name:
            tool_use_count += 1
            current_tool_name = tool_name
            last_tool_pending_run_command = tool_name == "run_command"
            continue

        if current_tool_name is not None and agy_trajectory_step_is_tool_result(step):
            last_tool_pending_run_command = (
                current_tool_name == "run_command"
                and agy_trajectory_status_is_pending(step.status)
            )
            current_tool_name = None

    if tool_use_count == 0:
        return AgyTurnProgress(
            no_progress=True,
            reason="trajectory_no_tool_steps",
            tool_use_count=0,
        )

    if last_tool_pending_run_command:
        return AgyTurnProgress(
            no_progress=True,
            reason="trajectory_pending_run_command",
            tool_use_count=tool_use_count,
        )

    return AgyTurnProgress(
        no_progress=False,
        reason="trajectory_progress",
        tool_use_count=tool_use_count,
    )


def _resolve_agy_conversation_dbs(snapshot: _AgyConversationSnapshot) -> list[Path]:
    """Resolve DBs touched by the run represented by *snapshot*."""
    touched = _touched_conversation_dbs(snapshot)
    if not touched:
        return []

    cwd_conversation_id = _cwd_conversation_id(snapshot.cache_dir, snapshot.cwd)
    if cwd_conversation_id:
        matching = [path for path in touched if path.stem == cwd_conversation_id]
        if matching:
            return sorted(matching, key=_mtime_ns)
        # A cwd map exists but points elsewhere, so do not risk cross-run data.
        return []

    return sorted(touched, key=_mtime_ns)


def _read_agy_trajectory_steps(
    db_path: Path,
    *,
    after_idx: int | None = None,
) -> list[AgyTrajectoryStep]:
    """Read Antigravity trajectory steps from *db_path* in SQLite read-only mode."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        if after_idx is None:
            rows = conn.execute(
                "SELECT idx, step_type, status, step_payload FROM steps ORDER BY idx"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT idx, step_type, status, step_payload "
                "FROM steps WHERE idx > ? ORDER BY idx",
                (after_idx,),
            ).fetchall()

    steps: list[AgyTrajectoryStep] = []
    for idx, step_type, status, step_payload in rows:
        payload = bytes(step_payload or b"")
        steps.append(
            AgyTrajectoryStep(
                idx=int(idx),
                step_type=_int_or_none(step_type),
                status=_int_or_none(status),
                step_payload=payload,
            )
        )
    return steps


def _agy_conversations_dir() -> Path:
    """Return the Antigravity conversations directory."""
    override = os.environ.get(_CONVERSATIONS_DIR_ENV)
    if override:
        return Path(override).expanduser()

    for env_name in _AGY_HOME_ENV_CANDIDATES:
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser() / "conversations"

    return Path.home() / ".gemini" / "antigravity-cli" / "conversations"


def _conversation_db_mtimes(conversations_dir: Path) -> MappingPathMtimes:
    if not conversations_dir.is_dir():
        return {}
    mtimes: MappingPathMtimes = {}
    for path in conversations_dir.glob("*.db"):
        try:
            mtimes[path.resolve()] = path.stat().st_mtime_ns
        except OSError:
            continue
    return mtimes


def _conversation_db_max_indices(conversations_dir: Path) -> MappingPathMaxIndices:
    if not conversations_dir.is_dir():
        return {}
    max_indices: MappingPathMaxIndices = {}
    for path in conversations_dir.glob("*.db"):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        max_idx = _conversation_db_max_idx(resolved)
        if max_idx is not None:
            max_indices[resolved] = max_idx
    return max_indices


def _conversation_db_max_idx(db_path: Path) -> int | None:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute("SELECT MAX(idx) FROM steps").fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None or not isinstance(row[0], int):
        return None
    return row[0]


def _touched_conversation_dbs(snapshot: _AgyConversationSnapshot) -> list[Path]:
    current = _conversation_db_mtimes(snapshot.conversations_dir)
    touched: list[Path] = []
    for path, mtime_ns in current.items():
        previous = snapshot.db_mtimes_ns.get(path)
        if previous is None or mtime_ns != previous:
            touched.append(path)
    return touched


def _cwd_conversation_id(cache_dir: Path, cwd: str) -> str | None:
    path = cache_dir / "last_conversations.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    cwd_candidates = {cwd, str(Path(cwd).resolve())}
    return _find_cwd_conversation_id(data, cwd_candidates)


def _find_cwd_conversation_id(value: Any, cwd_candidates: set[str]) -> str | None:
    if isinstance(value, dict):
        for cwd in cwd_candidates:
            direct = value.get(cwd)
            conversation_id = _conversation_id_from_value(direct)
            if conversation_id:
                return conversation_id

        if _value_matches_cwd(value, cwd_candidates):
            conversation_id = _conversation_id_from_value(value)
            if conversation_id:
                return conversation_id

        for nested in value.values():
            conversation_id = _find_cwd_conversation_id(nested, cwd_candidates)
            if conversation_id:
                return conversation_id
    elif isinstance(value, list):
        for nested in value:
            conversation_id = _find_cwd_conversation_id(nested, cwd_candidates)
            if conversation_id:
                return conversation_id
    return None


def _conversation_id_from_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return _conversation_id_from_text(value)
    if isinstance(value, dict):
        for key in (
            "conversation_id",
            "conversationId",
            "id",
            "last_conversation",
            "lastConversation",
        ):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return _conversation_id_from_text(candidate)
    return None


def _conversation_id_from_text(value: str) -> str:
    return Path(value).stem if value.endswith(".db") or "/" in value else value


def _value_matches_cwd(value: dict[Any, Any], cwd_candidates: set[str]) -> bool:
    for key in ("cwd", "workspace", "workspace_dir", "workspaceDir", "path"):
        candidate = value.get(key)
        if (
            isinstance(candidate, str)
            and str(Path(candidate).resolve()) in cwd_candidates
        ):
            return True
    return False


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _agy_version_supports_trajectory(agy_bin: str) -> bool:
    allowlist = _configured_version_allowlist()
    if "*" in allowlist:
        return True

    version = _agy_version(agy_bin)
    if not version:
        return False
    return version in allowlist


def _configured_version_allowlist() -> frozenset[str]:
    raw = os.environ.get(_VERSION_ALLOWLIST_ENV)
    if not raw:
        return _SUPPORTED_AGY_TRAJECTORY_VERSIONS
    values = frozenset(value.strip() for value in raw.split(",") if value.strip())
    return values or _SUPPORTED_AGY_TRAJECTORY_VERSIONS


@lru_cache(maxsize=8)
def _agy_version(agy_bin: str) -> str | None:
    try:
        completed = subprocess.run(
            [agy_bin, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    output = f"{completed.stdout}\n{completed.stderr}"
    match = _VERSION_RE.search(output)
    return match.group(1) if match else None


__all__ = [
    "AgyTurnProgress",
    "analyze_agy_turn_progress",
    "append_agy_tool_call_events",
    "prepare_agy_tool_call_extraction",
]
