"""Frontend-neutral audit helpers for successful repository opens."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import getpass
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.identity import AgentIdentity, discover_agent_identity
from sase.core.paths import sase_projects_dir
from sase.memory.locks import locked_file
from sase.project_aliases import resolve_project_alias_ref
from sase.repo_inventory import RepoKind

REPO_OPEN_LOG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RepoOpenEvent:
    """One successfully prepared repository checkout."""

    schema_version: int
    id: str
    timestamp: str
    project: str
    repo: str
    repo_kind: RepoKind
    workspace_num: int
    path: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    reason: str
    cwd: str


@dataclass(frozen=True)
class RepoOpenRepoSummary:
    """Aggregate open activity for one repository."""

    repo: str
    repo_kind: RepoKind
    open_count: int
    distinct_agent_count: int
    last_opened_at: str
    last_agent: str
    last_reason: str


@dataclass(frozen=True)
class RepoOpenAgentSummary:
    """Aggregate open activity for one agent or interactive user."""

    agent_name: str
    open_count: int
    distinct_repo_count: int
    last_opened_at: str
    last_repo: str
    last_reason: str


def build_repo_open_event(
    *,
    project: str,
    repo: str,
    repo_kind: RepoKind,
    workspace_num: int,
    path: str,
    reason: str,
    cwd: Path | None = None,
    now: datetime | None = None,
    open_id: str | None = None,
    env: Mapping[str, str] | None = None,
    agent: AgentIdentity | None = None,
    login_user: str | None = None,
) -> RepoOpenEvent:
    """Build an attributable event, falling back to an interactive identity."""

    current_env = os.environ if env is None else env
    identity = agent or discover_agent_identity(current_env)
    if identity is None:
        agent_name = _interactive_user(current_env, login_user=login_user)
        agent_source = "interactive"
        artifacts_dir = _optional_text(current_env.get("SASE_ARTIFACTS_DIR"))
    else:
        agent_name = identity.name
        agent_source = identity.source
        artifacts_dir = identity.artifacts_dir

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("repo open reason must not be empty")

    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    return RepoOpenEvent(
        schema_version=REPO_OPEN_LOG_SCHEMA_VERSION,
        id=open_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project,
        repo=repo,
        repo_kind=repo_kind,
        workspace_num=workspace_num,
        path=path,
        agent_name=agent_name,
        agent_source=agent_source,
        artifacts_dir=artifacts_dir,
        reason=normalized_reason,
        cwd=str(cwd_path),
    )


def repo_open_log_path(project: str) -> Path:
    """Return the project-scoped repository-open JSONL path."""

    project_name = resolve_project_alias_ref(project)
    return sase_projects_dir() / project_name / "repo_opens.jsonl"


def append_repo_open_event(
    event: RepoOpenEvent,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one repository-open event under an exclusive file lock."""

    path = log_path or repo_open_log_path(event.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(asdict(event), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()


def read_repo_open_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[RepoOpenEvent, ...]:
    """Read repository-open events, skipping malformed JSONL rows."""

    if log_path is None and project is None:
        raise ValueError("project is required when log_path is not provided")
    path = log_path or repo_open_log_path(project or "")
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[RepoOpenEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        event = _event_from_mapping(data)
        if event is not None:
            events.append(event)
    return tuple(events)


def filter_repo_open_events(
    events: Iterable[RepoOpenEvent],
    *,
    repo: str | None = None,
    agent_name: str | None = None,
    workspace_num: int | None = None,
) -> tuple[RepoOpenEvent, ...]:
    """Filter open events by repository, agent, and/or workspace number."""

    repo_filter = repo.strip() if repo else None
    agent_filter = agent_name.strip() if agent_name else None
    return tuple(
        event
        for event in events
        if (repo_filter is None or event.repo == repo_filter)
        and (agent_filter is None or event.agent_name == agent_filter)
        and (workspace_num is None or event.workspace_num == workspace_num)
    )


def summarize_repo_opens_by_repo(
    events: Iterable[RepoOpenEvent],
) -> tuple[RepoOpenRepoSummary, ...]:
    """Aggregate open counts and latest-open context by repository."""

    grouped: dict[tuple[str, RepoKind], list[RepoOpenEvent]] = {}
    for event in events:
        grouped.setdefault((event.repo, event.repo_kind), []).append(event)

    summaries: list[RepoOpenRepoSummary] = []
    for (repo, repo_kind), repo_events in grouped.items():
        latest = _latest_event(repo_events)
        summaries.append(
            RepoOpenRepoSummary(
                repo=repo,
                repo_kind=repo_kind,
                open_count=len(repo_events),
                distinct_agent_count=len({event.agent_name for event in repo_events}),
                last_opened_at=latest.timestamp,
                last_agent=latest.agent_name,
                last_reason=latest.reason,
            )
        )
    return tuple(
        sorted(summaries, key=lambda summary: (summary.repo, summary.repo_kind))
    )


def summarize_repo_opens_by_agent(
    events: Iterable[RepoOpenEvent],
) -> tuple[RepoOpenAgentSummary, ...]:
    """Aggregate open counts and latest-open context by agent name."""

    grouped: dict[str, list[RepoOpenEvent]] = {}
    for event in events:
        grouped.setdefault(event.agent_name, []).append(event)

    summaries: list[RepoOpenAgentSummary] = []
    for agent_name, agent_events in grouped.items():
        latest = _latest_event(agent_events)
        summaries.append(
            RepoOpenAgentSummary(
                agent_name=agent_name,
                open_count=len(agent_events),
                distinct_repo_count=len({event.repo for event in agent_events}),
                last_opened_at=latest.timestamp,
                last_repo=latest.repo,
                last_reason=latest.reason,
            )
        )
    return tuple(sorted(summaries, key=lambda summary: summary.agent_name))


def _interactive_user(env: Mapping[str, str], *, login_user: str | None = None) -> str:
    explicit = _optional_text(login_user)
    if explicit is not None:
        return explicit
    try:
        discovered = _optional_text(getpass.getuser())
    except (KeyError, OSError):
        discovered = None
    return discovered or _optional_text(env.get("USER")) or "unknown"


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


def _event_from_mapping(data: Mapping[str, Any]) -> RepoOpenEvent | None:
    if data.get("schema_version") != REPO_OPEN_LOG_SCHEMA_VERSION:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "repo",
        "repo_kind",
        "path",
        "agent_name",
        "agent_source",
        "reason",
        "cwd",
    )
    if any(not isinstance(data.get(key), str) for key in required_strings):
        return None
    repo_kind = data["repo_kind"]
    if repo_kind not in {"primary", "sidecar", "linked"}:
        return None
    workspace_num = data.get("workspace_num")
    if not isinstance(workspace_num, int) or isinstance(workspace_num, bool):
        return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None

    return RepoOpenEvent(
        schema_version=REPO_OPEN_LOG_SCHEMA_VERSION,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        repo=data["repo"],
        repo_kind=repo_kind,
        workspace_num=workspace_num,
        path=data["path"],
        agent_name=data["agent_name"],
        agent_source=data["agent_source"],
        artifacts_dir=artifacts_dir,
        reason=data["reason"],
        cwd=data["cwd"],
    )


def _latest_event(events: list[RepoOpenEvent]) -> RepoOpenEvent:
    return max(events, key=lambda event: event.timestamp)


__all__ = [
    "REPO_OPEN_LOG_SCHEMA_VERSION",
    "RepoOpenAgentSummary",
    "RepoOpenEvent",
    "RepoOpenRepoSummary",
    "append_repo_open_event",
    "build_repo_open_event",
    "filter_repo_open_events",
    "read_repo_open_events",
    "repo_open_log_path",
    "summarize_repo_opens_by_agent",
    "summarize_repo_opens_by_repo",
]
