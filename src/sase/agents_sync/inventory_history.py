"""Primary-repository history used to enrich agent inventory records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory_io import (
    canonical_local_name as _canonical_local_name,
    require_owner as _require_owner,
)
from sase.agents_sync.inventory_models import InventoryLaneCommitHistory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    known_owner_roots,
    parse_agent_session_name,
)
from sase.core.commit_footer_facade import CommitTagValue, LinkedCommitTagValue
from sase.core.paths import sase_home
from sase.sase_agent import SaseAgentRef, sase_agent_ref_for_name
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tag_values


@dataclass(frozen=True, slots=True)
class HistoricalAssociations:
    """Commit associations recovered from the primary repository's history."""

    run_commits: dict[str, tuple[CommitRecord, ...]]
    lane_commits: tuple[InventoryLaneCommitHistory, ...]


@dataclass(frozen=True, slots=True)
class _HistoryTrailerCommit:
    """The small parsed trailer projection needed to rebuild associations."""

    sha: str
    committed_at: int
    subject: str
    agent_label: str
    agent_destination: str | None
    machine_label: str | None

    @property
    def agent_value(self) -> CommitTagValue:
        if self.agent_destination is None:
            return self.agent_label
        return LinkedCommitTagValue(self.agent_label, self.agent_destination)


_HISTORY_CACHE_SCHEMA_VERSION = 1
_HISTORY_CACHE_MAX_COMMITS = 50_000
_HISTORY_CACHE_MAX_BYTES = 32 * 1024 * 1024
_HISTORY_LOG_FORMAT = "--format=%H%x00%ct%x00%s%x00%B%x00"


