"""Bead store checks for ``sase doctor``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.names import is_process_alive
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.bead.model import Issue, Status
from sase.bead.sync import bead_state_is_clean
from sase.core import bead_read_facade as rust_beads
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10
_CLAIM_OWNER_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=False,
    include_workflow_state=False,
    include_waiting=False,
)


@dataclass(frozen=True)
class _AgentOwner:
    """The newest artifact record for one agent name, as advisories see it."""

    bead_id: str | None
    promoted: bool
    alive: bool


def bead_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default bead check specs."""
    return (
        CheckSpec(
            id="project.beads",
            group="project",
            title="Project beads",
            runner=lambda: _check_project_beads(context),
        ),
    )


def _check_project_beads(context: DoctorContext) -> DiagnosticCheck:
    """Adapt the read-only bead doctor output into one diagnostic check."""
    beads_dir = _find_existing_beads_dir(context)
    if beads_dir is None:
        return DiagnosticCheck(
            id="project.beads",
            group="project",
            status="SKIP",
            title="Project beads",
            summary="no bead store found for this checkout or project",
            data={
                "project": context.project,
                "candidate_paths": [
                    str(path) for path in _candidate_beads_dirs(context)
                ],
            },
        )

    messages = rust_beads.doctor(beads_dir)
    advisories = _store_advisories(beads_dir, context.sase_home / "projects")
    if advisories:
        if len(messages) == 1 and messages[0].strip().upper().startswith("OK:"):
            messages = []
        messages.extend(advisories)
    sync_clean = _bead_sync_clean(beads_dir)
    if sync_clean is False:
        ok_message = "OK: no issues found"
        if messages == [ok_message]:
            messages = []
        messages.append("WARNING: bead state has uncommitted changes")

    stats = rust_beads.stats(beads_dir)
    status = _messages_status(messages)
    problem_messages = tuple(
        message for message in messages if not message.strip().upper().startswith("OK:")
    )
    summary = _messages_summary(status, messages, stats)

    return DiagnosticCheck(
        id="project.beads",
        group="project",
        status=status,
        title="Project beads",
        summary=summary,
        details=problem_messages[:_MAX_DETAIL_ROWS],
        next_steps=("Run `sase bead doctor`.",) if problem_messages else (),
        data={
            "beads_dir": str(beads_dir),
            "messages": messages,
            "stats": stats,
            "sync_clean": sync_clean,
        },
    )


def _store_advisories(beads_dir: Path, projects_root: Path) -> list[str]:
    """Return read-only advisories about state no other layer reconciles.

    Nothing here ever mutates. Claim promotion is documented as permanent, and
    a dependency edge whose target was removed can only be repaired by hand.
    """
    try:
        issues = rust_beads.list_issues(beads_dir)
    except Exception:  # noqa: BLE001 - advisory failure must not break doctor.
        return []
    if not issues:
        return []
    messages = _claim_advisories(issues, projects_root)
    messages.extend(_dangling_dependency_advisories(issues))
    return messages


