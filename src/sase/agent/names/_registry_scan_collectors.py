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
    add_owner_family,
    add_owner_names,
    localize_payload_name,
    source_owner_from_payload,
)
from sase.agent.names._registry_scan_payloads import (
    artifact_owner,
    bundle_owner,
    clan_from_payload,
    family_from_payload,
    load_dismissed_suffixes,
    names_from_payloads,
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
        if entry.get("reservation_kind") not in {"planned", "planned_clan"}:
            continue
        retained = dict(entry)
        if retained.get("origin") in {None, "local"} and identity is not None:
            retained.update(local_entry_provenance(name, identity))
        entries[name] = retained


def collect_artifact_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
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
            _collect_workflow_artifact_entries(
                entries,
                project_dir=project_dir,
                workflow_dir=workflow_dir,
                projects_dir=projects_dir,
                dismissed_suffixes=dismissed_suffixes,
                identity=identity,
            )


def _collect_workflow_artifact_entries(
    entries: dict[str, dict[str, Any]],
    *,
    project_dir: Path,
    workflow_dir: Path,
    projects_dir: Path,
    dismissed_suffixes: set[str],
    identity: AgentIdentitySnapshot,
) -> None:
    for artifact_dir in iter_agent_artifact_dirs(
        project_dir.name,
        workflow_dir.name,
        projects_root=projects_dir,
    ):
        if not artifact_dir.is_dir():
            continue
        meta = read_json_object(artifact_dir / "agent_meta.json")
        done = read_json_object(artifact_dir / "done.json")
        if meta is None and done is None:
            continue
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
        family = family_from_payload(meta)
        names = names_from_payloads(meta, done)
        if family is not None:
            names.discard(family)
        add_owner_clan(
            entries,
            _localize_clan(clan, provenance_payload, identity),
            owner,
            provenance_payload,
            identity,
        )
        add_owner_family(
            entries,
            _localize_optional_name(family, provenance_payload, identity),
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


def collect_dismissed_bundle_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot | None = None,
) -> None:
    if identity is None:
        identity = AgentIdentitySnapshot.current()
    bundles_dir = sase_subdir("dismissed_bundles")
    if not bundles_dir.is_dir():
        return
    try:
        paths = list(bundles_dir.rglob("*.json"))
    except OSError:
        return
    for path in paths:
        if not path.is_file():
            continue
        bundle = read_json_object(path)
        if bundle is None:
            continue
        owner = bundle_owner(path, bundle)
        clan = clan_from_payload(bundle)
        family = family_from_payload(bundle)
        names = names_from_payloads(bundle, None, bundle_name_keys=True)
        if family is not None:
            names.discard(family)
        add_owner_clan(
            entries,
            _localize_clan(clan, bundle, identity),
            owner,
            bundle,
            identity,
        )
        add_owner_family(
            entries,
            _localize_optional_name(family, bundle, identity),
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


def collect_owner_namespace_entries(
    entries: dict[str, dict[str, Any]],
    identity: AgentIdentitySnapshot,
) -> None:
    """Reserve configured and observed foreign owner roots.

    A root can already hold an ``auto_prefix`` entry derived from an
    imported artifact's own bare spelling (its first dotted segment, e.g.
    ``athena`` from ``athena.research.b``). That auto-prefix squats the root
    a container reservation must occupy, so it is displaced the same way a
    clan or family container displaces one.
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