def historical_associations(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> HistoricalAssociations:
    """Associate tagged primary-repository commits with runs and sase agents."""

    trailers, head = _history_trailers(target, identity, git_runner)
    if trailers is None:
        return HistoricalAssociations({}, ())
    # Resolve the reserved agent-session set once for the whole build. The
    # per-footer lookup below used to rebuild it from the full name registry
    # on every commit, which dominated scoped inventory builds. A registry
    # change is observed by the next inventory build.
    reserved_agent_session_names = _reserved_agent_session_names_once()
    exact_runs: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    lanes: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    agent_session_lanes: dict[str, bool] = {}
    for trailer in trailers:
        sha = trailer.sha
        subject = trailer.subject
        committed_at = trailer.committed_at
        value = trailer.agent_value
        raw_name = trailer.agent_label
        footer_machine = trailer.machine_label
        if not raw_name or not _footer_is_current_owner(
            raw_name, footer_machine, identity
        ):
            continue
        try:
            local_name = _canonical_local_name(raw_name, identity)
            parsed = parse_agent_session_name(local_name)
        except (AgentsSyncFormatError, ValueError, RuntimeError):
            continue
        commit = CommitRecord(sha, subject, committed_at)
        if parsed.member_role is not None:
            # Legacy footers named the concrete session member. Preserve that
            # exact run attribution forever; only sase-agent-valued footers
            # belong to the session container.
            exact_runs[local_name][sha] = commit
            continue
        try:
            agent_ref = sase_agent_ref_for_name(
                local_name,
                identity,
                reserved_agent_session_names=reserved_agent_session_names,
            )
        except PublicationDrainTimedOut:
            raise
        except Exception:  # noqa: BLE001 - best-effort history boundary.
            continue
        if value is None:
            continue
        is_agent_session = _sase_agent_footer_is_agent_session(value, agent_ref)
        lanes[agent_ref.local_name][sha] = commit
        agent_session_lanes[agent_ref.local_name] = (
            agent_session_lanes.get(agent_ref.local_name, False) or is_agent_session
        )

    lane_commits = tuple(
        InventoryLaneCommitHistory(
            name,
            agent_session_lanes[name],
            _sorted_commit_rows(rows),
        )
        for name, rows in sorted(lanes.items())
    )
    run_rows = dict(exact_runs)
    for history in lane_commits:
        if history.is_agent_session:
            continue
        current = run_rows.setdefault(history.local_name, {})
        current.update({commit.sha: commit for commit in history.commits})
    associations = HistoricalAssociations(
        {
            name: tuple(
                sorted(rows.values(), key=lambda item: (item.committed_at, item.sha))
            )
            for name, rows in run_rows.items()
        },
        lane_commits,
    )
    # ``head`` is included here to make it explicit that the parsed trailer
    # projection returned above is the complete ancestry at this revision.
    del head
    return associations


def _history_trailers(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> tuple[tuple[_HistoryTrailerCommit, ...] | None, str | None]:
    """Load parsed trailers, extending a valid cache only along descendants."""

    head_result = git_runner(
        target.primary_checkout,
        ["rev-parse", "HEAD"],
        op="agents_sync.v2_history_head",
    )
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""
    cache_path = _history_cache_path(target)
    cache = _read_history_cache(cache_path, target, identity) if head else None

    if cache is not None and cache[0] == head:
        return cache[1], head

    prior: tuple[_HistoryTrailerCommit, ...] = ()
    range_start: str | None = None
    if cache is not None and head:
        cached_head, prior = cache
        ancestor = git_runner(
            target.primary_checkout,
            ["merge-base", "--is-ancestor", cached_head, head],
            op="agents_sync.v2_history_cache_ancestor",
        )
        if ancestor.returncode == 0:
            range_start = cached_head

    args = ["log", _HISTORY_LOG_FORMAT]
    if range_start is not None:
        args.append(f"{range_start}..{head}")
    result = git_runner(
        target.primary_checkout,
        args,
        op="agents_sync.v2_history",
    )
    if result.returncode != 0 and range_start is not None:
        # A stale or unusual cache range must never make inventory incomplete.
        result = git_runner(
            target.primary_checkout,
            ["log", _HISTORY_LOG_FORMAT],
            op="agents_sync.v2_history",
        )
        prior = ()
    if result.returncode != 0:
        return None, head or None

    parsed = _parse_history_trailers(result.stdout)
    combined_by_sha = {item.sha: item for item in prior}
    combined_by_sha.update({item.sha: item for item in parsed})
    combined = tuple(combined_by_sha.values())
    if head:
        _write_history_cache(cache_path, target, identity, head, combined)
    return combined, head or None


def _parse_history_trailers(stdout: str) -> tuple[_HistoryTrailerCommit, ...]:
    """Parse only commits carrying an AGENT trailer into the cache projection."""

    rows: list[_HistoryTrailerCommit] = []
    chunks = stdout.split("\x00")
    for index in range(0, len(chunks) - 3, 4):
        sha = chunks[index].lstrip("\r\n").strip().lower()
        subject = chunks[index + 2].rstrip("\r\n")
        try:
            committed_at = int(chunks[index + 1].strip())
            tags = parse_trailing_commit_tag_values(chunks[index + 3].rstrip("\r\n"))
        except (ValueError, TypeError, RuntimeError):
            continue
        agent = tags.get("AGENT")
        if isinstance(agent, LinkedCommitTagValue):
            agent_label = agent.label
            agent_destination = agent.destination
        elif isinstance(agent, str):
            agent_label = agent
            agent_destination = None
        else:
            continue
        machine = tags.get("MACHINE")
        machine_label = (
            machine.label if isinstance(machine, LinkedCommitTagValue) else machine
        )
        rows.append(
            _HistoryTrailerCommit(
                sha,
                committed_at,
                subject,
                agent_label,
                agent_destination,
                machine_label if isinstance(machine_label, str) else None,
            )
        )
    return tuple(rows)


def _history_cache_path(target: ProjectTarget) -> Path:
    identity = f"{target.project_key}\0{target.primary_checkout.resolve(strict=False)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return sase_home() / "cache" / "agent-publication-history" / f"{digest}.json"


def _history_cache_identity(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
) -> dict[str, object]:
    owner = identity.owner
    return {
        "project_key": target.project_key,
        "primary_checkout": str(target.primary_checkout.resolve(strict=False)),
        "owner": (
            {"username": owner.username, "machine_name": owner.machine_name}
            if owner is not None
            else None
        ),
        "known_owner_roots": sorted(known_owner_roots(identity)),
    }


def _read_history_cache(
    path: Path,
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
) -> tuple[str, tuple[_HistoryTrailerCommit, ...]] | None:
    try:
        if path.stat().st_size > _HISTORY_CACHE_MAX_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _HISTORY_CACHE_SCHEMA_VERSION
        or any(
            payload.get(key) != value
            for key, value in _history_cache_identity(target, identity).items()
        )
        or not isinstance(payload.get("head"), str)
        or not isinstance(payload.get("commits"), list)
    ):
        return None
    commits: list[_HistoryTrailerCommit] = []
    for row in payload["commits"]:
        if not isinstance(row, dict):
            return None
        sha = row.get("sha")
        committed_at = row.get("committed_at")
        subject = row.get("subject")
        agent_label = row.get("agent_label")
        destination = row.get("agent_destination")
        machine_label = row.get("machine_label")
        if (
            not isinstance(sha, str)
            or not isinstance(committed_at, int)
            or not isinstance(subject, str)
            or not isinstance(agent_label, str)
            or (destination is not None and not isinstance(destination, str))
            or (machine_label is not None and not isinstance(machine_label, str))
        ):
            return None
        commits.append(
            _HistoryTrailerCommit(
                sha,
                committed_at,
                subject,
                agent_label,
                destination,
                machine_label,
            )
        )
    if len(commits) > _HISTORY_CACHE_MAX_COMMITS:
        return None
    return payload["head"], tuple(commits)


def _write_history_cache(
    path: Path,
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    head: str,
    commits: tuple[_HistoryTrailerCommit, ...],
) -> None:
    """Persist a bounded cache; cache I/O never changes inventory results."""

    if len(commits) > _HISTORY_CACHE_MAX_COMMITS:
        _discard_history_cache(path)
        return
    payload = {
        "schema_version": _HISTORY_CACHE_SCHEMA_VERSION,
        **_history_cache_identity(target, identity),
        "head": head,
        "commits": [
            {
                "sha": row.sha,
                "committed_at": row.committed_at,
                "subject": row.subject,
                "agent_label": row.agent_label,
                "agent_destination": row.agent_destination,
                "machine_label": row.machine_label,
            }
            for row in commits
        ],
    }
    try:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > _HISTORY_CACHE_MAX_BYTES:
            _discard_history_cache(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as output:
                output.write(encoded)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        return


def _discard_history_cache(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _reserved_agent_session_names_once() -> set[str] | None:
    """Return the reserved agent-session set for one inventory build.

    Best-effort display-tier read: it never forces a registry rebuild or
    takes the allocation lock. ``None`` preserves the per-call fallback in
    :func:`sase.sase_agent.sase_agent_ref_for_name` when the registry is
    unavailable.
    """

    try:
        from sase.agent.names import get_reserved_agent_session_names_for_display

        return get_reserved_agent_session_names_for_display()
    except Exception:  # noqa: BLE001 - best-effort history boundary.
        return None


def _sorted_commit_rows(
    rows: dict[str, CommitRecord],
) -> tuple[CommitRecord, ...]:
    return tuple(sorted(rows.values(), key=lambda item: (item.committed_at, item.sha)))


def _destination_is_agent_session_page(destination: str) -> bool:
    """Return whether a linked footer destination names a session page.

    Historical commit footers used ``families/``; current footers use
    ``sessions/``. Both path segments identify an agent-session page.
    """

    path = unquote(urlsplit(destination).path)
    return bool({"families", "sessions"} & {part for part in path.split("/") if part})


def _sase_agent_footer_is_agent_session(
    value: CommitTagValue, agent_ref: SaseAgentRef
) -> bool:
    """Classify an ambiguous sase-agent label from its own footer evidence first."""

    if isinstance(value, LinkedCommitTagValue):
        return _destination_is_agent_session_page(value.destination)
    return agent_ref.is_agent_session


def primary_remote_url(
    target: ProjectTarget,
    git_runner: GitRunner,
) -> str | None:
    """Read the primary checkout's origin without making publication fragile."""

    try:
        result = git_runner(
            target.primary_checkout,
            ["config", "--get", "remote.origin.url"],
            op="agents_sync.v2_primary_remote",
        )
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - optional local Git metadata boundary.
        return None
    remote_url = result.stdout.strip()
    return remote_url if result.returncode == 0 and remote_url else None


def _footer_is_current_owner(
    name: str,
    footer_machine: str | None,
    identity: AgentIdentitySnapshot,
) -> bool:
    owner = _require_owner(identity)
    global_prefix = f"{owner.username}.{owner.machine_name}."
    if name.startswith(global_prefix):
        return footer_machine in {None, owner.machine_name}
    parts = name.split(".")
    if len(parts) >= 3 and footer_machine and parts[1] == footer_machine:
        return False
    if footer_machine == owner.machine_name:
        return True
    # Legacy footers stored a bare name with a host that was not the configured
    # machine identity. Accept only spellings without an explicit owner prefix.
    return not (footer_machine and name.startswith(f"{footer_machine}."))
