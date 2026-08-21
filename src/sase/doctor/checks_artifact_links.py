"""Artifact-link aggregate checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    artifact_link_aggregate_path,
    resolve_artifact_link_project_key,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext
    from sase.sdd.store import SddStore

_CHECK_ID = "project.artifact_links_aggregate"


def artifact_links_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return artifact-link aggregate check specs."""

    return (
        CheckSpec(
            id=_CHECK_ID,
            group="project",
            title="Artifact link aggregate",
            runner=lambda: _check_artifact_links_aggregate(context),
        ),
    )


def _check_artifact_links_aggregate(context: DoctorContext) -> DiagnosticCheck:
    """Rebuild-compare the project aggregate against sidecar ``links/`` JSON."""

    store = _resolve_store(context)
    if store is None:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="SKIP",
            title="Artifact link aggregate",
            summary="no SDD store found in this checkout",
            data={"stale": False},
        )

    try:
        project_key = _project_key(context)
    except Exception as exc:  # noqa: BLE001 - make config failures actionable
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="ERROR",
            title="Artifact link aggregate",
            summary="could not resolve a canonical project key for artifact links",
            next_steps=str(exc),
            data={"stale": False, "error": str(exc)},
        )
    if not project_key:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="ERROR",
            title="Artifact link aggregate",
            summary="could not resolve a canonical project key for artifact links",
            next_steps=(
                "Check the workspace marker, ProjectSpec key, PROJECT_NAME, "
                "aliases, and provider slug for this checkout."
            ),
            data={"stale": False},
        )

    adapter = ArtifactLinkStore.from_sdd_store(store, project_key)
    on_disk = adapter.load_aggregate()
    expected = adapter.preview_aggregate()
    stale = _rows_signature(on_disk) != _rows_signature(expected)
    missing = not artifact_link_aggregate_path(project_key).is_file()
    expected_count = len(expected["rows"])
    if missing and expected_count == 0:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="OK",
            title="Artifact link aggregate",
            summary="no artifact link rows to index",
            data={"stale": False, "rows": 0},
        )
    if missing or stale:
        status: CheckStatus = "ERROR"
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status=status,
            title="Artifact link aggregate",
            summary=(
                "artifact-links aggregate is missing or stale versus sidecar links/"
            ),
            next_steps=(
                "Rebuild ~/.sase/projects/<key>/artifact-links.json "
                "from sidecar links/ JSON.",
            ),
            data={
                "stale": True,
                "missing": missing,
                "rows": expected_count,
            },
        )
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="OK",
        title="Artifact link aggregate",
        summary=f"{expected_count} artifact link row(s) indexed",
        data={"stale": False, "rows": expected_count},
    )


def _rows_signature(document: dict[str, object]) -> tuple[tuple[object, ...], ...]:
    rows = document.get("rows")
    if not isinstance(rows, list):
        return ()
    signatures: list[tuple[object, ...]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        signatures.append(
            (
                str(row.get("source_ref") or ""),
                str(row.get("relation") or ""),
                str(row.get("target_ref") or ""),
                str(row.get("description") or ""),
                int(row.get("uses") or 0),
            )
        )
    return tuple(sorted(signatures))


def _project_key(context: DoctorContext) -> str | None:
    return resolve_artifact_link_project_key(context.cwd, fallback=context.project)


def _resolve_store(context: DoctorContext) -> SddStore | None:
    try:
        from sase.sdd.checkout_anchor import resolve_checkout_anchor
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        anchor = resolve_checkout_anchor(context.cwd)
        primary_root, workspace_num = workspace_context_for_plan_resolution(
            anchor.primary_root
        )
        return resolve_sdd_store(primary_root, workspace_num)
    except Exception:  # noqa: BLE001 - a doctor check never breaks the report.
        return None


__all__ = ["artifact_links_check_specs"]
