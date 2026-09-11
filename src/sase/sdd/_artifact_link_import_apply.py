"""Resumable apply loop for artifact-link legacy-index import."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import fcntl
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any, Literal

from sase.agents_sync.io import atomic_write_bytes
from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_commit import (
    artifact_link_publication_error_for_roots,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkCutoverMarker,
    artifact_link_cutover_marker_path,
    read_artifact_link_cutover_marker,
)
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_LOCK_FILENAME,
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_install import event_object_is_durable
from sase.sdd._artifact_link_import_plan import (
    ArtifactLinkIndexImportPlan,
    assert_same_import,
    plan_artifact_link_index_import,
)
from sase.sdd.artifact_link_outbox import inspect_artifact_link_outbox

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore


@dataclass(frozen=True, slots=True)
class ArtifactLinkIndexImportReport:
    """Result of a preview or apply run."""

    plan: ArtifactLinkIndexImportPlan
    applied: bool
    already_imported: bool = False
    converted_outbox_entries: int = 0
    covered_outbox_entries: int = 0
    outbox_conversion_diagnostics: tuple[str, ...] = ()
    queued_legacy_outbox_entries: int = 0
    queued_invalid_outbox_entries: int = 0
    fenced_markers_changed: tuple[Path, ...] = ()
    event_paths: tuple[Path, ...] = ()
    imported_markers_changed: tuple[Path, ...] = ()
    aggregate_rows: int = 0
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "aggregate_rows": self.aggregate_rows,
            "already_imported": self.already_imported,
            "applied": self.applied,
            "converted_outbox_entries": self.converted_outbox_entries,
            "covered_outbox_entries": self.covered_outbox_entries,
            "event_paths": [str(path) for path in self.event_paths],
            "fenced_markers_changed": [
                str(path) for path in self.fenced_markers_changed
            ],
            "imported_markers_changed": [
                str(path) for path in self.imported_markers_changed
            ],
            "outbox_conversion_diagnostics": list(self.outbox_conversion_diagnostics),
            "plan": self.plan.to_json_dict(),
            "publication_error": self.publication_error,
            "queued_invalid_outbox_entries": self.queued_invalid_outbox_entries,
            "queued_legacy_outbox_entries": self.queued_legacy_outbox_entries,
            "skip_diagnostics": list(self.skip_diagnostics),
        }


def import_artifact_link_indexes(
    store: ArtifactLinkStore,
    *,
    apply: bool = False,
    push_after_commit: bool | Literal["async"] | None = "async",
) -> ArtifactLinkIndexImportReport:
    """Preview or apply the legacy-index import."""

    plan = plan_artifact_link_index_import(store)
    outbox = inspect_artifact_link_outbox(store.project_key)
    if not apply:
        return ArtifactLinkIndexImportReport(
            plan=plan,
            applied=False,
            aggregate_rows=len(store.load_aggregate().get("rows", [])),
            queued_legacy_outbox_entries=outbox.legacy_queued,
            queued_invalid_outbox_entries=outbox.invalid_queued,
        )

    lock_path = (
        sase_projects_dir() / store.project_key / ARTIFACT_LINK_EVENT_LOCK_FILENAME
    )
    with locked_file(lock_path, fcntl.LOCK_EX):
        return _apply_import_locked(
            store,
            push_after_commit=push_after_commit,
        )


def _apply_import_locked(
    store: ArtifactLinkStore,
    *,
    push_after_commit: bool | Literal["async"] | None,
) -> ArtifactLinkIndexImportReport:
    from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
    from sase.sdd.artifact_link_outbox import (
        convert_legacy_artifact_link_outbox_entries,
    )

    converted = 0
    covered = 0
    conversion_diagnostics: list[str] = []
    fenced_changed: list[Path] = []
    imported_changed: list[Path] = []
    event_paths: list[Path] = []
    skip_diagnostics: list[str] = []
    seen_states: set[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = (
        set()
    )

    while True:
        plan = plan_artifact_link_index_import(store)
        progress = _import_progress(store, plan)
        if progress["conflicts"]:
            raise RuntimeError("\n".join(str(item) for item in progress["conflicts"]))
        phase = str(progress["phase"])
        state_key = (
            phase,
            tuple(str(item) for item in progress["roles_needing_fence_marker"]),
            tuple(str(item) for item in progress["roles_needing_baseline_event"]),
            tuple(str(item) for item in progress["roles_needing_imported_marker"]),
        )
        if state_key in seen_states:
            raise RuntimeError(f"artifact-link cutover made no progress: {state_key}")
        seen_states.add(state_key)

        if phase == "complete":
            aggregate = store.rebuild_aggregate()
            publication_error = _publication_error_for_imported_roots(
                store,
                plan,
                push_after_commit,
            )
            if publication_error:
                raise RuntimeError(publication_error)
            outbox = inspect_artifact_link_outbox(store.project_key)
            return ArtifactLinkIndexImportReport(
                plan=plan,
                applied=True,
                already_imported=not (
                    fenced_changed
                    or imported_changed
                    or event_paths
                    or converted
                    or covered
                ),
                converted_outbox_entries=converted,
                covered_outbox_entries=covered,
                outbox_conversion_diagnostics=tuple(conversion_diagnostics),
                queued_legacy_outbox_entries=outbox.legacy_queued,
                queued_invalid_outbox_entries=outbox.invalid_queued,
                fenced_markers_changed=tuple(dict.fromkeys(fenced_changed)),
                event_paths=tuple(dict.fromkeys(event_paths)),
                imported_markers_changed=tuple(dict.fromkeys(imported_changed)),
                aggregate_rows=len(aggregate.get("rows", [])),
                skip_diagnostics=tuple(dict.fromkeys(skip_diagnostics)),
            )

        if phase == "fence":
            fenced_changed.extend(
                _publish_marker(
                    plan,
                    plan.fenced_marker,
                    progress["roles_needing_fence_marker"],
                    store,
                    push_after_commit,
                )
            )
            continue

        if phase == "publish_baseline":
            conversion = convert_legacy_artifact_link_outbox_entries(
                store.project_key,
                baseline_rows=plan.rows,
            )
            converted += conversion.converted
            covered += conversion.covered
            conversion_diagnostics.extend(conversion.invalid)
            publish = publish_artifact_link_events(
                store,
                (plan.baseline_event,),
                push_after_commit=push_after_commit,
                mutation_origin="machine",
                already_locked=True,
                extra_roots=plan.sidecar_roots,
            )
            if publish.publication_error:
                raise RuntimeError(publish.publication_error)
            if publish.published != 1:
                diagnostic = (
                    "\n".join(publish.skip_diagnostics)
                    or "artifact-link baseline import event was not durable"
                )
                raise RuntimeError(diagnostic)
            event_paths.extend(publish.event_paths)
            skip_diagnostics.extend(publish.skip_diagnostics)
            _assert_baseline_durable(plan)
            continue

        if phase == "mark_imported":
            imported_changed.extend(
                _publish_marker(
                    plan,
                    plan.imported_marker,
                    progress["roles_needing_imported_marker"],
                    store,
                    push_after_commit,
                )
            )
            continue

        raise RuntimeError(f"unsupported artifact-link cutover phase: {phase}")


def _import_progress(
    store: ArtifactLinkStore,
    plan: ArtifactLinkIndexImportPlan,
) -> dict[str, Any]:
    observations = []
    baseline_object = canonical_artifact_link_event_object(plan.baseline_event)
    for role in plan.roles:
        marker = read_artifact_link_cutover_marker(
            role.root,
            expected_project_key=plan.project_key,
        )
        observations.append(
            {
                "baseline_durable": event_object_is_durable(
                    role.root,
                    baseline_object,
                ),
                "marker": None if marker is None else marker.payload,
                "marker_committed": _marker_is_committed(role.root, marker),
                "role": role.role,
            }
        )
    return dict(
        require_rust_binding("artifact_link_cutover_progress")(
            {
                "expected": plan.fenced_marker.payload,
                "roots": observations,
            }
        )
    )


def _marker_is_committed(
    root: Path,
    marker: ArtifactLinkCutoverMarker | None,
) -> bool:
    if marker is None:
        return False
    relative = artifact_link_cutover_marker_path(root).relative_to(
        root.expanduser().resolve(strict=False)
    )
    result = _git_show(root, relative.as_posix())
    return result == marker.canonical_bytes


def _publish_marker(
    plan: ArtifactLinkIndexImportPlan,
    marker: ArtifactLinkCutoverMarker,
    roles: Iterable[str],
    store: ArtifactLinkStore,
    push_after_commit: bool | Literal["async"] | None,
) -> tuple[Path, ...]:
    payload = marker.canonical_bytes
    changed_by_root: dict[Path, list[Path]] = {}
    changed: list[Path] = []
    for role in plan.role_by_name(roles):
        path = artifact_link_cutover_marker_path(role.root)
        if path.is_symlink():
            raise RuntimeError(f"artifact-link cutover marker is a symlink: {path}")
        if path.is_file() and path.read_bytes() != payload:
            existing = read_artifact_link_cutover_marker(
                role.root,
                expected_project_key=plan.project_key,
            )
            if existing is not None:
                assert_same_import(existing, marker)
        if not path.is_file() or path.read_bytes() != payload:
            atomic_write_bytes(path, payload)
        changed.append(path)
        changed_by_root.setdefault(role.root, []).append(path)
    if changed:
        result = commit_artifact_link_indexes(
            (),
            store=store.sdd_store,
            project_key=plan.project_key,
            repo_roots=plan.sidecar_roots,
            extra_paths_by_root=changed_by_root,
            mutation_origin="machine",
            push_after_commit=push_after_commit,
            verify_publication=True,
            message="chore(artifact-links): persist link event store marker",
        )
        if result.publication_error:
            raise RuntimeError(result.publication_error)
    return tuple(changed)


def _publication_error_for_imported_roots(
    store: ArtifactLinkStore,
    plan: ArtifactLinkIndexImportPlan,
    push_after_commit: bool | Literal["async"] | None,
) -> str | None:
    if push_after_commit is False:
        return None
    return artifact_link_publication_error_for_roots(
        plan.sidecar_roots,
        store=store.sdd_store,
        project_key=store.project_key,
        register_retry=True,
        description="chore(artifact-links): persist link event store marker",
    )


def _assert_baseline_durable(plan: ArtifactLinkIndexImportPlan) -> None:
    baseline_object = canonical_artifact_link_event_object(plan.baseline_event)
    missing = [
        role.role
        for role in plan.roles
        if not event_object_is_durable(role.root, baseline_object)
    ]
    if missing:
        raise RuntimeError(
            "baseline import event is not durable for roles: " + ", ".join(missing)
        )


def _git_show(root: Path, relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


__all__ = [
    "ArtifactLinkIndexImportReport",
    "import_artifact_link_indexes",
]
