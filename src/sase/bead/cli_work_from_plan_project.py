"""Frontmatter project routing for plan-file ``sase bead work``."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import error_with_resume
from sase.bead.cli_work_from_plan_types import PlanFileWorkError, PlanFileWorkResult
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin
    from sase.bead.operation_context import BeadOperationContext


@dataclass(frozen=True)
class _PlanFileProjectRoute:
    """Resolved frontmatter project for one plan-file launch."""

    authored: str
    label: str
    origin: BeadStoreOrigin
    context: BeadOperationContext | None
    cwd_foreign_label: str | None


def resolve_plan_file_project_route(
    source_path: Path,
    *,
    dry_run: bool,
    no_push: bool,
    parent: str | None,
    capacity: int | None,
) -> _PlanFileProjectRoute | None:
    """Read and resolve ``project`` after validation, before any mutation.

    Returns ``None`` when the field is absent so callers keep working-directory
    behavior. Unknown or ambiguous values fail closed with a resume hint.
    """

    from sase.bead.cross_project import (
        AmbiguousBeadProjectError,
        origin_for_project_ref,
    )
    from sase.bead.operation_context import (
        BeadOperationRoutingError,
        resolve_operation_context_for_project,
    )
    from sase.sdd.plan_project import read_plan_project_file

    authored = read_plan_project_file(source_path)
    if authored is None:
        return None
    try:
        origin = origin_for_project_ref(authored)
    except AmbiguousBeadProjectError as exc:
        raise error_with_resume(
            (
                f"epic plan {source_path} names project {authored!r}, but that "
                f"value is ambiguous: {exc}"
            ),
            source_path,
            no_push=no_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc
    if origin is None:
        raise error_with_resume(
            (
                f"epic plan {source_path} names project {authored!r}, but that "
                "project is unknown or not enabled; see `sase project list`"
            ),
            source_path,
            no_push=no_push,
            parent_override=parent,
            capacity=capacity,
        )
    label = origin.project_label or origin.project_key or authored
    if _invocation_belongs_to_project(origin):
        return _PlanFileProjectRoute(
            authored=authored,
            label=label,
            origin=origin,
            context=None,
            cwd_foreign_label=None,
        )
    try:
        context = resolve_operation_context_for_project(
            authored,
            for_write=not dry_run,
            materialize=not dry_run,
        )
    except BeadOperationRoutingError as exc:
        raise error_with_resume(
            (
                f"epic plan {source_path} names project {authored!r}, but that "
                f"project could not be opened: {exc}"
            ),
            source_path,
            no_push=no_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc
    return _PlanFileProjectRoute(
        authored=authored,
        label=label,
        origin=origin,
        context=context,
        cwd_foreign_label=_cwd_foreign_project_label(origin),
    )


def resolve_plan_file_parent_context(
    parent_id: str | None,
    *,
    source_path: Path,
    dry_run: bool,
    no_push: bool,
    parent: str | None,
    capacity: int | None,
    cwd: Path | None = None,
    expected_context: BeadOperationContext | None = None,
    frontmatter_label: str | None = None,
) -> BeadOperationContext | None:
    """Resolve ``parent_bead``/``--parent``, refusing a cross-project parent."""
    if parent_id is None:
        return None
    from sase.bead.operation_context import (
        BeadOperationRoutingError,
        resolve_operation_context_for_targets,
    )

    try:
        parent_context = resolve_operation_context_for_targets(
            [parent_id],
            cwd=cwd,
            for_write=not dry_run,
            materialize=not dry_run,
        )
    except BeadOperationRoutingError as exc:
        message = str(exc)
        missing = "not found" in message.casefold()
        detail = (
            f"epic plan {source_path} names parent bead {parent_id!r}, but that "
            "bead is missing from the active store and enabled project stores; "
            "restore the parent bead, choose another with --parent <bead-id>, "
            "or force a top-level epic with --parent top-level"
            if missing
            else (
                f"epic plan {source_path} names parent bead {parent_id!r}, but "
                f"that bead could not be resolved: {message}"
            )
        )
        raise error_with_resume(
            detail,
            source_path,
            no_push=no_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc
    if expected_context is not None and not _same_beads_dir(
        parent_context, expected_context
    ):
        parent_label = (
            parent_context.project_label
            or parent_context.project_key
            or "another project"
        )
        raise _parent_project_mismatch_error(
            source_path,
            parent_id,
            parent_label=parent_label,
            frontmatter_label=frontmatter_label or "the plan project",
            no_push=no_push,
            parent=parent,
            capacity=capacity,
        )
    return parent_context


def render_project_and_store(
    project_route: _PlanFileProjectRoute | None,
    *,
    store: SddStore,
    location: Any,
) -> None:
    """Print the optional Project line, then the Store line."""
    if project_route is not None:
        if project_route.cwd_foreign_label is not None:
            Console().print(
                "[yellow]→[/yellow] Routing         "
                f"frontmatter project {project_route.label} "
                f"(working directory is {project_route.cwd_foreign_label})"
            )
        Console().print(f"[green]✓[/green] Project         {project_route.label}")
    Console().print(
        "[green]✓[/green] Store           "
        f"{store.storage} · beads at {location.beads_dir}"
    )


def with_plan_project(
    result: PlanFileWorkResult, project_route: _PlanFileProjectRoute | None
) -> PlanFileWorkResult:
    """Attach the frontmatter project label to a plan-file result."""
    if project_route is None:
        return result
    return replace(result, project=project_route.label)


def _invocation_belongs_to_project(
    origin: Any,
    *,
    cwd: Path | None = None,
) -> bool:
    """Return whether *cwd* is already inside *origin*'s project.

    True for the primary checkout, a numbered workspace, or a host-leased
    checkout of the same project. Those invocations keep local store
    resolution instead of routing through the primary.
    """

    invocation_cwd = (Path.cwd() if cwd is None else cwd).expanduser().resolve()
    refs = _folded_project_refs(origin)
    primary = getattr(origin, "primary_workspace", None)
    project_key = getattr(origin, "project_key", None)
    project_label = getattr(origin, "project_label", None)
    if primary is not None:
        primary = Path(primary).expanduser().resolve()

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(invocation_cwd))
    except Exception:
        found = None
    if found is not None:
        _checkout, marker = found
        for value in (marker.project_name, marker.project_key):
            if isinstance(value, str) and value.strip().casefold() in refs:
                return True
        marker_primary = marker.primary_workspace_dir.strip()
        if (
            marker_primary
            and primary is not None
            and _same_path(Path(marker_primary), primary)
        ):
            return True

    if primary is not None:
        try:
            from sase.bead.project_name import cwd_matches_project_workspace

            for name in (project_key, project_label):
                if not isinstance(name, str) or not name:
                    continue
                if cwd_matches_project_workspace(str(invocation_cwd), primary, name):
                    return True
        except Exception:
            if _same_path(invocation_cwd, primary) or _is_relative_to(
                invocation_cwd, primary
            ):
                return True

    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        inferred = infer_project_name_from_cwd(str(invocation_cwd))
    except Exception:
        inferred = None
    if isinstance(inferred, str) and inferred.casefold() in refs:
        return True

    try:
        from sase.workspace_provider import ownership

        context = ownership.user_directed_context(cwd=invocation_cwd)
    except Exception:
        context = None
    if context is not None:
        invocation_project = getattr(context, "project", None)
        if (
            isinstance(invocation_project, str)
            and invocation_project.casefold() in refs
        ):
            return True
        invocation_primary = getattr(context, "primary_checkout_dir", None)
        if (
            invocation_primary is not None
            and primary is not None
            and _same_path(Path(invocation_primary), primary)
        ):
            return True
    return False


def _parent_project_mismatch_error(
    source_path: Path,
    parent_id: str,
    *,
    parent_label: str,
    frontmatter_label: str,
    no_push: bool,
    parent: str | None,
    capacity: int | None,
) -> PlanFileWorkError:
    """Refuse a parent that belongs to a different project than frontmatter."""

    return error_with_resume(
        (
            f"epic plan {source_path} names parent bead {parent_id!r} in "
            f"project {parent_label}, but the plan's frontmatter project is "
            f"{frontmatter_label}; use a parent in that project, or force a "
            "top-level epic with --parent top-level"
        ),
        source_path,
        no_push=no_push,
        parent_override=parent,
        capacity=capacity,
    )


def _cwd_foreign_project_label(origin: BeadStoreOrigin) -> str | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    cwd = Path.cwd().expanduser().resolve()
    refs = _folded_project_refs(origin)
    try:
        inferred = infer_project_name_from_cwd(str(cwd))
    except Exception:
        inferred = None
    if isinstance(inferred, str) and inferred.strip():
        return None if inferred.casefold() in refs else inferred
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(cwd))
    except Exception:
        found = None
    if found is None:
        return None
    _checkout, marker = found
    for value in (marker.project_name, marker.project_key):
        if isinstance(value, str) and value.strip():
            if value.casefold() in refs:
                return None
            return value
    return None


def _folded_project_refs(origin: Any) -> set[str]:
    refs = {
        value.strip()
        for value in (
            getattr(origin, "project_key", None),
            getattr(origin, "project_label", None),
        )
        if isinstance(value, str) and value.strip()
    }
    return {value.casefold() for value in refs}


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(
        strict=False
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _same_beads_dir(left: BeadOperationContext, right: BeadOperationContext) -> bool:
    return _same_path(left.beads_dir, right.beads_dir)


__all__ = [
    "render_project_and_store",
    "resolve_plan_file_parent_context",
    "resolve_plan_file_project_route",
    "with_plan_project",
]
