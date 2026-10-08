"""Bounded run enumeration and provider session location."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_TRANSCRIPT_BYTE_CAP = 512 * 1024
HELPER_TRANSCRIPT_BYTE_CAP = 16 * 1024 * 1024

_KNOWN_PROVIDERS = ("claude", "codex", "grok", "muse", "agy")


@dataclass(frozen=True)
class ScoredRun:
    """One SASE run selected for verification."""

    provider: str
    name: str
    workspace_dir: str
    artifact_dir: str
    started_at: datetime
    ended_at: datetime | None
    project: str | None


def parse_when(value: str, *, now: datetime) -> datetime:
    """Parse ``--since``/``--until`` durations (``30m``, ``24h``) or ISO times.

    Accepted durations are ``m`` (minutes), ``h``, ``d``, and ``w`` plus ISO
    timestamps. Anything else raises ``ValueError`` for the CLI to report.
    """
    text = value.strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mhdw])", text, re.IGNORECASE)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        seconds = {
            "m": 60.0,
            "h": 3600.0,
            "d": 86400.0,
            "w": 604800.0,
        }[unit]
        return now - timedelta(seconds=amount * seconds)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"invalid --since/--until value {value!r}: "
            "expected like 30m, 24h, 7d, 2w, or an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_time(value: object) -> datetime | None:
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


def read_json_object(path: Path) -> dict[str, Any]:
    """Return the JSON object at *path*, or ``{}`` when unreadable."""
    return _read_json(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as stream:
            decoded = json.load(stream)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def enumerate_runs(
    *,
    limit_per_provider: int,
    since: datetime | None,
    until: datetime | None,
    project: str | None,
    agent: str | None,
    providers: tuple[str, ...],
) -> list[ScoredRun]:
    """Return the newest runs per provider from the bounded artifact index."""
    from sase.agent.listing_snapshot import listing_snapshot

    wanted = [p for p in providers if p in _KNOWN_PROVIDERS] or list(_KNOWN_PROVIDERS)
    # One bounded index query per wanted provider so rare providers are not
    # crowded out by the newest overall runs. Widen to the 200 cap when a
    # post-filter (agent/since/until) will discard rows after the query.
    per_query_limit = (
        200
        if (agent is not None or since is not None or until is not None)
        else limit_per_provider
    )
    candidates: list[ScoredRun] = []
    for provider in wanted:
        snapshot, _state = listing_snapshot(
            project=project,
            requested_limit=per_query_limit,
            candidate_filter={
                "kind": "equals",
                "field": "provider",
                "value": provider,
            },
        )
        for record in snapshot.records:
            meta = record.agent_meta
            record_provider = str(getattr(meta, "llm_provider", "") or "").lower()
            if record_provider not in wanted:
                continue
            artifact_dir = str(record.artifact_dir)
            disk_meta = _read_json(Path(artifact_dir) / "agent_meta.json")
            workspace_dir = str(
                disk_meta.get("workspace_dir")
                or getattr(meta, "workspace_dir", "")
                or ""
            )
            name = str(
                disk_meta.get("name") or getattr(meta, "name", "") or record.timestamp
            )
            bead_id = str(disk_meta.get("bead_id") or "")
            if agent and agent not in (name, bead_id):
                continue
            started = _parse_time(disk_meta.get("run_started_at"))
            if started is None:
                started = _parse_time(record.timestamp)
            if started is None:
                continue
            if since is not None and started < since:
                continue
            if until is not None and started > until:
                continue
            done = _read_json(Path(artifact_dir) / "done.json")
            ended = _parse_time(done.get("finished_at"))
            candidates.append(
                ScoredRun(
                    provider=record_provider,
                    name=name,
                    workspace_dir=workspace_dir,
                    artifact_dir=artifact_dir,
                    started_at=started,
                    ended_at=ended,
                    project=str(record.project_name or "") or None,
                )
            )
    candidates.sort(key=lambda run: run.started_at, reverse=True)
    per_provider: dict[str, int] = {}
    selected: list[ScoredRun] = []
    for run in candidates:
        count = per_provider.get(run.provider, 0)
        if count >= limit_per_provider:
            continue
        per_provider[run.provider] = count + 1
        selected.append(run)
    return selected


def home_h1() -> str | None:
    """Return the first H1 of the current ``~/AGENTS.md``."""
    from sase.instructions.fingerprints import first_h1

    path = Path.home() / "AGENTS.md"
    try:
        return first_h1(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def project_h1(workspace_dir: str) -> str | None:
    """Return the first H1 of the run's workspace-root ``AGENTS.md``."""
    from sase.instructions.fingerprints import first_h1

    try:
        return first_h1((Path(workspace_dir) / "AGENTS.md").read_text(encoding="utf-8"))
    except OSError:
        return None


