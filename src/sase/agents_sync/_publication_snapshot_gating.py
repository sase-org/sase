"""Gated run files for owner-sharded hood snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sase.agents_sync.inventory import InventoryRun
from sase.agents_sync.v2_io import file_reference, v2_json_bytes
from sase.agents_sync.v2_models import (
    RunState,
    V2FileReference,
    V2ProjectIdentity,
    V2RunCommitsPayload,
    V2RunMetadataPayload,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
)
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_EVIDENCE_DISMISSED,
    AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
    AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
    TERMINAL_RUN_STATES,
)
from sase.core.agent_archive_facade import capabilities_from_v2_run
from sase.core.agent_identity_facade import AgentOwnerIdentity

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope


# File kinds whose bytes are required for a run to stay in the snapshot. A
# scanner hit or unverifiable required file withholds the whole run so no
# dangling references or metadata leaks remain.
_STRUCTURAL_RUN_KINDS = ("meta", "state", "commits")

# File kinds withheld individually. A blocked kind never merges prior bytes
# back; an unverified kind may still merge previously published bytes because
# the withheld bytes themselves are never published.
_CONTENT_RUN_KINDS = ("prompt", "chat", "embedded_workflows", "prompt_steps")


@dataclass(frozen=True, slots=True)
class GatedRun:
    """One inventory run after protection gating."""

    run: InventoryRun
    record: V2RunRecord | None
    blocked_kinds: frozenset[str]
    withheld_reason: str | None
    notes: tuple[str, ...]


def _prior_content_blocked(
    scope: PublicationProtectionScope, destination: str, content: bytes
) -> bool:
    """Return whether a GH013 rejection already blocked these exact bytes.

    A failed lookup never authorizes publication, but it also never
    withholds on its own: the fresh scan below still decides. Only a durable
    ``blocked`` record for this exact digest withholds the candidate, so a
    clean rebuild after rejection recovery cannot replay rejected bytes.
    """

    # Deferred so the protection modules stay out of the TUI startup closure.
    from sase.agents_sync.publication_protection import (
        lookup_publication_content_record,
    )

    try:
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            sha256=hashlib.sha256(content).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        return False
    return isinstance(record, dict) and record.get("status") == "blocked"


def gate_run_files(
    run: InventoryRun,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    payload: dict[str, bytes],
    *,
    scope: PublicationProtectionScope,
) -> GatedRun:
    """Scan one run's bytes and withhold unsafe content without its evidence."""

    # Deferred so the protection modules stay out of the TUI startup closure.
    from sase.agents_sync.publication_protection import (
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    root = f"agents/{run.global_name}"
    meta = V2RunMetadataPayload(
        owner,
        project,
        run.source_run_id,
        run.local_name,
        run.global_name,
        run.metadata,
    )
    state = V2RunStatePayload(
        run.source_run_id,
        cast(RunState, run.state),
        run.started_at,
        run.finished_at,
        run.dismissed_at,
    )
    commits = V2RunCommitsPayload(run.source_run_id, run.commits)
    run_metadata_from_json(meta.to_json_dict())
    run_state_from_json(state.to_json_dict())
    run_commits_from_json(commits.to_json_dict())
    candidates: tuple[tuple[str, str, bytes | None], ...] = (
        ("meta", "meta.json", v2_json_bytes(meta.to_json_dict())),
        ("state", "state.json", v2_json_bytes(state.to_json_dict())),
        ("commits", "commits.json", v2_json_bytes(commits.to_json_dict())),
        ("prompt", "prompt.md", run.prompt_bytes),
        ("chat", "chat.md", run.chat_bytes),
        (
            "embedded_workflows",
            "embedded_workflows.json",
            run.embedded_workflows_bytes,
        ),
        ("prompt_steps", "prompt_steps.json", run.prompt_steps_bytes),
    )
    accepted: dict[str, tuple[str, bytes]] = {}
    blocked_kinds: set[str] = set()
    notes: list[str] = []
    withheld_reason: str | None = None
    for kind, name, content in candidates:
        if content is None:
            continue
        destination = f"{root}/{name}"
        if _prior_content_blocked(scope, destination, content):
            notes.append(f"withheld {destination}: blocked")
            if kind in _STRUCTURAL_RUN_KINDS:
                blocked_kinds.update(_CONTENT_RUN_KINDS)
                blocked_kinds.update(_STRUCTURAL_RUN_KINDS)
                return GatedRun(
                    run=run,
                    record=None,
                    blocked_kinds=frozenset(blocked_kinds),
                    withheld_reason="blocked",
                    notes=tuple(notes),
                )
            blocked_kinds.add(kind)
            withheld_reason = withheld_reason or "blocked"
            continue
        verdict = scan_publication_bytes(content, max_bytes=scope.max_bytes)
        status = verdict.disposition.get("status") if verdict.disposition else None
        try:
            record_publication_bytes_scan(
                scope.project_key,
                repository_identity=scope.repository_identity,
                relative_destination=destination,
                verdict=verdict,
                affected_requests=(run.source_run_id,),
            )
        except Exception:  # noqa: BLE001 - the scan verdict still withholds.
            notes.append(
                f"protection ledger unavailable for {run.global_name}; "
                "withholding on the scan verdict alone"
            )
        if verdict.is_publishable:
            accepted[kind] = (destination, content)
            continue
        reason = "blocked" if status == "blocked" else "unverified"
        notes.append(f"withheld {destination}: {reason}")
        if kind in _STRUCTURAL_RUN_KINDS:
            withheld_reason = reason
            blocked_kinds.update(_CONTENT_RUN_KINDS)
            blocked_kinds.update(_STRUCTURAL_RUN_KINDS)
            return GatedRun(
                run=run,
                record=None,
                blocked_kinds=frozenset(blocked_kinds),
                withheld_reason=withheld_reason,
                notes=tuple(notes),
            )
        if reason == "blocked":
            blocked_kinds.add(kind)
        withheld_reason = withheld_reason or reason
    files: list[tuple[str, V2FileReference]] = []
    for kind, (destination, content) in accepted.items():
        payload[destination] = content
        files.append((kind, file_reference(destination, content)))
    capabilities = capabilities_from_v2_run(
        dict(run.metadata), {kind for kind, _ in files}
    )
    return GatedRun(
        run=run,
        record=V2RunRecord(
            source_run_id=run.source_run_id,
            local_name=run.local_name,
            global_name=run.global_name,
            state=cast(RunState, run.state),
            started_at=run.started_at,
            finished_at=run.finished_at,
            dismissed_at=run.dismissed_at,
            metadata=run.metadata,
            commits=run.commits,
            files=tuple(files),
            capabilities=capabilities,
        ),
        blocked_kinds=frozenset(blocked_kinds),
        withheld_reason=None,
        notes=tuple(notes),
    )


def resolve_preserved_run_state(
    run: InventoryRun,
    previous: V2RunRecord | None,
    project: V2ProjectIdentity,
    owner: AgentOwnerIdentity,
) -> tuple[InventoryRun, str | None]:
    """Preserve verified terminal state for the same immutable run.

    A reused name with a different ``source_run_id`` never borrows terminal
    state. Same-identity active/waiting observations never regress a
    published terminal outcome; contradictory terminal outcomes are left as
    previously published with a bounded diagnostic. Resolution happens
    before file gating so a preserved terminal snapshot cannot point at an
    active ``state.json`` payload.
    """

    from sase.core.agent_run_state_facade import resolve_agent_run_state
    from sase.core.agent_run_state_wire import (
        AgentRunIdentityWire,
        AgentRunStateResolveRequestWire,
    )

    if previous is None:
        return run, None
    if previous.source_run_id != run.source_run_id:
        return run, None
    if previous.global_name != run.global_name:
        return run, None
    if run.state in TERMINAL_RUN_STATES and run.state != "dismissed":
        evidence_kind = AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER
        evidence_state: str | None = run.state
    elif run.state == "dismissed":
        evidence_kind = AGENT_RUN_STATE_EVIDENCE_DISMISSED
        evidence_state = "dismissed"
    elif run.state in ("active", "waiting"):
        evidence_kind = AGENT_RUN_STATE_EVIDENCE_UNFINISHED
        evidence_state = None
    else:
        return (
            run,
            f"{run.global_name}: unresolvable state {run.state!r}; "
            "preserved published state",
        )
    owner_token = f"{owner.username}@{owner.machine_name}"
    identity = AgentRunIdentityWire(
        project=project.key,
        owner=owner_token,
        global_name=run.global_name,
        source_run_id=run.source_run_id,
    )
    request = AgentRunStateResolveRequestWire(
        identity=identity,
        published_state=previous.state,
        published_started_at=previous.started_at,
        published_finished_at=previous.finished_at,
        evidence_kind=evidence_kind,
        evidence_identity=identity,
        evidence_state=evidence_state,
        evidence_started_at=run.started_at,
        evidence_finished_at=run.finished_at,
    )
    try:
        response = resolve_agent_run_state(request)
    except (ValueError, RuntimeError) as exc:
        return run, f"{run.global_name}: unresolved state evidence ({exc}); unchanged"
    new_state = response.selected_state
    new_started_at = response.selected_started_at
    new_finished_at = response.selected_finished_at
    if new_state == "dismissed":
        new_dismissed_at = run.dismissed_at or previous.dismissed_at
    else:
        new_dismissed_at = None
    if (
        new_state == run.state
        and new_started_at == run.started_at
        and new_finished_at == run.finished_at
        and new_dismissed_at == run.dismissed_at
    ):
        return run, None
    updated = replace(
        run,
        state=new_state,  # type: ignore[arg-type]
        started_at=new_started_at,
        finished_at=new_finished_at,
        dismissed_at=new_dismissed_at,
    )
    if response.reason in (
        "conflicting_terminal_evidence",
        "identity_conflict",
        "malformed_evidence",
        "missing_evidence",
    ):
        return (
            updated,
            f"{run.global_name}: {response.reason}; preserved {previous.state}",
        )
    return updated, None


def merge_richer_run_files(
    current: V2RunRecord,
    previous: V2RunRecord | None,
    repo_root: Path,
    payload: dict[str, bytes],
    *,
    scope: PublicationProtectionScope,
    blocked_kinds: frozenset[str] = frozenset(),
) -> tuple[V2RunRecord, tuple[str, ...]]:
    """Keep recoverable prompt/chat bytes instead of commit-only placeholders.

    Blocked kinds never merge prior bytes back. Merged prior bytes are
    scanned exactly like fresh candidates because this drain writes them.
    Only the same immutable run (matching ``source_run_id``) may reuse
    previously published content; a reused name with a different run
    identity never borrows prior bytes.
    """

    if previous is None:
        return current, ()
    if previous.source_run_id != current.source_run_id:
        return current, ()
    notes: list[str] = []
    previous_files = dict(previous.files)
    current_files = dict(current.files)
    files = list(current.files)
    changed = False
    for kind in _CONTENT_RUN_KINDS:
        if kind in blocked_kinds:
            notes.append(f"withheld richer {kind} for {current.global_name}: blocked")
            continue
        prior = previous_files.get(kind)
        if prior is None:
            continue
        prior_path = repo_root / prior.path
        if not prior_path.is_file():
            continue
        try:
            prior_bytes = prior_path.read_bytes()
        except OSError:
            continue
        current_ref = current_files.get(kind)
        current_bytes = (
            payload.get(current_ref.path) if current_ref is not None else None
        )
        if current_bytes is not None and len(current_bytes) >= len(prior_bytes):
            continue
        if not _prior_bytes_releasable(
            prior_bytes, prior.path, current.global_name, scope, notes
        ):
            continue
        payload[prior.path] = prior_bytes
        if current_ref is not None and current_ref.path != prior.path:
            payload.pop(current_ref.path, None)
        files = [
            (item_kind, prior if item_kind == kind else ref) for item_kind, ref in files
        ]
        if kind not in current_files:
            files.append((kind, prior))
        changed = True
    if not changed:
        return current, tuple(notes)
    capabilities = capabilities_from_v2_run(
        dict(current.metadata), {kind for kind, _ref in files}
    )
    return replace(current, files=tuple(files), capabilities=capabilities), tuple(notes)


def _prior_bytes_releasable(
    prior_bytes: bytes,
    prior_path: str,
    global_name: str,
    scope: PublicationProtectionScope,
    notes: list[str],
) -> bool:
    """Return whether previously published bytes may re-enter this payload."""

    # Deferred so the protection modules stay out of the TUI startup closure.
    from sase.agents_sync.publication_protection import (
        lookup_publication_content_record,
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    try:
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=prior_path,
            sha256=hashlib.sha256(prior_bytes).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        record = None
    if isinstance(record, dict) and record.get("status") == "blocked":
        notes.append(f"withheld richer {prior_path}: blocked")
        return False
    verdict = scan_publication_bytes(prior_bytes, max_bytes=scope.max_bytes)
    try:
        record_publication_bytes_scan(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=prior_path,
            verdict=verdict,
        )
    except Exception:  # noqa: BLE001 - the scan verdict still withholds.
        notes.append(
            f"protection ledger unavailable for {global_name}; "
            "withholding on the scan verdict alone"
        )
    if not verdict.is_publishable:
        status = verdict.disposition.get("status") if verdict.disposition else None
        reason = "blocked" if status == "blocked" else "unverified"
        notes.append(f"withheld richer {prior_path}: {reason}")
        return False
    return True
