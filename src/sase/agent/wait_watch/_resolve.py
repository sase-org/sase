"""Resolve agent wait names to snapshot-backed wait targets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import json
from pathlib import Path

from sase.agent.names._common import is_process_alive
from sase.agent.names._templates import resolve_agent_name_template_reference
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.plan_chain import AGENT_FAMILY_SEPARATOR, agent_family_base

from ._types import (
    WaitCaller,
    WaitTarget,
    WaitTargetKind,
    WaitTargetResolutionError,
)

LivenessChecker = Callable[[dict[str, object], Path], bool]


def wait_scan_options(
    *, project_name: str | None = None
) -> AgentArtifactScanOptionsWire:
    """Return scan options for agent wait resolution and classification."""

    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,) if project_name else (),
    )


def load_wait_caller_from_env(
    env: Mapping[str, str],
) -> WaitCaller | None:
    """Return the calling agent identity from ``SASE_ARTIFACTS_DIR`` when present."""

    artifact_dir_value = env.get("SASE_ARTIFACTS_DIR")
    if not artifact_dir_value:
        return None
    artifact_dir = Path(artifact_dir_value).expanduser()
    try:
        data = json.loads(
            (artifact_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return WaitCaller(artifact_dir=str(artifact_dir))
    if not isinstance(data, dict):
        return WaitCaller(artifact_dir=str(artifact_dir))
    name = _string_value(data.get("name"))
    workflow_name = _string_value(data.get("workflow_name"))
    family_name = _string_value(data.get("agent_family")) or _family_from_name(name)
    clan_name = _string_value(data.get("agent_clan"))
    return WaitCaller(
        artifact_dir=str(artifact_dir),
        name=name,
        workflow_name=workflow_name,
        family_name=family_name,
        clan_name=clan_name,
    )


def resolve_wait_targets(
    names: Sequence[str],
    snapshot: AgentArtifactScanWire,
    *,
    project_name: str | None = None,
    caller: WaitCaller | None = None,
    liveness_checker: LivenessChecker = is_process_alive,
) -> tuple[WaitTarget, ...]:
    """Resolve explicit wait names against one artifact snapshot."""

    if not names:
        raise WaitTargetResolutionError("provide at least one agent name or use --all")

    targets: list[WaitTarget] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    records = tuple(_ace_run_records(snapshot.records, project_name=project_name))
    for raw_name in names:
        name = _resolve_name_template(raw_name)
        _raise_for_unsupported_reference(name)
        target = (
            _resolve_clan(name, raw_name, records)
            or _resolve_family(name, raw_name, records)
            or _resolve_workflow(name, raw_name, records)
            or _resolve_agent(name, raw_name, records, liveness_checker)
        )
        if target is None:
            raise WaitTargetResolutionError(
                f"no agent wait target found for {raw_name!r}"
            )
        if caller is not None and _target_intersects_caller(target, records, caller):
            raise WaitTargetResolutionError(
                f"refusing to wait on calling agent family via {raw_name!r}"
            )
        if target.key not in seen:
            seen.add(target.key)
            targets.append(target)
    return tuple(targets)


def resolve_all_wait_targets(
    snapshot: AgentArtifactScanWire,
    *,
    project_name: str | None = None,
    caller: WaitCaller | None = None,
    liveness_checker: LivenessChecker = is_process_alive,
) -> tuple[WaitTarget, ...]:
    """Snapshot live agents into wait targets for ``--all`` behavior."""

    records = tuple(_ace_run_records(snapshot.records, project_name=project_name))
    targets: list[WaitTarget] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for record in records:
        if not record_is_live(record, liveness_checker):
            continue
        if caller is not None and _caller_excludes_record(caller, record):
            continue
        target = _target_for_live_record(record, records)
        if target is None or target.key in seen:
            continue
        seen.add(target.key)
        targets.append(target)
    return tuple(targets)


def target_records(
    target: WaitTarget,
    records: Iterable[AgentArtifactRecordWire],
) -> tuple[AgentArtifactRecordWire, ...]:
    """Return records from *records* currently included in *target*."""

    ace_records = tuple(
        record
        for record in records
        if record.workflow_dir_name == target.workflow_dir_name
    )
    if target.kind is WaitTargetKind.AGENT:
        return tuple(
            record
            for record in ace_records
            if _same_path(record.artifact_dir, target.artifact_dir)
        )
    if target.kind is WaitTargetKind.CLAN:
        return _clan_generation_records(
            ace_records,
            target.name,
            target.clan_generation,
        )
    if target.kind is WaitTargetKind.FAMILY:
        return _family_generation_records(
            ace_records,
            target.name,
            target.family_root_timestamp,
        )
    return _workflow_records(ace_records, target.name)


def _target_intersects_caller(
    target: WaitTarget,
    records: Iterable[AgentArtifactRecordWire],
    caller: WaitCaller,
) -> bool:
    if target.kind is WaitTargetKind.AGENT:
        return _same_path(target.artifact_dir, caller.artifact_dir)
    if caller.family_name and target.kind is WaitTargetKind.FAMILY:
        return _same_name(target.name, caller.family_name)
    if caller.name and _same_name(target.name, caller.name):
        return True
    if caller.workflow_name and _same_name(target.name, caller.workflow_name):
        return True
    return any(
        _caller_excludes_record(caller, record)
        for record in target_records(target, records)
    )


def _caller_excludes_record(
    caller: WaitCaller, record: AgentArtifactRecordWire
) -> bool:
    if _same_path(caller.artifact_dir, record.artifact_dir):
        return True
    if caller.family_name is None:
        return False
    base = _record_family_base(record) or _family_from_name(record_name(record))
    return base is not None and _same_name(base, caller.family_name)


def record_is_live(
    record: AgentArtifactRecordWire,
    liveness_checker: LivenessChecker = is_process_alive,
) -> bool:
    if record.has_done_marker:
        return False
    return liveness_checker(_process_meta(record), Path(record.artifact_dir))


def record_name(record: AgentArtifactRecordWire) -> str:
    meta = record.agent_meta
    if meta is not None:
        return meta.name or meta.workflow_name or record.timestamp
    if record.done is not None:
        return record.done.name or record.timestamp
    return record.timestamp


def _record_clan_identity(
    record: AgentArtifactRecordWire,
) -> tuple[str, str] | None:
    meta = record.agent_meta
    if meta is None or not meta.agent_clan:
        return None
    generation = meta.agent_clan_generation or meta.parent_timestamp or record.timestamp
    return meta.agent_clan, generation


def _record_family_base(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is None:
        return None
    if meta.agent_family:
        return meta.agent_family
    if meta.name:
        base = agent_family_base(meta.name)
        if base:
            return base
    if meta.workflow_name and (meta.plan_chain_root or meta.agent_family_role):
        return meta.workflow_name
    return None


def _resolve_clan(
    name: str,
    raw_name: str,
    records: Sequence[AgentArtifactRecordWire],
) -> WaitTarget | None:
    for candidate in _name_candidates(name):
        generations = {
            generation
            for record in records
            if (identity := _record_clan_identity(record)) is not None
            and _same_name(identity[0], candidate)
            for generation in (identity[1],)
        }
        if generations:
            generation = max(generations)
            return WaitTarget(
                raw_name=raw_name,
                name=candidate,
                kind=WaitTargetKind.CLAN,
                clan_generation=generation,
            )
    return None


def _resolve_family(
    name: str,
    raw_name: str,
    records: Sequence[AgentArtifactRecordWire],
) -> WaitTarget | None:
    for candidate in _name_candidates(name):
        members = _family_generation_records(records, candidate, None)
        if members:
            root_timestamp = _family_root_timestamp(members)
            return WaitTarget(
                raw_name=raw_name,
                name=candidate,
                kind=WaitTargetKind.FAMILY,
                family_root_timestamp=root_timestamp,
            )
    return None


def _resolve_workflow(
    name: str,
    raw_name: str,
    records: Sequence[AgentArtifactRecordWire],
) -> WaitTarget | None:
    for candidate in _name_candidates(name):
        workflow_records = _workflow_records(records, candidate)
        if workflow_records:
            return WaitTarget(
                raw_name=raw_name,
                name=candidate,
                kind=WaitTargetKind.WORKFLOW,
            )
    return None


def _resolve_agent(
    name: str,
    raw_name: str,
    records: Sequence[AgentArtifactRecordWire],
    liveness_checker: LivenessChecker,
) -> WaitTarget | None:
    candidate_rank = {
        candidate: rank for rank, candidate in enumerate(_name_candidates(name))
    }
    matches = [
        record
        for record in records
        if record.agent_meta is not None and record.agent_meta.name in candidate_rank
    ]
    if not matches:
        return None

    def priority(record: AgentArtifactRecordWire) -> tuple[int, int, str]:
        assert record.agent_meta is not None
        rank = candidate_rank[record.agent_meta.name or ""]
        live_rank = 2 if record_is_live(record, liveness_checker) else 1
        return (live_rank, -rank, record.timestamp)

    best = max(matches, key=priority)
    assert best.agent_meta is not None
    return WaitTarget(
        raw_name=raw_name,
        name=best.agent_meta.name or name,
        kind=WaitTargetKind.AGENT,
        artifact_dir=best.artifact_dir,
        project_name=best.project_name,
        workflow_dir_name=best.workflow_dir_name,
    )


def _target_for_live_record(
    record: AgentArtifactRecordWire,
    records: Sequence[AgentArtifactRecordWire],
) -> WaitTarget | None:
    if (identity := _record_clan_identity(record)) is not None:
        return WaitTarget(
            raw_name=identity[0],
            name=identity[0],
            kind=WaitTargetKind.CLAN,
            clan_generation=identity[1],
        )
    if (base := _record_family_base(record)) is not None:
        root_timestamp = _family_root_timestamp_for_record(records, base, record)
        return WaitTarget(
            raw_name=base,
            name=base,
            kind=WaitTargetKind.FAMILY,
            family_root_timestamp=root_timestamp,
        )
    name = record_name(record)
    return WaitTarget(
        raw_name=name,
        name=name,
        kind=WaitTargetKind.AGENT,
        artifact_dir=record.artifact_dir,
        project_name=record.project_name,
        workflow_dir_name=record.workflow_dir_name,
    )


def _clan_generation_records(
    records: Sequence[AgentArtifactRecordWire],
    clan_name: str,
    generation: str | None,
) -> tuple[AgentArtifactRecordWire, ...]:
    matches = [
        record
        for record in records
        if (identity := _record_clan_identity(record)) is not None
        and _same_name(identity[0], clan_name)
        and (generation is None or identity[1] == generation)
    ]
    if generation is None and matches:
        newest = max(
            identity[1]
            for record in matches
            if (identity := _record_clan_identity(record))
        )
        matches = [
            record
            for record in matches
            if (identity := _record_clan_identity(record)) is not None
            and identity[1] == newest
        ]
    return tuple(sorted(matches, key=lambda record: record.timestamp))


def _family_generation_records(
    records: Sequence[AgentArtifactRecordWire],
    family_name: str,
    root_timestamp: str | None,
) -> tuple[AgentArtifactRecordWire, ...]:
    family_key = _name_key(family_name)
    members = [
        record
        for record in records
        if (base := _record_family_base(record)) is not None
        and _name_key(base) == family_key
    ]
    if not members:
        return ()
    if root_timestamp is None:
        root_timestamp = _family_root_timestamp(members)
    if root_timestamp is None:
        return tuple(sorted(members, key=lambda record: record.timestamp))

    by_timestamp = {record.timestamp: record for record in members}
    included = {root_timestamp}
    changed = True
    while changed:
        changed = False
        for record in members:
            meta = record.agent_meta
            parent = None if meta is None else meta.parent_timestamp
            if parent in included and record.timestamp not in included:
                included.add(record.timestamp)
                changed = True
    return tuple(
        sorted(
            (
                record
                for timestamp, record in by_timestamp.items()
                if timestamp in included
            ),
            key=lambda record: record.timestamp,
        )
    )


def _workflow_records(
    records: Sequence[AgentArtifactRecordWire],
    workflow_name: str,
) -> tuple[AgentArtifactRecordWire, ...]:
    workflow_key = _name_key(workflow_name)
    matches = [
        record
        for record in records
        if record.workflow_state is not None
        and _name_key(record.workflow_state.workflow_name) == workflow_key
    ]
    return tuple(sorted(matches, key=lambda record: record.timestamp))


def _family_root_timestamp(
    members: Sequence[AgentArtifactRecordWire],
) -> str | None:
    roots = [
        record
        for record in members
        if record.agent_meta is None or not record.agent_meta.parent_timestamp
    ]
    if not roots:
        return None
    return max(roots, key=lambda record: record.timestamp).timestamp


def _family_root_timestamp_for_record(
    records: Sequence[AgentArtifactRecordWire],
    family_name: str,
    record: AgentArtifactRecordWire,
) -> str | None:
    members = _family_generation_records(records, family_name, None)
    by_timestamp = {member.timestamp: member for member in members}
    current = record
    seen: set[str] = set()
    while current.timestamp not in seen:
        seen.add(current.timestamp)
        meta = current.agent_meta
        parent = None if meta is None else meta.parent_timestamp
        if parent is None or parent not in by_timestamp:
            return current.timestamp
        current = by_timestamp[parent]
    return record.timestamp


def _ace_run_records(
    records: Iterable[AgentArtifactRecordWire],
    *,
    project_name: str | None,
) -> Iterable[AgentArtifactRecordWire]:
    for record in records:
        if record.workflow_dir_name != "ace-run":
            continue
        if project_name is not None and record.project_name != project_name:
            continue
        yield record


def _process_meta(record: AgentArtifactRecordWire) -> dict[str, object]:
    meta: dict[str, object] = {}
    if record.agent_meta is not None:
        if record.agent_meta.pid is not None:
            meta["pid"] = record.agent_meta.pid
        if record.agent_meta.stopped_at is not None:
            meta["stopped_at"] = record.agent_meta.stopped_at
    if (
        "pid" not in meta
        and record.running is not None
        and record.running.pid is not None
    ):
        meta["pid"] = record.running.pid
    return meta


def _resolve_name_template(raw_name: str) -> str:
    try:
        return resolve_agent_name_template_reference(raw_name)
    except Exception as exc:
        raise WaitTargetResolutionError(str(exc)) from exc


def _raise_for_unsupported_reference(name: str) -> None:
    from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference

    try:
        tribe = parse_tribe_reference(name)
    except InvalidTribeError as exc:
        raise WaitTargetResolutionError(str(exc)) from exc
    if tribe is not None:
        raise WaitTargetResolutionError(
            f"tribe wait target {name!r} requires %wait and is not supported"
        )


def _name_candidates(name: str) -> tuple[str, ...]:
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    return current_owner_agent_name_lookup_candidates(name)


def _name_key(name: str) -> str:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    return current_owner_agent_name_key(name)


def _same_name(left: str, right: str) -> bool:
    return _name_key(left) == _name_key(right)


def _same_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return Path(left).expanduser().resolve(strict=False) == Path(
        right
    ).expanduser().resolve(strict=False)


def _family_from_name(name: str | None) -> str | None:
    if not name or AGENT_FAMILY_SEPARATOR not in name:
        return None
    base, _, _suffix = name.partition(AGENT_FAMILY_SEPARATOR)
    return base or None


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
