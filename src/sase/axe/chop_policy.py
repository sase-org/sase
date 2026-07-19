"""Runner-owned declarative chop policy and bookkeeping host adapter.

The Rust chop engine owns validation and deterministic decisions. This module
supplies the IO-bound snapshots that engine consumes and persists its returned
checkpoint/once-per transforms under each chop's state directory.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Protocol

from sase.agent.running import list_running_agents
from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    CHOP_STATE_SCHEMA_VERSION,
    apply_chop_checkpoint_update,
    check_and_record_chop_once_per,
    evaluate_chop_decision,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.core.time import get_timezone

from .config import ChopConfig
from .state import atomic_write_json, ensure_chop_dirs, read_json

ChopDecisionOutcome = Literal["fire", "skip", "check_error"]
ChopCheckpointEvent = Literal[
    "observed", "action_accepted", "action_succeeded", "action_failed"
]

_DEFAULT_CHECKPOINT_DOCUMENT: dict[str, Any] = {
    "schema_version": CHOP_STATE_SCHEMA_VERSION,
    "entries": {},
}
_DEFAULT_SEEN_DOCUMENT: dict[str, Any] = {
    "schema_version": CHOP_STATE_SCHEMA_VERSION,
    "entries": [],
}
_GIT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class ChopPreflight:
    """One normalized guard/trigger decision made before script dispatch."""

    outcome: ChopDecisionOutcome
    reason: str
    decision: dict[str, Any] | None = None
    checkpoint_enabled: bool = False


@dataclass(frozen=True)
class _ChopOncePerOutcome:
    """Per-proposal once-per decisions for one structured chop result."""

    accepted_indices: tuple[int, ...]
    decisions: dict[int, dict[str, str]]


class _Proposal(Protocol):
    @property
    def index(self) -> int: ...

    @property
    def proposal_id(self) -> str | None: ...

    @property
    def workspace(self) -> str: ...

    @property
    def agent_name(self) -> str: ...

    @property
    def dedupe_key(self) -> str | None: ...

    @property
    def wait_on(self) -> int | str | None: ...


def evaluate_chop_preflight(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    context_file: str | None,
    scheduled: bool,
    force: bool = False,
    now: datetime | None = None,
) -> ChopPreflight:
    """Evaluate configured guards and trigger before dispatching a chop.

    Manual runs replace the configured trigger with ``always`` while retaining
    guards. ``force`` is manual-run escape hatch that bypasses both.
    """
    if force:
        return ChopPreflight(
            outcome="fire",
            reason="forced manual run bypassed declarative guards and trigger",
        )

    timestamp = (now or datetime.now(get_timezone())).isoformat()
    try:
        checkpoint = _read_checkpoint_document(lumberjack_name, chop.name)
        changespecs = (
            _changespec_snapshots(context_file)
            if any(guard.get("provider") == "changespec" for guard in chop.inhibit_if)
            else []
        )
        agents = (
            _agent_snapshots()
            if any(guard.get("provider") == "agent_hood" for guard in chop.inhibit_if)
            else []
        )

        trigger = chop.trigger if scheduled else {"provider": "always"}
        git: list[dict[str, Any]] = []
        checkpoint_for_decision = checkpoint
        if trigger.get("provider") == "git.commits_since":
            git_snapshot, checkpoint_for_decision = _git_snapshot(
                trigger,
                checkpoint,
            )
            if git_snapshot is not None:
                git.append(git_snapshot)

        decision = evaluate_chop_decision(
            {
                "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                "inhibit_if": chop.inhibit_if,
                "trigger": trigger,
                "changespecs": changespecs,
                "agents": agents,
                "git": git,
                "checkpoint": checkpoint_for_decision,
                "now": timestamp,
            }
        )
    except Exception as exc:
        return ChopPreflight(
            outcome="check_error",
            reason=f"declarative chop preflight failed: {exc}",
        )

    outcome = str(decision.get("outcome"))
    if outcome not in {"fire", "skip", "check_error"}:
        return ChopPreflight(
            outcome="check_error",
            reason=f"declarative chop preflight returned invalid outcome {outcome!r}",
            decision=decision,
        )
    return ChopPreflight(
        outcome=outcome,  # type: ignore[arg-type]
        reason=str(decision.get("reason") or "no decision reason was provided"),
        decision=decision,
        checkpoint_enabled=scheduled,
    )


def record_chop_checkpoint_event(
    lumberjack_name: str,
    chop_name: str,
    preflight: ChopPreflight,
    event: ChopCheckpointEvent,
    *,
    now: datetime | None = None,
) -> None:
    """Persist one checkpoint lifecycle event returned by the Rust engine."""
    decision = preflight.decision
    if not preflight.checkpoint_enabled or decision is None:
        return
    key = decision.get("checkpoint_key")
    cursor = decision.get("checkpoint_cursor")
    policy = decision.get("checkpoint_policy")
    if not key or not cursor or not policy:
        return

    with _chop_policy_lock(lumberjack_name, chop_name):
        document = _read_checkpoint_document(lumberjack_name, chop_name)
        updated = apply_chop_checkpoint_update(
            {
                "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                "document": document,
                "key": str(key),
                "cursor": str(cursor),
                "now": (now or datetime.now(get_timezone())).isoformat(),
                "policy": str(policy),
                "event": event,
            }
        )
        atomic_write_json(_checkpoint_path(lumberjack_name, chop_name), updated)


def finalize_pending_chop_checkpoints(
    lumberjack_name: str,
    chop_name: str,
    event: Literal["action_succeeded", "action_failed"],
    *,
    now: datetime | None = None,
) -> int:
    """Finalize every pending on-action-success cursor for one chop."""
    with _chop_policy_lock(lumberjack_name, chop_name):
        document = _read_checkpoint_document(lumberjack_name, chop_name)
        entries = document.get("entries")
        if not isinstance(entries, dict):
            raise ValueError("checkpoint document entries must be an object")
        pending = [
            (str(key), str(entry["pending_cursor"]))
            for key, entry in entries.items()
            if isinstance(entry, dict) and entry.get("pending_cursor")
        ]
        if not pending:
            return 0

        timestamp = (now or datetime.now(get_timezone())).isoformat()
        updated = document
        for key, cursor in pending:
            updated = apply_chop_checkpoint_update(
                {
                    "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                    "document": updated,
                    "key": key,
                    "cursor": cursor,
                    "now": timestamp,
                    "policy": "on_action_success",
                    "event": event,
                }
            )
        atomic_write_json(_checkpoint_path(lumberjack_name, chop_name), updated)
        return len(pending)


def apply_chop_once_per(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    proposals: Sequence[_Proposal],
    persist: bool,
    now: datetime | None = None,
) -> _ChopOncePerOutcome:
    """Apply bounded event dedupe and dependency-aware proposal filtering."""
    if chop.once_per is None and not any(p.dedupe_key for p in proposals):
        return _ChopOncePerOutcome(
            accepted_indices=tuple(proposal.index for proposal in proposals),
            decisions={},
        )

    timestamp = (now or datetime.now(get_timezone())).isoformat()
    capacity = int((chop.once_per or {}).get("capacity", 1024))
    accepted: list[int] = []
    accepted_ids: set[str] = set()
    decisions: dict[int, dict[str, str]] = {}

    with _chop_policy_lock(lumberjack_name, chop.name):
        document = _read_seen_document(lumberjack_name, chop.name)
        changed = False
        for proposal in proposals:
            dependency = proposal.wait_on
            dependency_accepted = True
            if isinstance(dependency, int):
                dependency_accepted = dependency in accepted
            elif isinstance(dependency, str):
                dependency_accepted = dependency in accepted_ids
            if not dependency_accepted:
                decisions[proposal.index] = {
                    "outcome": "duplicate",
                    "reason": (
                        f"proposal dependency {dependency!r} was skipped by once-per"
                    ),
                    "key": "",
                }
                continue

            key = _proposal_once_per_key(chop, proposal)
            if key is None:
                accepted.append(proposal.index)
                if proposal.proposal_id is not None:
                    accepted_ids.add(proposal.proposal_id)
                continue

            result = check_and_record_chop_once_per(
                {
                    "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                    "document": document,
                    "key": key,
                    "now": timestamp,
                    "capacity": capacity,
                }
            )
            outcome = str(result["outcome"])
            decisions[proposal.index] = {
                "outcome": outcome,
                "reason": str(result["reason"]),
                "key": key,
            }
            if outcome == "duplicate":
                continue
            if outcome != "accept":
                raise ValueError(f"unexpected once-per outcome: {outcome}")
            document = dict(result["document"])
            changed = True
            accepted.append(proposal.index)
            if proposal.proposal_id is not None:
                accepted_ids.add(proposal.proposal_id)

        if persist and changed:
            atomic_write_json(_seen_path(lumberjack_name, chop.name), document)

    return _ChopOncePerOutcome(tuple(accepted), decisions)


def check_chop_trigger_runtime(chop: ChopConfig) -> str | None:
    """Return a doctor error for an unusable git trigger, otherwise ``None``."""
    if chop.trigger.get("provider") != "git.commits_since":
        return None
    project = str(chop.trigger.get("project") or "")
    record = _resolve_chop_git_project(project)
    if record is None:
        return f"project ref {project!r} does not match a registered SASE project"
    if not record.workspace_dir:
        return f"project {project!r} has no primary workspace"
    try:
        _run_git(Path(record.workspace_dir).expanduser(), "rev-parse", "HEAD")
    except RuntimeError as exc:
        return str(exc)
    return None


def _resolve_chop_git_project(project: str) -> ProjectRecordWire | None:
    """Resolve a trigger project ref without creating or mutating a project."""
    try:
        records = list_project_records(
            sase_projects_dir(), "all", include_home=False, projects_only=True
        )
    except Exception:
        return None

    raw = project.removeprefix("#")
    candidates = {raw.casefold()}
    if raw.startswith("git:"):
        candidates.add(raw.removeprefix("git:").casefold())
    if raw.startswith("gh:"):
        owner_repo = raw.removeprefix("gh:")
        candidates.add(f"gh_{owner_repo.replace('/', '__')}".casefold())

    for record in records:
        names = {
            record.project_name,
            effective_project_name(record),
            *record.aliases,
        }
        if any(name.casefold() in candidates for name in names if name):
            return record
    return None


def _git_snapshot(
    trigger: dict[str, Any],
    checkpoint: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    project = str(trigger.get("project") or "")
    record = _resolve_chop_git_project(project)
    if record is None or not record.workspace_dir:
        return None, checkpoint

    repo = Path(record.workspace_dir).expanduser()
    head = _run_git(repo, "rev-parse", "HEAD")
    checkpoint_key = f"git.commits_since:{project}"
    entries = checkpoint.get("entries")
    raw_entry = entries.get(checkpoint_key) if isinstance(entries, dict) else None
    cursor = str(raw_entry.get("cursor") or "") if isinstance(raw_entry, dict) else ""

    checkpoint_found = False
    if cursor:
        try:
            _run_git(repo, "cat-file", "-e", f"{cursor}^{{commit}}")
            _run_git(repo, "merge-base", "--is-ancestor", cursor, head)
            count = int(_run_git(repo, "rev-list", "--count", f"{cursor}..HEAD"))
            checkpoint_found = True
        except (RuntimeError, ValueError):
            count = int(trigger["threshold"])
    else:
        # Preserve the retired workflows' missing-marker behavior: the first
        # observation fires and establishes a runner-owned checkpoint.
        count = int(trigger["threshold"])

    checkpoint_for_decision = checkpoint
    if cursor and not checkpoint_found:
        checkpoint_for_decision = json.loads(json.dumps(checkpoint))
        decision_entries = checkpoint_for_decision.get("entries")
        if isinstance(decision_entries, dict):
            decision_entries.pop(checkpoint_key, None)

    return (
        {
            "project": project,
            "head": head,
            "commits_since_checkpoint": count,
            "checkpoint_found": checkpoint_found,
        },
        checkpoint_for_decision,
    )


def _changespec_snapshots(context_file: str | None) -> list[dict[str, str]]:
    if not context_file:
        raise ValueError("changespec guard requires a chop context file")
    try:
        context = json.loads(Path(context_file).read_text(encoding="utf-8"))
        changespec_path = Path(str(context["all_changespecs_file"]))
        rows = json.loads(changespec_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load ChangeSpec guard snapshot: {exc}") from exc
    if not isinstance(rows, list):
        raise ValueError("ChangeSpec guard snapshot must be a list")
    return [
        {"name": str(row.get("name") or ""), "status": str(row.get("status") or "")}
        for row in rows
        if isinstance(row, dict)
    ]


def _agent_snapshots() -> list[dict[str, Any]]:
    return [
        {
            "name": str(agent.name),
            "status": str(agent.status),
            "active": True,
        }
        for agent in list_running_agents()
        if agent.name
    ]


def _proposal_once_per_key(chop: ChopConfig, proposal: _Proposal) -> str | None:
    if proposal.dedupe_key:
        return proposal.dedupe_key
    once_per = chop.once_per
    if once_per is None:
        return None
    template = str(once_per["key"])
    proposal_value = SimpleNamespace(
        id=proposal.proposal_id or "",
        index=proposal.index,
        workspace=proposal.workspace,
        agent_name=proposal.agent_name,
        dedupe_key=proposal.dedupe_key or "",
    )
    try:
        rendered = template.format_map(
            {
                "chop": _NamedTemplateValue(chop.name),
                "proposal": proposal_value,
                "target": _TargetTemplateValue(chop.target),
            }
        )
    except (AttributeError, KeyError, ValueError) as exc:
        raise ValueError(
            f"could not render once_per key template {template!r}: {exc}"
        ) from exc
    if not rendered.strip():
        raise ValueError("once_per key template rendered an empty key")
    return rendered


class _NamedTemplateValue(str):
    @property
    def name(self) -> str:
        return str(self)


class _TargetTemplateValue(dict[str, Any]):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(f"git observation failed for {repo}: {detail}")
    return result.stdout.strip()


def _checkpoint_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "checkpoint.json"


def _seen_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "seen.json"


def _lock_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "policy.lock"


@contextmanager
def _chop_policy_lock(lumberjack_name: str, chop_name: str) -> Iterator[None]:
    with _lock_path(lumberjack_name, chop_name).open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_checkpoint_document(lumberjack_name: str, chop_name: str) -> dict[str, Any]:
    return _read_policy_document(
        _checkpoint_path(lumberjack_name, chop_name),
        _DEFAULT_CHECKPOINT_DOCUMENT,
        "checkpoint",
    )


def _read_seen_document(lumberjack_name: str, chop_name: str) -> dict[str, Any]:
    return _read_policy_document(
        _seen_path(lumberjack_name, chop_name),
        _DEFAULT_SEEN_DOCUMENT,
        "seen-store",
    )


def _read_policy_document(
    path: Path,
    default: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    document = read_json(path)
    if not isinstance(document, dict):
        raise ValueError(f"{label} state is unreadable: {path}")
    return document


__all__ = [
    "ChopPreflight",
    "apply_chop_once_per",
    "check_chop_trigger_runtime",
    "evaluate_chop_preflight",
    "finalize_pending_chop_checkpoints",
    "record_chop_checkpoint_event",
]