def _claim_advisories(issues: list[Issue], projects_root: Path) -> list[str]:
    """Return read-only advisories about claims that disagree with agents.

    Four disagreements are reported: a claimed bead whose owner has no artifact
    anywhere, a claimed bead whose owning agent is dead, a promoted
    ``in_progress`` bead whose runner died before closing it, and a live
    pre-launch agent whose bead is still ``open`` even though the
    ``bead_claim_checks`` chop should have claimed it for that agent.
    """
    claimed = [issue for issue in issues if issue.status == Status.CLAIMED]
    in_progress = [issue for issue in issues if issue.status == Status.IN_PROGRESS]
    open_ids = {issue.id for issue in issues if issue.status == Status.OPEN}
    if not claimed and not in_progress and not open_ids:
        return []

    try:
        snapshot = scan_agent_artifacts(projects_root, _CLAIM_OWNER_SCAN_OPTIONS)
    except Exception:  # noqa: BLE001 - failed resolution proves nothing.
        return []
    owners = _owners_by_agent_name(snapshot)

    messages: list[str] = []
    orphaned = [issue for issue in claimed if issue.assignee not in owners]
    if orphaned:
        bead_ids = ", ".join(issue.id for issue in orphaned)
        messages.append(
            "WARNING: claimed beads have no resolvable agent artifact: "
            f"{bead_ids}; run `sase bead open <id>` to reopen them"
        )
    stale_claims = _issues_with_dead_owner(claimed, owners)
    if stale_claims:
        messages.append(
            "WARNING: claimed beads whose owning agent is gone: "
            f"{_render_owned(stale_claims)}; run `sase bead open <id>` to "
            "release them"
        )
    stranded = _issues_with_dead_owner(in_progress, owners, require_promoted=True)
    if stranded:
        messages.append(
            "WARNING: in_progress beads whose promoted agent is gone: "
            f"{_render_owned(stranded)}; run `sase bead open <id>` or retry "
            "the owning epic"
        )
    unclaimed = _live_agents_without_claims(open_ids, owners)
    if unclaimed:
        rendered = ", ".join(f"{bead_id} ({agent})" for bead_id, agent in unclaimed)
        messages.append(
            "WARNING: live pre-launch agents own beads that are still open: "
            f"{rendered}; check that the `bead_claim_checks` chop is running"
        )
    return messages


def _dangling_dependency_advisories(issues: list[Issue]) -> list[str]:
    """Return an advisory for dependency edges whose target no longer exists.

    ``sase bead rm`` leaves these behind: the read side treats a missing
    blocker as satisfied, so only doctor can surface the broken edge.
    """
    known = {issue.id for issue in issues}
    dangling = sorted(
        {
            (issue.id, dependency.depends_on_id)
            for issue in issues
            for dependency in issue.dependencies
            if dependency.depends_on_id not in known
        }
    )
    if not dangling:
        return []
    rendered = ", ".join(f"{issue_id} -> {missing}" for issue_id, missing in dangling)
    return [
        "WARNING: dependency edges point at beads that no longer exist: "
        f"{rendered}; recreate the missing bead or recreate the dependent "
        "without the edge"
    ]


def _owners_by_agent_name(snapshot: AgentArtifactScanWire) -> dict[str, _AgentOwner]:
    """Index the newest artifact record per agent name."""
    owners: dict[str, _AgentOwner] = {}
    timestamps: dict[str, str] = {}
    for record in snapshot.records:
        meta = record.agent_meta
        if meta is None or not meta.name:
            continue
        previous = timestamps.get(meta.name)
        if previous is not None and record.timestamp <= previous:
            continue
        artifact_dir = Path(record.artifact_dir)
        raw_meta = _read_json_dict(artifact_dir / "agent_meta.json")
        timestamps[meta.name] = record.timestamp
        owners[meta.name] = _AgentOwner(
            bead_id=str(meta.bead_id) if meta.bead_id else None,
            # An unreadable marker cannot prove the claim was never promoted.
            promoted=raw_meta is None or raw_meta.get("bead_claim_promoted") is True,
            alive=_agent_process_is_alive(meta, artifact_dir),
        )
    return owners


def _issues_with_dead_owner(
    issues: list[Issue],
    owners: dict[str, _AgentOwner],
    *,
    require_promoted: bool = False,
) -> list[tuple[str, str]]:
    """Return ``(bead_id, agent_name)`` pairs owned by a dead agent."""
    stale: list[tuple[str, str]] = []
    for issue in issues:
        owner = owners.get(issue.assignee)
        if owner is None or owner.alive:
            continue
        if require_promoted and not owner.promoted:
            continue
        stale.append((issue.id, issue.assignee))
    return sorted(stale)


def _render_owned(owned: list[tuple[str, str]]) -> str:
    return ", ".join(f"{bead_id} ({agent})" for bead_id, agent in owned)


