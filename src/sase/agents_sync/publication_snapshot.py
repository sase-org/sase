"""Build owner-sharded hood snapshots and their run payloads."""

from __future__ import annotations

from sase.plan_chain import (
    agent_session_value,
)

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryLaneCommitHistory
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.publication_validation import verify_run_files
from sase.agents_sync.v2_io import file_reference, validate_snapshot, v2_json_bytes

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope
from sase.agents_sync.v2_models import (
    ContainerKind,
    RelationshipKind,
    RunState,
    V2ContainerRecord,
    canonical_container_kind,
    V2FileReference,
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2RelationshipRecord,
    V2RelationshipTarget,
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
from sase.core.agent_archive_facade import capabilities_from_v2_run
from sase.core.agent_identity_facade import (
    AgentSessionNameKind,
    AgentOwnerIdentity,
    agent_name_ancestors,
    globalize_agent_name,
    parse_agent_session_name,
)


# File kinds whose bytes are required for a run to stay in the snapshot. A
# scanner hit or unverifiable required file withholds the whole run so no
# dangling references or metadata leaks remain.
_STRUCTURAL_RUN_KINDS = ("meta", "state", "commits")

# File kinds withheld individually. A blocked kind never merges prior bytes
# back; an unverified kind may still merge previously published bytes because
# the withheld bytes themselves are never published.
_CONTENT_RUN_KINDS = ("prompt", "chat", "embedded_workflows", "prompt_steps")


@dataclass(frozen=True, slots=True)
class _GatedRun:
    """One inventory run after protection gating."""

    run: InventoryRun
    record: V2RunRecord | None
    blocked_kinds: frozenset[str]
    withheld_reason: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HoodWithheld:
    """Structured outcome when every current run in a hood is withheld."""

    hood: str
    reason: str
    withheld_runs: tuple[tuple[str, str], ...]


class HoodWithheldError(Exception):
    """A hood has current runs, but none of them may be published.

    Does not subclass ``AgentsSyncFormatError``: the commit drain treats
    that error as a terminal hood failure. Callers skip the hood and keep
    planning the rest of the project.
    """

    def __init__(self, withheld: _HoodWithheld) -> None:
        self.withheld = withheld
        super().__init__(f"hood {withheld.hood!r} withheld: {withheld.reason}")


RUN_WITHHELD_BLOCKED = "run withheld by publication protection"
RUN_WITHHELD_UNVERIFIED = "run could not be verified for publication"
HOOD_WITHHELD_BLOCKED = "hood withheld by publication protection"
HOOD_WITHHELD_UNVERIFIED = "hood could not be verified for publication"


def settlement_error_for_withheld_request(
    *,
    global_agent: str,
    local_hood: str,
    withheld_runs: tuple[tuple[str, str], ...],
    withheld_hoods: tuple[tuple[str, str], ...],
) -> str | None:
    """Return the value-free park/retry error for a withheld request, if any."""

    reason = dict(withheld_runs).get(global_agent)
    if reason is not None:
        return RUN_WITHHELD_BLOCKED if reason == "blocked" else RUN_WITHHELD_UNVERIFIED
    reason = dict(withheld_hoods).get(local_hood)
    if reason is not None:
        return (
            HOOD_WITHHELD_BLOCKED if reason == "blocked" else HOOD_WITHHELD_UNVERIFIED
        )
    return None


def build_hood_snapshot(
    repo_root: Path,
    project: V2ProjectIdentity,
    owner: AgentOwnerIdentity,
    hood: str,
    inventory: ProjectHoodInventory,
    previous: V2HoodSnapshot | None,
    *,
    protection_scope: PublicationProtectionScope | None = None,
) -> tuple[
    V2HoodSnapshot, dict[str, bytes], tuple[str, ...], tuple[tuple[str, str], ...]
]:
    current = inventory.hood_runs(hood)
    agent_session_history = inventory.agent_session_lane_commits(hood)
    if not current and previous is None:
        from sase.agents_sync.io import AgentsSyncFormatError

        raise AgentsSyncFormatError(f"hood {hood!r} has no publishable runs")
    if protection_scope is None:
        # Deferred so the protection modules stay out of the TUI startup closure.
        from sase.agents_sync.publication_protection import PublicationProtectionScope

        scope = PublicationProtectionScope(
            project_key=project.key,
            repository_identity=project.key,
        )
    else:
        scope = protection_scope
    payload: dict[str, bytes] = {}
    previous_by_global = (
        {run.global_name: run for run in previous.runs} if previous is not None else {}
    )
    gated = tuple(
        _gate_run_files(run, owner, project, payload, scope=scope) for run in current
    )
    notes: list[str] = []
    withheld_globals: set[str] = set()
    withheld_pairs: list[tuple[str, str]] = []
    gated_records: list[_GatedRun] = []
    for gated_run in gated:
        notes.extend(gated_run.notes)
        if gated_run.record is None:
            withheld_globals.add(gated_run.run.global_name)
            withheld_pairs.append(
                (
                    gated_run.run.global_name,
                    gated_run.withheld_reason or "unverified",
                )
            )
        else:
            gated_records.append(gated_run)
    if current and not gated_records:
        hood_reason = (
            "blocked"
            if all(gated_run.withheld_reason == "blocked" for gated_run in gated)
            else "unverified"
        )
        raise HoodWithheldError(
            _HoodWithheld(
                hood=hood,
                reason=hood_reason,
                withheld_runs=tuple(withheld_pairs),
            )
        )
    current_records: list[V2RunRecord] = []
    for gated_run in gated_records:
        assert gated_run.record is not None
        merged, merge_notes = _merge_richer_run_files(
            gated_run.record,
            previous_by_global.get(gated_run.run.global_name),
            repo_root,
            payload,
            scope=scope,
            blocked_kinds=gated_run.blocked_kinds,
        )
        notes.extend(merge_notes)
        current_records.append(merged)
    current_ids = {run.source_run_id for run in current_records}
    current_globals = {run.global_name for run in current_records}
    prior_records = (
        tuple(
            run
            for run in previous.runs
            if run.source_run_id not in current_ids
            and run.global_name not in current_globals
            and run.global_name not in withheld_globals
        )
        if previous is not None
        else ()
    )
    for run in prior_records:
        verify_run_files(repo_root, run)
    combined = tuple(
        sorted((*prior_records, *current_records), key=lambda item: item.source_run_id)
    )
    containers = _build_containers(
        combined,
        owner,
        agent_session_history,
        previous.containers if previous is not None else (),
    )
    publishable_current = tuple(
        run for run in current if run.global_name not in withheld_globals
    )
    relationships = _build_relationships(
        publishable_current,
        combined,
        inventory,
        owner,
        previous,
        current_ids,
    )
    ancestors = tuple(
        sorted(
            {
                globalize_agent_name(ancestor, owner)
                for run in combined
                for ancestor in agent_name_ancestors(run.local_name)
            }
        )
    )
    snapshot = V2HoodSnapshot(
        owner=owner,
        project=project,
        local_hood=hood,
        global_hood=globalize_agent_name(hood, owner),
        structural_ancestors=ancestors,
        runs=combined,
        containers=containers,
        relationships=relationships,
    )
    validate_snapshot(snapshot)
    return snapshot, payload, tuple(notes), tuple(withheld_pairs)


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


def _gate_run_files(
    run: InventoryRun,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    payload: dict[str, bytes],
    *,
    scope: PublicationProtectionScope,
) -> _GatedRun:
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
                return _GatedRun(
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
            return _GatedRun(
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
    return _GatedRun(
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


def _merge_richer_run_files(
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
    """

    if previous is None:
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


def _build_containers(
    runs: tuple[V2RunRecord, ...],
    owner: AgentOwnerIdentity,
    lane_commits: tuple[InventoryLaneCommitHistory, ...] = (),
    previous: tuple[V2ContainerRecord, ...] = (),
) -> tuple[V2ContainerRecord, ...]:
    agent_sessions: dict[str, set[str]] = {}
    clans: dict[str, set[str]] = {}
    agent_session_commits: dict[str, dict[str, CommitRecord]] = {}
    for run in runs:
        metadata = dict(run.metadata)
        parsed = parse_agent_session_name(run.local_name)
        agent_session = (
            parsed.agent_session_name
            if parsed.kind is AgentSessionNameKind.MEMBER
            else _text(agent_session_value(metadata))
        )
        if agent_session:
            agent_sessions.setdefault(agent_session, set()).add(run.source_run_id)
        clan = _text(metadata.get("agent_clan"))
        if clan:
            clans.setdefault(clan, set()).add(run.source_run_id)
    for history in lane_commits:
        if history.local_name not in agent_sessions:
            # Containers require at least one member; retain but do not fabricate
            # a run merely to carry session-lane history.
            continue
        agent_sessions.setdefault(history.local_name, set())
        commits = agent_session_commits.setdefault(history.local_name, {})
        commits.update({commit.sha: commit for commit in history.commits})
    containers = [
        V2ContainerRecord(
            cast(ContainerKind, kind),
            globalize_agent_name(name, owner),
            tuple(sorted(members)),
            (
                tuple(
                    sorted(
                        agent_session_commits.get(name, {}).values(),
                        key=lambda item: (item.committed_at, item.sha),
                    )
                )
                if kind == "session"
                else ()
            ),
        )
        for kind, groups in (("session", agent_sessions), ("clan", clans))
        for name, members in sorted(groups.items())
    ]
    by_key = {
        (canonical_container_kind(item.kind), item.global_name): item
        for item in containers
    }
    member_ids = {run.source_run_id for run in runs}
    for item in previous:
        if any(member not in member_ids for member in item.member_source_run_ids):
            # A withheld run left this retained container pointing at absent
            # members; session pages render every member, so the stale
            # container is dropped instead of rendering broken member links.
            continue
        key = (canonical_container_kind(item.kind), item.global_name)
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        commits = {commit.sha: commit for commit in (*item.commits, *current.commits)}
        by_key[key] = replace(
            current,
            commits=tuple(
                sorted(commits.values(), key=lambda row: (row.committed_at, row.sha))
            ),
        )
    return tuple(
        sorted(by_key.values(), key=lambda item: (item.kind, item.global_name))
    )


def _build_relationships(
    current: tuple[InventoryRun, ...],
    combined: tuple[V2RunRecord, ...],
    inventory: ProjectHoodInventory,
    owner: AgentOwnerIdentity,
    previous: V2HoodSnapshot | None,
    current_ids: set[str],
) -> tuple[V2RelationshipRecord, ...]:
    by_local = {run.local_name: run for run in inventory.runs}
    by_timestamp = {run.timestamp: run for run in inventory.runs}
    inside_ids = {run.source_run_id for run in combined}
    rows: list[V2RelationshipRecord] = []
    one_to_one: set[tuple[str, str]] = set()
    for run in current:
        for relation in run.relationships:
            key = (relation.kind, run.source_run_id)
            if relation.kind != "wait" and key in one_to_one:
                continue
            target_run = (
                by_local.get(relation.target)
                if relation.target_kind == "name"
                else by_timestamp.get(relation.target)
            )
            if target_run is None or target_run.source_run_id == run.source_run_id:
                continue
            if target_run.source_run_id in inside_ids:
                target = V2RelationshipTarget(
                    "source_run_id", source_run_id=target_run.source_run_id
                )
                required = True
            else:
                target = V2RelationshipTarget(
                    "global_name",
                    global_name=target_run.global_name,
                    owner=owner,
                )
                required = False
            rows.append(
                V2RelationshipRecord(
                    cast(RelationshipKind, relation.kind),
                    run.source_run_id,
                    target,
                    required,
                )
            )
            one_to_one.add(key)
    if previous is not None:
        rows.extend(
            relation
            for relation in previous.relationships
            if relation.source_run_id not in current_ids
            and relation.source_run_id in inside_ids
            and _target_is_retained(relation, inside_ids)
        )
    unique = {
        (
            item.kind,
            item.source_run_id,
            item.target.kind,
            item.target.source_run_id,
            item.target.global_name,
        ): item
        for item in rows
    }
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.kind,
                item.source_run_id,
                item.target.kind,
                item.target.source_run_id or item.target.global_name or "",
            ),
        )
    )


def _target_is_retained(relation: V2RelationshipRecord, inside_ids: set[str]) -> bool:
    return (
        relation.target.kind == "global_name"
        or relation.target.source_run_id in inside_ids
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
