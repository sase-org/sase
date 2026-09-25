"""Top-level source collectors for the durable agent-name registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.names._registry_entries import (
    local_entry_provenance,
    owner_namespace_entry,
)
from sase.agent.names._registry_scan_entries import (
    promote_container_over_auto_prefix,
    add_owner_clan,
    add_owner_agent_session,
    add_owner_names,
    localize_payload_name,
    source_owner_from_payload,
)
from sase.agent.names._registry_scan_payloads import (
    artifact_owner,
    bundle_owner,
    clan_from_payload,
    agent_session_from_payload,
    load_dismissed_suffixes,
    owner_identity_names,
    read_json_object,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir


def collect_planned_reservation_entries(
    entries: dict[str, dict[str, Any]],
    existing: dict[str, Any] | None,
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    if existing is None:
        return
    existing_entries = existing.get("entries")
    if not isinstance(existing_entries, dict):
        return
    for name, entry in existing_entries.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if entry.get("reservation_kind") not in {
            "planned",
            "planned_clan",
            "cleanup_in_progress",
        }:
            continue
        retained = dict(entry)
        if retained.get("origin") in {None, "local"} and identity is not None:
            retained.update(local_entry_provenance(name, identity))
        entries[name] = retained


def collect_inflight_claim_entries(
    entries: dict[str, dict[str, Any]],
    existing: dict[str, Any] | None,
    identity: AgentIdentitySnapshot,
) -> None:
    """Keep live local claims the unlocked scan could not yet identify.

    A runner reserves its name before it writes the named metadata that the
    ordinary artifact scan consumes.  Rechecking only absent existing entries
    while holding the allocation lock closes that interval without adding I/O
    to the usual fully-derived rebuild path.
    """
    if existing is None:
        return
    existing_entries = existing.get("entries")
    if not isinstance(existing_entries, dict):
        return

    dismissed_suffixes: set[str] | None = None
    for name, entry in existing_entries.items():
        if name in entries or not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if not _is_local_inflight_claim(entry):
            continue
        artifact_path = _artifact_dir_from_entry(entry)
        if artifact_path is None:
            continue

        meta = read_json_object(artifact_path / "agent_meta.json")
        done = read_json_object(artifact_path / "done.json")
        if _payload_has_identity(meta, done):
            context = _artifact_directory_context(artifact_path)
            if context is None:
                continue
            project_dir, workflow_dir = context
            if dismissed_suffixes is None:
                dismissed_suffixes = load_dismissed_suffixes()
            derived: dict[str, dict[str, Any]] = {}
            _collect_single_artifact_entries(
                derived,
                artifact_path,
                project_dir=project_dir,
                workflow_dir=workflow_dir,
                dismissed_suffixes=dismissed_suffixes,
                identity=identity,
            )
            for derived_name, derived_entry in derived.items():
                entries.setdefault(derived_name, derived_entry)
            continue

        if done is None and meta is not None:
            # Keep this import local: _common imports name lookup helpers.
            from sase.agent.names._common import is_process_alive

            if is_process_alive(meta, artifact_path):
                entries[name] = dict(entry)


def _is_local_inflight_claim(entry: dict[str, Any]) -> bool:
    return (
        entry.get("origin") in {None, "local"}
        and entry.get("source") == "artifact"
        and entry.get("reservation_kind")
        not in {
            "planned",
            "planned_clan",
            "cleanup_in_progress",
            "auto_prefix",
            "owner_namespace",
        }
    )


def _artifact_dir_from_entry(entry: dict[str, Any]) -> Path | None:
    artifact_dir = entry.get("artifacts_dir")
    if not isinstance(artifact_dir, str) or not artifact_dir:
        return None
    path = Path(artifact_dir).expanduser()
    return path if path.is_dir() else None


def _payload_has_identity(
    meta: dict[str, Any] | None,
    done: dict[str, Any] | None,
) -> bool:
    return bool(
        owner_identity_names(meta, done)
        or clan_from_payload(meta)
        or agent_session_from_payload(meta)
    )


def _artifact_directory_context(artifact_dir: Path) -> tuple[Path, Path] | None:
    """Return the project and workflow parents for a legacy or sharded artifact."""
    for workflow_dir in artifact_dir.parents:
        artifacts_root = workflow_dir.parent
        if artifacts_root.name == "artifacts":
            return artifacts_root.parent, workflow_dir
    return None


def collect_artifact_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()
    if identity is None:
        identity = AgentIdentitySnapshot.current()
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return
    dismissed_suffixes = load_dismissed_suffixes()
    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return
    parsed_sources = 0
    for project_dir in project_iter:
        artifacts_root = project_dir / "artifacts"
        if not project_dir.is_dir() or not artifacts_root.is_dir():
            continue
        try:
            workflow_iter = artifacts_root.iterdir()
        except OSError:
            continue
        for workflow_dir in workflow_iter:
            if not workflow_dir.is_dir():
                continue
            parsed_sources += _collect_workflow_artifact_entries(
                entries,
                project_dir=project_dir,
                workflow_dir=workflow_dir,
                projects_dir=projects_dir,
                dismissed_suffixes=dismissed_suffixes,
                identity=identity,
            )
    if timer is not None:
        timer.mark(
            "registry_artifact_source_counts",
            full_scans=1,
            parsed_source_files=parsed_sources,
        )


def _collect_workflow_artifact_entries(
    entries: dict[str, dict[str, Any]],
    *,
    project_dir: Path,
    workflow_dir: Path,
    projects_dir: Path,
    dismissed_suffixes: set[str],
    identity: AgentIdentitySnapshot,
) -> int:
    parsed_sources = 0
    for artifact_dir in iter_agent_artifact_dirs(
        project_dir.name,
        workflow_dir.name,
        projects_root=projects_dir,
    ):
        parsed_sources += _collect_single_artifact_entries(
            entries,
            artifact_dir,
            project_dir=project_dir,
            workflow_dir=workflow_dir,
            dismissed_suffixes=dismissed_suffixes,
            identity=identity,
        )
    return parsed_sources


def _collect_single_artifact_entries(
    entries: dict[str, dict[str, Any]],
    artifact_dir: Path,
    *,
    project_dir: Path,
    workflow_dir: Path,
    dismissed_suffixes: set[str],
    identity: AgentIdentitySnapshot,
) -> bool:
    """Derive all registry entries owned by one artifact directory."""
    if not artifact_dir.is_dir():
        return False
    meta = read_json_object(artifact_dir / "agent_meta.json")
    done = read_json_object(artifact_dir / "done.json")
    if meta is None and done is None:
        return False
    state = "done" if done is not None else "active"
    if artifact_dir.name in dismissed_suffixes:
        state = "dismissed"
    owner = artifact_owner(
        project_dir=project_dir,
        workflow_dir=workflow_dir,
        artifact_dir=artifact_dir,
        state=state,
    )
    provenance_payload = meta or done or {}
    clan = clan_from_payload(meta)
    agent_session = agent_session_from_payload(meta)
    names = owner_identity_names(meta, done)
    add_owner_clan(
        entries,
        _localize_clan(clan, provenance_payload, identity),
        owner,
        provenance_payload,
        identity,
    )
    add_owner_agent_session(
        entries,
        _localize_optional_name(agent_session, provenance_payload, identity),
        owner,
        provenance_payload,
        identity,
    )
    add_owner_names(
        entries,
        _localize_names(names, provenance_payload, identity),
        owner,
        provenance_payload,
        identity,
    )
    return True


def collect_dismissed_bundle_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()
    if identity is None:
        identity = AgentIdentitySnapshot.current()
    bundles_dir = sase_subdir("dismissed_bundles")
    if not bundles_dir.is_dir():
        return
    try:
        paths = list(bundles_dir.rglob("*.json"))
    except OSError:
        return
    parsed_sources = 0
    for path in paths:
        if not path.is_file():
            continue
        bundle = read_json_object(path)
        if bundle is None:
            continue
        parsed_sources += 1
        owner = bundle_owner(path, bundle)
        clan = clan_from_payload(bundle)
        agent_session = agent_session_from_payload(bundle)
        names = owner_identity_names(bundle, bundle=True)
        add_owner_clan(
            entries,
            _localize_clan(clan, bundle, identity),
            owner,
            bundle,
            identity,
        )
        add_owner_agent_session(
            entries,
            _localize_optional_name(agent_session, bundle, identity),
            owner,
            bundle,
            identity,
        )
        add_owner_names(
            entries,
            _localize_names(names, bundle, identity),
            owner,
            bundle,
            identity,
        )
    if timer is not None:
        timer.mark(
            "registry_bundle_source_counts",
            full_scans=1,
            parsed_source_files=parsed_sources,
        )


def collect_owner_namespace_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot,
) -> None:
    """Reserve configured and observed foreign owner roots.

    A root can already hold an ``auto_prefix`` entry derived from an
    imported artifact's own bare spelling (its first dotted segment, e.g.
    ``athena`` from ``athena.research.b``). That auto-prefix squats the root
    a container reservation must occupy, so it is displaced the same way a
    clan or agent-session container displaces one.
    """
    owner = identity.owner
    for machine_name in identity.sibling_machines:
        if owner is not None and machine_name == owner.machine_name:
            continue
        _reserve_owner_namespace_root(
            entries,
            machine_name,
            owner_namespace_entry(
                machine_name,
                namespace_kind="sibling_machine",
            ),
        )

    for entry in tuple(entries.values()):
        if not isinstance(entry, dict):
            continue
        source_owner = source_owner_from_payload(entry)
        if source_owner is not None:
            if owner is not None and source_owner.username == owner.username:
                if source_owner.machine_name != owner.machine_name:
                    _reserve_owner_namespace_root(
                        entries,
                        source_owner.machine_name,
                        owner_namespace_entry(
                            source_owner.machine_name,
                            namespace_kind="sibling_machine",
                            source_owner=source_owner,
                        ),
                    )
            else:
                root = f"{source_owner.username}.{source_owner.machine_name}"
                _reserve_owner_namespace_root(
                    entries,
                    root,
                    owner_namespace_entry(
                        root,
                        namespace_kind="foreign_username",
                        source_owner=source_owner,
                    ),
                )
        legacy_machine = entry.get("legacy_source_machine")
        if isinstance(legacy_machine, str) and legacy_machine:
            _reserve_owner_namespace_root(
                entries,
                legacy_machine,
                owner_namespace_entry(
                    legacy_machine,
                    namespace_kind="legacy_source_machine",
                ),
            )


def _reserve_owner_namespace_root(
    entries: dict[str, dict[str, Any]],
    root: str,
    container_entry: dict[str, Any],
) -> None:
    if promote_container_over_auto_prefix(entries, root, container_entry):
        return
    entries.setdefault(root, container_entry)


def _localize_clan(
    clan: tuple[str, str] | None,
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> tuple[str, str] | None:
    if clan is None:
        return None
    name, generation = clan
    localized = localize_payload_name(name, payload, identity)
    return None if localized is None else (localized, generation)


def _localize_optional_name(
    name: str | None,
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> str | None:
    return None if name is None else localize_payload_name(name, payload, identity)


def _localize_names(
    names: set[str],
    payload: dict[str, Any],
    identity: AgentIdentitySnapshot,
) -> set[str]:
    localized: set[str] = set()
    for name in names:
        value = localize_payload_name(name, payload, identity)
        if value is not None:
            localized.add(value)
    return localized
