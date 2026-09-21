"""Shared helpers for bead CLI handlers.

Store access (``init_beads``, ``get_project``, ``get_read_view``) and the
single-mutation lane (``auto_commit_bead_store``, ``bead_store_mutation``) live
here; the remaining helpers live in focused modules and are re-exported to keep
the historical ``sase.bead.cli_common`` import surface intact:

- ``cli_common_publication`` — publication errors and push verification
- ``cli_common_routing`` — operation-context routing for CLI targets
- ``cli_common_paths`` — workspace/plan-path mapping
- ``cli_common_presentation`` — single-line row presentation

Patch the module that defines a helper (``cli_common_publication``,
``cli_common_paths``, ...), not this facade.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.bead.cli_common_paths import normalize_workspace_path, storage_plan_path
from sase.bead.cli_common_presentation import created_cell, status_icon
from sase.bead.cli_common_publication import (
    BeadPublicationError,
    emit_routed_bead_publication_failure,
    ensure_bead_mutation_published,
    routed_bead_context_requires_publication,
)
from sase.bead.cli_common_routing import resolve_bead_operation_context
from sase.bead.cli_location import (
    BeadsLocation,
    bead_store_exists,
    find_beads_location,
    resolve_beads_location,
    resolved_beads_location_is_usable,
)
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
    BeadProject,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.bead.operation_context import BeadOperationContext

# Backward-compatible alias for tests and downstream imports of the old module.
_BeadsLocation = BeadsLocation

__all__ = [
    "BeadPublicationError",
    "BeadsLocation",
    "_BeadsLocation",
    "_push_committed_bead_store",
    "auto_commit_bead_store",
    "bead_store_exists",
    "bead_store_mutation",
    "created_cell",
    "emit_routed_bead_publication_failure",
    "ensure_bead_mutation_published",
    "find_beads_location",
    "get_project",
    "get_read_view",
    "init_beads",
    "normalize_workspace_path",
    "resolve_bead_operation_context",
    "resolve_beads_location",
    "resolved_beads_location_is_usable",
    "routed_bead_context_requires_publication",
    "status_icon",
    "storage_plan_path",
]


@dataclass
class _BeadStoreMutation:
    """One CLI mutation whose commit remains inside the store lock."""

    project: BeadProject
    commit_message: str | None = None
    publication_outcome: Any | None = None

    def commit(self, message: str) -> None:
        self.commit_message = message


def init_beads(root: Path, beads_dirname: str) -> None:
    """Initialize beads at the given location.

    For non-VC mode, bootstraps a standalone git repo inside the SDD directory.
    """
    if beads_dirname == BEADS_DIRNAME:
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(root, commit=True, push=False)
    if beads_dirname in {BEADS_DIRNAME_NON_VC, BEADS_DIRNAME_ROOT}:
        import subprocess

        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").is_dir():
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        from sase.sdd._bead_ignore import ensure_bead_store_gitignore

        ensure_bead_store_gitignore(
            root,
            prefix="" if beads_dirname == BEADS_DIRNAME_ROOT else "beads",
        )
    with BeadProject.init(root, beads_dirname=beads_dirname):
        pass
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        from sase.sdd.files import commit_sdd_files

        commit_sdd_files(root, "Initialize beads", auto_commit_type="beads")


def get_project(
    *,
    cwd: Path | None = None,
    bead_context: BeadOperationContext | None = None,
) -> BeadProject:
    """Open the BeadProject for write operations, auto-initializing if needed."""
    if bead_context is not None:
        from sase.bead.operation_context import project_for_operation_context

        return project_for_operation_context(bead_context)

    location = resolve_beads_location(cwd=cwd, require_existing=True)
    _refuse_read_only_bead_store(location, operation="mutation")
    from sase.bead.sync import bead_refresh_mode

    if (
        location is None
        or not resolved_beads_location_is_usable(location)
        or bead_refresh_mode() == "blocking"
    ):
        location = resolve_beads_location(cwd=cwd, materialize=True)
        _refuse_read_only_bead_store(location, operation="mutation")

    if location is None:
        root, beads_dirname = find_beads_location(cwd=cwd, materialize=True)
    else:
        root, beads_dirname = location.root, location.beads_dirname
    if not bead_store_exists(root, beads_dirname):
        init_beads(root, beads_dirname)
    return BeadProject(root, beads_dirname=beads_dirname)


def get_read_view(*, bead_context: BeadOperationContext | None = None) -> BeadProject:
    """Open the same single bead store used by write commands."""
    if bead_context is not None:
        from sase.bead.operation_context import read_view_for_operation_context

        return read_view_for_operation_context(bead_context)

    location = resolve_beads_location(require_existing=True)
    if location is not None and location.read_only:
        return BeadProject(location.root, beads_dirname=location.beads_dirname)
    return get_project()


def _refuse_read_only_bead_store(
    location: BeadsLocation | None,
    *,
    operation: str,
) -> None:
    if location is None or not location.read_only:
        return
    raise RuntimeError(
        f"Refusing bead-store {operation} from a plain checkout: "
        f"{location.beads_dir} was discovered through a checkout-local "
        ".sase/sdd-store.json record and is available for reads only."
    )


def auto_commit_bead_store(
    message: str,
    *,
    push_after_commit: bool | Literal["async"] | None = None,
    already_locked: bool = False,
    cwd: Path | None = None,
    mutation_origin: str = "user",
    operation_context: Any | None = None,
    bead_context: BeadOperationContext | None = None,
) -> bool:
    """Best-effort commit/push for non-in-tree SDD bead store mutations."""
    try:
        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import SddStore

        from sase.bead.operation_context import (
            location_from_operation_context,
            ownership_context_for_commit,
        )

        location = location_from_operation_context(
            bead_context,
            cwd=cwd,
            require_existing=True,
        )
        if location is None or location.is_in_tree or location.read_only:
            return False
        store = location.store or SddStore(
            storage="local",
            sdd_dir=location.root,
            repo_root=location.root,
        )
        commit_kwargs: dict[str, Any] = {}
        if push_after_commit is not None:
            commit_kwargs["push_after_commit"] = push_after_commit
        if already_locked:
            commit_kwargs["already_locked"] = True
        if mutation_origin != "user":
            commit_kwargs["mutation_origin"] = mutation_origin
        if operation_context is None:
            operation_context = ownership_context_for_commit(bead_context)
        if operation_context is not None:
            commit_kwargs["operation_context"] = operation_context
        return bool(
            commit_sdd_store_files(
                store,
                message,
                auto_commit_type="beads",
                paths=[location.beads_dir],
                **commit_kwargs,
            )
        )
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        from sase.bead._stream_integrity import BeadStreamIntegrityError

        if isinstance(
            exc,
            (
                SddMaterializationError,
                SddRepositoryHealthError,
                BeadStreamIntegrityError,
            ),
        ):
            raise
        _logger.warning(
            "Failed to auto-commit SDD bead store changes",
            exc_info=True,
        )
        return False


@contextmanager
def bead_store_mutation(
    auto_commit: Callable[..., bool] = auto_commit_bead_store,
    *,
    no_push: bool = False,
    cwd: Path | None = None,
    mutation_origin: str = "user",
    operation_context: Any | None = None,
    bead_context: BeadOperationContext | None = None,
) -> Iterator[_BeadStoreMutation]:
    """Keep one CLI bead mutation and its commit under one store lock."""
    from sase.bead.sync import bead_store_write_lock

    committed = False
    routed_bead_context = _routed_bead_context(bead_context)
    with get_project(cwd=cwd, bead_context=bead_context) as project:
        with bead_store_write_lock(project.beads_dir) as already_locked:
            mutation = _BeadStoreMutation(project)
            yield mutation
            if (
                mutation.commit_message is not None
                and mutation.project.mutation_changed
            ):
                commit_kwargs: dict[str, Any] = {
                    "push_after_commit": False,
                    "already_locked": already_locked,
                }
                if cwd is not None:
                    commit_kwargs["cwd"] = cwd
                if mutation_origin != "user":
                    commit_kwargs["mutation_origin"] = mutation_origin
                if operation_context is not None:
                    commit_kwargs["operation_context"] = operation_context
                if routed_bead_context is not None:
                    commit_kwargs["bead_context"] = routed_bead_context
                try:
                    committed = auto_commit(mutation.commit_message, **commit_kwargs)
                except Exception as exc:
                    if routed_bead_context_requires_publication(routed_bead_context):
                        raise emit_routed_bead_publication_failure(
                            mutation.commit_message,
                            bead_context=routed_bead_context,
                            cause=exc,
                        ) from exc
                    raise
                if not committed and routed_bead_context_requires_publication(
                    routed_bead_context
                ):
                    raise emit_routed_bead_publication_failure(
                        mutation.commit_message,
                        bead_context=routed_bead_context,
                    )
    if committed and not no_push:
        push_kwargs: dict[str, Any] = {}
        if cwd is not None:
            push_kwargs["cwd"] = cwd
        if routed_bead_context is not None:
            push_kwargs["bead_context"] = routed_bead_context
        mutation.publication_outcome = _push_committed_bead_store(**push_kwargs)
        verify_kwargs: dict[str, Any] = {"description": mutation.commit_message}
        if cwd is not None:
            verify_kwargs["cwd"] = cwd
        if routed_bead_context is not None:
            verify_kwargs["bead_context"] = routed_bead_context
        verified = _require_published_bead_mutation(**verify_kwargs)
        if verified is not None:
            mutation.publication_outcome = verified
    if committed:
        _refresh_touch_index_after_mutation(mutation.project.beads_dir, cwd=cwd)


def _routed_bead_context(
    bead_context: BeadOperationContext | None,
) -> BeadOperationContext | None:
    if bead_context is None or bead_context.project_key is None:
        return None
    return bead_context


def _require_published_bead_mutation(
    *,
    description: str | None,
    cwd: Path | None = None,
    bead_context: BeadOperationContext | None = None,
) -> Any | None:
    """Fail the mutation when its commit never reached the canonical remote."""
    from sase.bead.operation_context import location_from_operation_context

    location = location_from_operation_context(
        bead_context,
        cwd=cwd,
        require_existing=True,
    )
    if location is None or location.is_in_tree or location.read_only:
        return None
    return ensure_bead_mutation_published(location.beads_dir, description=description)


def _push_committed_bead_store(
    *,
    cwd: Path | None = None,
    bead_context: BeadOperationContext | None = None,
) -> Any | None:
    """Apply the configured push policy after the mutation lock is released."""
    try:
        from sase.sdd._commit_store import (
            push_sdd_store_after_commit,
            sdd_commit_targets,
        )
        from sase.sdd.store import SddStore

        from sase.bead.operation_context import location_from_operation_context

        location = location_from_operation_context(
            bead_context,
            cwd=cwd,
            require_existing=True,
        )
        if location is None or location.is_in_tree:
            return None
        store = location.store or SddStore(
            storage="local",
            sdd_dir=location.root,
            repo_root=location.root,
        )
        last_outcome = None
        for target_store, _paths in sdd_commit_targets(
            store,
            [location.beads_dir],
        ):
            last_outcome = push_sdd_store_after_commit(
                target_store, push_after_commit=None
            )
        return last_outcome
    except Exception:
        _logger.warning(
            "Failed to synchronize committed SDD bead store changes",
            exc_info=True,
        )
        return None


def _refresh_touch_index_after_mutation(beads_dir: Path, cwd: Path | None) -> None:
    """Refresh the agent/bead touch index after a mutation commits.

    Best-effort and off the panel's hot path: a failure logs inside the
    facade and is swallowed, so an agent's own edit can never break the
    mutation that just committed. An unresolvable project is a quiet skip;
    the lumberjack tick converges the store instead.
    """
    try:
        from sase.core.bead_touch_index_facade import (
            refresh_touch_index_best_effort,
        )

        refresh_touch_index_best_effort(beads_dir, cwd=cwd)
    except Exception:
        _logger.warning(
            "Skipping bead touch-index refresh after mutation",
            exc_info=True,
        )