def _live_agents_without_claims(
    open_ids: set[str],
    owners: dict[str, _AgentOwner],
) -> list[tuple[str, str]]:
    """Return ``(bead_id, agent_name)`` pairs the reconciler should have claimed.

    Only an ``open`` bead qualifies: a bead that reached ``in_progress`` or
    ``closed`` was legitimately promoted past the claim, and the promotion
    flag in ``agent_meta.json`` can lag that transition by a moment.
    """
    if not open_ids:
        return []
    unclaimed: dict[str, str] = {}
    for name, owner in owners.items():
        if owner.bead_id not in open_ids or owner.promoted or not owner.alive:
            continue
        unclaimed[owner.bead_id] = name
    return sorted(unclaimed.items())


def _agent_process_is_alive(meta: AgentMetaWire, artifact_dir: Path) -> bool:
    liveness: dict[str, object] = {}
    if meta.pid is not None:
        liveness["pid"] = meta.pid
    if meta.stopped_at is not None:
        liveness["stopped_at"] = meta.stopped_at
    return is_process_alive(liveness, artifact_dir)


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _bead_sync_clean(beads_dir: Path) -> bool | None:
    """Return bead sync cleanliness, or ``None`` when git is unusable.

    ``bead_state_is_clean`` shells out to git; a missing or non-executable
    git must degrade this check, not crash the whole doctor report.
    """
    try:
        return bead_state_is_clean(beads_dir)
    except OSError:
        return None


def _find_existing_beads_dir(context: DoctorContext) -> Path | None:
    for path in _candidate_beads_dirs(context):
        if path.is_dir():
            return path
    return None


def _candidate_beads_dirs(context: DoctorContext) -> tuple[Path, ...]:
    candidates: list[Path] = []
    cwd = context.cwd.expanduser().resolve(strict=False)
    _append_resolved_beads_candidate(candidates, cwd)
    for parent in (cwd, *cwd.parents):
        candidates.append(parent / BEADS_DIRNAME)
        candidates.append(parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC)
        candidates.append(parent / "sase" / "repos" / "beads")

    try:
        resolution = resolve_current_project_record(context)
    except Exception:
        resolution = None
    record = getattr(resolution, "record", None)
    workspace_dir = getattr(record, "workspace_dir", None)
    if isinstance(workspace_dir, str) and workspace_dir:
        primary = Path(workspace_dir).expanduser()
        _append_resolved_beads_candidate(candidates, primary)
        candidates.append(primary / BEADS_DIRNAME)
        candidates.append(primary / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC)
        candidates.append(primary / "sase" / "repos" / "beads")

    return _dedupe_paths(candidates)


def _append_resolved_beads_candidate(candidates: list[Path], workspace: Path) -> None:
    try:
        from sase.sdd.store import resolve_sdd_kind_dir

        candidates.append(resolve_sdd_kind_dir(workspace, 1, "beads"))
    except Exception:  # noqa: BLE001 - doctor candidate resolution is best-effort.
        return


def _dedupe_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


def _messages_status(messages: list[str]) -> CheckStatus:
    normalized = [message.strip().upper() for message in messages]
    if any(message.startswith("ERROR:") for message in normalized):
        return "ERROR"
    if any(
        message.startswith("WARNING:") or message.startswith("WARN:")
        for message in normalized
    ):
        return "WARN"
    return "OK"


def _messages_summary(
    status: CheckStatus,
    messages: list[str],
    stats: dict[str, int],
) -> str:
    issue_count = sum(
        int(stats.get(key, 0)) for key in ("open", "claimed", "in_progress", "closed")
    )
    if status == "OK":
        return f"bead store healthy; {issue_count} issue(s)"
    problems = [
        message for message in messages if not message.strip().upper().startswith("OK:")
    ]
    label = "error" if status == "ERROR" else "warning"
    return f"bead doctor reported {len(problems)} {label}(s)"


__all__ = [
    "bead_check_specs",
]