def _claude_projects_root() -> Path:
    """Return the Claude projects root, honoring ``CLAUDE_CONFIG_DIR``."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"


def claude_project_dir(cwd: str) -> Path:
    """Return the encoded Claude project dir for *cwd*."""
    from sase.ace.tui.thinking.session_resolver import (
        encode_cwd_for_claude_project_dir,
    )

    return _claude_projects_root() / encode_cwd_for_claude_project_dir(
        cwd.rstrip("/") or cwd
    )


def _codex_sessions_root() -> Path:
    """Return the real Codex sessions root (never a per-run shadow home)."""
    from sase.llm_provider.codex import real_codex_home

    return real_codex_home() / "sessions"


def _grok_sessions_root() -> Path:
    """Return the Grok sessions root, honoring ``GROK_HOME``."""
    override = os.environ.get("GROK_HOME") or os.environ.get("SASE_GROK_HOME")
    if override:
        return Path(override).expanduser() / "sessions"
    return Path.home() / ".grok" / "sessions"


def _grok_cwd_dir(cwd: str) -> Path:
    """Return the Grok sessions dir for *cwd* (URL-encoded leaf)."""
    normalized = cwd.rstrip("/") or cwd
    return _grok_sessions_root() / urllib.parse.quote(normalized, safe="")


def _first_json_timestamp(path: Path, *, max_lines: int = 10) -> datetime | None:
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
                    parsed = _parse_time(event.get(key))
                    if parsed is not None:
                        return parsed
    except OSError:
        return None
    return None


def find_claude_sessions(run: ScoredRun) -> list[Path]:
    """Find root Claude transcripts for *run* within its time window."""
    directory = claude_project_dir(run.workspace_dir)
    if not directory.is_dir():
        return []
    end = run.ended_at or datetime.now(tz=UTC)
    matches: list[Path] = []
    try:
        candidates = list(directory.glob("*.jsonl"))
    except OSError:
        return []
    for path in candidates:
        first = _first_json_timestamp(path)
        if first is None:
            continue
        if run.started_at <= first <= end:
            matches.append(path)
    return sorted(matches)


def find_claude_helpers(session_path: Path) -> list[tuple[Path, str]]:
    """Return ``(transcript, agent_type)`` helper pairs for a root session."""
    helpers: list[tuple[Path, str]] = []
    subagents = session_path.parent / session_path.stem / "subagents"
    if not subagents.is_dir():
        return []
    try:
        transcripts = sorted(subagents.glob("agent-*.jsonl"))
    except OSError:
        return []
    for transcript in transcripts:
        agent_type = "unknown"
        meta_path = transcript.with_suffix(".json").with_name(
            transcript.stem + ".meta.json"
        )
        meta = _read_json(meta_path)
        raw_type = meta.get("agentType") or meta.get("agent_type")
        if isinstance(raw_type, str) and raw_type:
            agent_type = raw_type
        helpers.append((transcript, agent_type))
    return helpers


def find_codex_sessions(run: ScoredRun) -> list[Path]:
    """Find Codex rollouts whose ``session_meta`` matches *run*."""
    root = _codex_sessions_root()
    if not root.is_dir():
        return []
    end = run.ended_at or datetime.now(tz=UTC)
    days: set[str] = set()
    cursor = run.started_at
    while cursor.date() <= end.date():
        days.add(cursor.strftime("%Y/%m/%d"))
        cursor += timedelta(days=1)
        if len(days) > 366:
            break
    matches: list[Path] = []
    for day in sorted(days):
        directory = root / day
        if not directory.is_dir():
            continue
        try:
            rollouts = sorted(directory.glob("rollout-*.jsonl"))
        except OSError:
            continue
        for path in rollouts:
            if _codex_rollout_matches(path, run, end) and path not in matches:
                matches.append(path)
    return matches


def _codex_rollout_matches(path: Path, run: ScoredRun, end: datetime) -> bool:
    try:
        with open(path, encoding="utf-8") as stream:
            first = stream.readline()
    except OSError:
        return False
    try:
        event = json.loads(first)
    except json.JSONDecodeError:
        return False
    if not isinstance(event, dict) or event.get("type") != "session_meta":
        return False
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return False
    rollout_cwd = str(payload.get("cwd", "")).rstrip("/") or str(payload.get("cwd", ""))
    if rollout_cwd != (run.workspace_dir.rstrip("/") or run.workspace_dir):
        return False
    started = _parse_time(payload.get("timestamp"))
    return started is not None and run.started_at <= started <= end


def find_grok_sessions(run: ScoredRun) -> list[Path]:
    """Find Grok session dirs for *run* within its time window."""
    directory = _grok_cwd_dir(run.workspace_dir)
    if not directory.is_dir():
        return []
    end = run.ended_at or datetime.now(tz=UTC)
    matches: list[Path] = []
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return []
    want_cwd = run.workspace_dir.rstrip("/") or run.workspace_dir
    for child in children:
        context_path = child / "prompt_context.json"
        if not context_path.is_file():
            continue
        context = _read_json(context_path)
        got_cwd = str(context.get("working_directory", ""))
        if (got_cwd.rstrip("/") or got_cwd) != want_cwd:
            continue
        stamped = _parse_time(context.get("build_timestamp_utc"))
        if stamped is None:
            try:
                stamped = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC)
            except OSError:
                continue
        if run.started_at <= stamped <= end:
            matches.append(child)
    return matches


def find_muse_session_id(run: ScoredRun) -> str | None:
    """Return the Muse ``muse_session_id`` recorded for *run*, if any."""
    meta = _read_json(Path(run.artifact_dir) / "run_metadata.json")
    session_id = meta.get("muse_session_id")
    return str(session_id) if isinstance(session_id, str) and session_id else None


def read_jsonl_capped(
    path: Path, *, max_bytes: int
) -> tuple[list[dict[str, Any]], bool]:
    """Read JSONL lines up to *max_bytes*; report ``(records, partial)``."""
    records: list[dict[str, Any]] = []
    partial = False
    try:
        size = path.stat().st_size
    except OSError:
        return [], False
    if size > max_bytes:
        partial = True
    try:
        with open(path, encoding="utf-8") as stream:
            used = 0
            for line in stream:
                encoded = len(line.encode("utf-8"))
                if used + encoded > max_bytes:
                    partial = True
                    break
                used += encoded
                line = line.strip()
                if not line:
                    continue
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    records.append(decoded)
    except OSError:
        return [], False
    return records, partial


def read_text_capped(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    """Read text up to *max_bytes*; report ``(text, partial)``."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "", False
    if len(raw) > max_bytes:
        return raw[:max_bytes].decode("utf-8", errors="replace"), True
    return raw.decode("utf-8", errors="replace"), False


__all__ = [
    "HELPER_TRANSCRIPT_BYTE_CAP",
    "ROOT_TRANSCRIPT_BYTE_CAP",
    "ScoredRun",
    "claude_project_dir",
    "_claude_projects_root",
    "_codex_sessions_root",
    "enumerate_runs",
    "find_claude_helpers",
    "find_claude_sessions",
    "find_codex_sessions",
    "find_grok_sessions",
    "find_muse_session_id",
    "_grok_cwd_dir",
    "_grok_sessions_root",
    "home_h1",
    "parse_when",
    "project_h1",
    "read_json_object",
    "read_jsonl_capped",
    "read_text_capped",
]
