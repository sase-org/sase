"""Referenced By index checks for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.sdd.referenced_by_doctor import missing_referenced_by_indexes
from sase.sdd.store import document_sidecar_roles

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext
    from sase.sdd.store import SddStore

_MAX_DETAIL_ROWS = 10


def referenced_by_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return Referenced By index check specs."""

    return (
        CheckSpec(
            id="project.referenced_by_index",
            group="project",
            title="Referenced By index",
            runner=lambda: _check_referenced_by_index(context),
        ),
    )


def _check_referenced_by_index(context: DoctorContext) -> DiagnosticCheck:
    """Error when a committed Referenced By block has no ``links/`` JSON in HEAD."""

    store = _resolve_store(context)
    if store is None:
        return DiagnosticCheck(
            id="project.referenced_by_index",
            group="project",
            status="SKIP",
            title="Referenced By index",
            summary="no SDD store found in this checkout",
            data={"missing": ()},
        )

    missing = _missing_for_store(store)
    status: CheckStatus = "ERROR" if missing else "OK"
    summary = (
        f"{len(missing)} committed Referenced By block(s) missing links/ JSON in HEAD"
        if missing
        else "Referenced By blocks have committed links/ indexes"
    )
    return DiagnosticCheck(
        id="project.referenced_by_index",
        group="project",
        status=status,
        title="Referenced By index",
        summary=summary,
        details=tuple(missing[:_MAX_DETAIL_ROWS]),
        next_steps=(
            (
                "Write `links/<artifact-relpath>.json` for each cited document "
                "and commit it with the Referenced By refresh."
            ),
        )
        if missing
        else (),
        data={"missing": missing},
    )


def _missing_for_store(store: SddStore) -> tuple[str, ...]:
    missing: list[str] = []
    seen: set[Path] = set()
    roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
    for role in roles:
        try:
            root = store.repo_root_for_kind(role).expanduser().resolve(strict=False)
        except Exception:  # noqa: BLE001 - a doctor check never breaks the report.
            continue
        if not root.is_dir() or root in seen:
            continue
        seen.add(root)
        for relpath in missing_referenced_by_indexes(root):
            missing.append(f"{role}:{relpath}")
    return tuple(missing)


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


__all__ = ["referenced_by_check_specs"]
