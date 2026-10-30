"""State payload construction and repair page planning."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    content_digest,
    file_reference,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
    V2RunStatePayload,
    is_session_container,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.agents_sync._publication_state_repair_evidence import (
    validated_snapshot_for_entry,
)
from sase.agents_sync._publication_state_repair_types import (
    ResolvedWindow,
    StateRepairAffected,
)

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope


def plan_state_payload(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    resolved: ResolvedWindow,
    deadline: float,
    *,
    bad_hoods: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, bytes],
    dict[tuple[str, str], StateRepairAffected],
    int,
    tuple[str, ...],
    int,
    tuple[str, ...],
]:
    from sase.agents_sync.publication_protection import PublicationProtectionScope
    from sase.agents_sync.v2_io import read_owner_manifest

    scope = PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )
    by_hood: dict[str, list[tuple[str, StateRepairAffected]]] = {}
    for key, affected in resolved.changed.items():
        by_hood.setdefault(key[0], []).append((key[1], affected))
    payload: dict[str, bytes] = {}
    updated: dict[tuple[str, str], StateRepairAffected] = {}
    withheld = 0
    withheld_diags: list[str] = []
    failed = 0
    diagnostics: list[str] = []
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    manifest = read_owner_manifest(
        target.sidecar_path,
        owner,
        V2ProjectIdentity(target.project_key, target.project),
    )
    entries = manifest.by_hood()
    for hood in sorted(by_hood):
        if time.monotonic() > deadline:
            failed += len(by_hood[hood])
            diagnostics.append(
                f"hood {hood!r}: state repair work budget exceeded; "
                "retry the window with a smaller limit"
            )
            continue
        try:
            snapshot = validated_snapshot_for_entry(
                target.sidecar_path, owner, hood, entries.get(hood)
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            failed += len(by_hood[hood])
            diagnostics.append(f"hood {hood!r} is not repairable: {exc}")
            continue
        by_id = {run.source_run_id: run for run in snapshot.runs}
        replacements: dict[str, V2RunRecord] = {}
        hood_ok = True
        for run_id, affected in sorted(by_hood[hood]):
            pending = resolved.pending.get((hood, run_id))
            current = by_id.get(run_id)
            if pending is None or current is None:  # pragma: no cover - defensive
                failed += 1
                diagnostics.append(
                    f"{affected.global_name}: published run is no longer present"
                )
                hood_ok = False
                continue
            _record, started_at, finished_at = pending
            if affected.selected_state == "dismissed":
                dismissed_at = current.dismissed_at or finished_at
            else:
                dismissed_at = None
            state_payload = V2RunStatePayload(
                run_id,
                affected.selected_state,  # type: ignore[arg-type]
                started_at,
                finished_at,
                dismissed_at,
            )
            try:
                state_bytes = v2_json_bytes(state_payload.to_json_dict())
            except (TypeError, ValueError) as exc:
                failed += 1
                diagnostics.append(
                    f"{affected.global_name}: state payload is not encodable: {exc}"
                )
                continue
            if len(state_bytes) > scope.max_bytes:
                withheld += 1
                withheld_diags.append(
                    f"{affected.global_name}: state payload exceeds the "
                    "publication byte bound; withheld"
                )
                continue
            if not _state_bytes_publishable(
                state_bytes,
                f"agents/{affected.global_name}/state.json",
                scope,
                target,
                withheld_diags,
                affected.global_name,
            ):
                withheld += 1
                continue
            reference = file_reference(
                f"agents/{affected.global_name}/state.json", state_bytes
            )
            files = tuple(
                (kind, reference if kind == "state" else ref)
                for kind, ref in current.files
            )
            if "state" not in {kind for kind, _ref in files}:
                files = (*files, ("state", reference))
            replacements[run_id] = V2RunRecord(
                current.source_run_id,
                current.local_name,
                current.global_name,
                affected.selected_state,  # type: ignore[arg-type]
                started_at,
                finished_at,
                dismissed_at,
                current.metadata,
                current.commits,
                files,
                current.capabilities,
            )
            payload[f"agents/{affected.global_name}/state.json"] = state_bytes
        if not replacements:
            continue
        runs = tuple(replacements.get(run.source_run_id, run) for run in snapshot.runs)
        runs = tuple(sorted(runs, key=lambda item: item.source_run_id))
        updated_snapshot = V2HoodSnapshot(
            snapshot.owner,
            snapshot.project,
            snapshot.local_hood,
            snapshot.global_hood,
            snapshot.structural_ancestors,
            runs,
            snapshot.containers,
            snapshot.relationships,
        )
        try:
            from sase.agents_sync.v2_io import validate_snapshot

            validate_snapshot(updated_snapshot)
            snapshot_bytes = v2_json_bytes(updated_snapshot.to_json_dict())
        except (AgentsSyncFormatError, RuntimeError, ValueError) as exc:
            failed += len(replacements)
            diagnostics.append(f"hood {hood!r} repair snapshot is not valid: {exc}")
            for run_id in replacements:
                payload.pop(f"agents/{by_id[run_id].global_name}/state.json", None)
            continue
        if len(snapshot_bytes) > MAX_JSON_BYTES:
            failed += len(replacements)
            diagnostics.append(
                f"hood {hood!r} repair snapshot exceeds the JSON byte limit"
            )
            for run_id in replacements:
                payload.pop(f"agents/{by_id[run_id].global_name}/state.json", None)
            continue
        from sase.agents_sync.publication_validation import snapshot_path

        payload[snapshot_path(owner, hood)] = snapshot_bytes
        changed_snapshots[(owner.username, owner.machine_name, hood)] = updated_snapshot
        for run_id, affected in by_hood[hood]:
            if run_id in replacements:
                updated[(hood, run_id)] = affected
        if not hood_ok:
            diagnostics.append(f"hood {hood!r}: partially repaired")
    if not changed_snapshots:
        return (
            payload,
            updated,
            withheld,
            tuple(withheld_diags),
            failed,
            tuple(diagnostics),
        )
    try:
        manifest_payload, manifest_diags = _plan_manifest_and_pages(
            target, owner, changed_snapshots, payload, skip_hoods=bad_hoods
        )
    except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
        return (
            {},
            {},
            withheld,
            tuple(withheld_diags),
            failed + len(updated),
            (
                *diagnostics,
                f"state repair manifest is not writable: {exc}",
            ),
        )
    payload.update(manifest_payload)
    diagnostics.extend(manifest_diags)
    return payload, updated, withheld, tuple(withheld_diags), failed, tuple(diagnostics)


def _state_bytes_publishable(
    state_bytes: bytes,
    destination: str,
    scope: PublicationProtectionScope,
    target: ProjectTarget,
    withheld_diags: list[str],
    global_name: str,
) -> bool:
    from sase.agents_sync.publication_protection import (
        lookup_publication_content_record,
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    import hashlib

    try:
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            sha256=hashlib.sha256(state_bytes).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        record = None
    if isinstance(record, dict) and record.get("status") == "blocked":
        withheld_diags.append(f"{global_name}: state payload is blocked; withheld")
        return False
    verdict = scan_publication_bytes(state_bytes, max_bytes=scope.max_bytes)
    try:
        record_publication_bytes_scan(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            verdict=verdict,
        )
    except Exception:  # noqa: BLE001 - the scan verdict still withholds.
        withheld_diags.append(
            f"protection ledger unavailable for {global_name}; "
            "withholding on the scan verdict alone"
        )
    if not verdict.is_publishable:
        status = verdict.disposition.get("status") if verdict.disposition else None
        reason = "blocked" if status == "blocked" else "unverified"
        withheld_diags.append(f"{global_name}: state payload {reason}; withheld")
        return False
    return True


def _plan_manifest_and_pages(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
    payload: dict[str, bytes],
    *,
    skip_hoods: frozenset[str] = frozenset(),
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    from sase.agents_sync.bead_links import build_bead_page_links
    from sase.agents_sync.publication_validation import load_validated_publication
    from sase.agents_sync.rendering import render_targeted_browsing_payload
    from sase.agents_sync.v2_io import (
        check_manifest_write_size,
        owner_manifest_path,
        read_owner_manifest,
        v2_schema_document,
    )

    project = V2ProjectIdentity(target.project_key, target.project)
    previous_manifest = read_owner_manifest(target.sidecar_path, owner, project)
    entries = dict(previous_manifest.by_hood())
    for (username, machine, hood), snapshot in changed_snapshots.items():
        assert (username, machine) == (owner.username, owner.machine_name)
        snapshot_bytes = payload[
            f"users/{username}/machines/{machine}/hoods/{hood}/snapshot.json"
        ]
        entries[hood] = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            None,
            len(snapshot.runs),
            sum(is_session_container(item.kind) for item in snapshot.containers),
        )
    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    manifest_bytes = v2_json_bytes(manifest.to_json_dict())
    check_manifest_write_size(len(manifest.hoods), manifest_bytes)
    extra: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
        "sessions/.gitkeep": b"",
        owner_manifest_path(owner): manifest_bytes,
    }
    if skip_hoods:
        return _plan_manifest_and_pages_degraded(
            target,
            owner,
            project,
            manifest,
            changed_snapshots,
            {**payload, **extra},
            skip_hoods,
        )
    manifests, snapshots, diagnostics = load_validated_publication(
        target.sidecar_path,
        override_manifest=manifest,
        override_snapshots=dict(changed_snapshots),
        override_payload={**payload, **extra},
    )
    selected_keys = frozenset(changed_snapshots)
    bead_links, bead_diagnostics = build_bead_page_links(
        tuple(snapshots[key] for key in sorted(selected_keys) if key in snapshots),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    # Targeted rendering keeps complete manifests but writes only affected
    # hood, agent, session, and index pages; unrelated pages are omitted.
    pages = render_targeted_browsing_payload(
        manifests,
        snapshots,
        selected_keys,
        bead_links=bead_links,
    )
    return {**extra, **pages}, (*diagnostics, *bead_diagnostics)


def _plan_manifest_and_pages_degraded(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    manifest: V2OwnerManifest,
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
    payload: dict[str, bytes],
    skip_hoods: frozenset[str],
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    """Render repair pages while unreadable sibling hoods stay preserved.

    The written manifest keeps every entry (skipped hoods byte-for-byte), but
    derived browsing pages can only cover readable hoods, so rendering uses a
    filtered manifest. Skipped units stay explicitly failed with their own
    diagnostic; the next full sync restores complete pages.
    """

    from sase.agents_sync.bead_links import build_bead_page_links
    from sase.agents_sync.publication_validation import verify_run_files
    from sase.agents_sync.rendering import render_targeted_browsing_payload
    from sase.agents_sync.v2_io import (
        owner_manifest_from_bytes,
        read_all_owner_manifests_lenient,
        read_owner_manifest,
        v2_json_bytes,
    )

    from sase.agents_sync.v2_io import validate_snapshot

    for snapshot in changed_snapshots.values():
        validate_snapshot(snapshot)
        for run in snapshot.runs:
            verify_run_files(target.sidecar_path, run, payload)
    owner_manifest_from_bytes(v2_json_bytes(manifest.to_json_dict()))
    on_disk_entries = read_owner_manifest(target.sidecar_path, owner, project).by_hood()
    healthy: dict[tuple[str, str, str], V2HoodSnapshot] = dict(changed_snapshots)
    for hood, _entry in manifest.hoods:
        key = (owner.username, owner.machine_name, hood)
        if key in healthy or hood in skip_hoods:
            continue
        healthy[key] = validated_snapshot_for_entry(
            target.sidecar_path, owner, hood, on_disk_entries.get(hood)
        )
    render_manifest = V2OwnerManifest(
        owner,
        project,
        tuple(
            (hood, entry) for hood, entry in manifest.hoods if hood not in skip_hoods
        ),
    )
    other_manifests, lenient_diagnostics = read_all_owner_manifests_lenient(
        target.sidecar_path
    )
    manifests = tuple(
        item
        for item in other_manifests
        if (item.owner.username, item.owner.machine_name)
        != (owner.username, owner.machine_name)
    ) + (render_manifest,)
    snapshots = {
        key: snapshot
        for key, snapshot in healthy.items()
        if key
        not in {(owner.username, owner.machine_name, hood) for hood in skip_hoods}
    }
    selected_keys = frozenset(changed_snapshots)
    bead_links, bead_diagnostics = build_bead_page_links(
        tuple(snapshots[key] for key in sorted(selected_keys) if key in snapshots),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    pages = render_targeted_browsing_payload(
        manifests,
        snapshots,
        selected_keys,
        bead_links=bead_links,
    )
    skipped = ", ".join(sorted(skip_hoods))
    return {**payload, **pages}, (
        *lenient_diagnostics,
        *bead_diagnostics,
        f"browsing pages exclude unreadable hood(s) {skipped}; "
        "manifest entries preserved",
    )


def protection_scope(target: ProjectTarget) -> PublicationProtectionScope:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

    return PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )
