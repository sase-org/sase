"""Shared helpers for bead CLI handlers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import sys
from pathlib import Path
from typing import Any, Literal

from sase.bead.cli_location import (
    BeadsLocation,
    bead_store_exists,
    find_beads_location,
    resolve_beads_location,
    resolved_beads_location_is_usable,
)
from sase.bead.model import Issue, Status
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
    BeadProject,
)

_logger = logging.getLogger(__name__)

# Backward-compatible alias for tests and downstream imports of the old module.
_BeadsLocation = BeadsLocation


class BeadPublicationError(RuntimeError):
    """Raised when a committed bead mutation could not be published.

    The mutation exists in the local store only, so its command must fail
    loudly rather than report a success nobody else can observe.
    """


@dataclass
class _BeadStoreMutation:
    """One CLI mutation whose commit remains inside the store lock."""

    project: BeadProject
    commit_message: str | None = None

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


def get_project(*, cwd: Path | None = None) -> BeadProject:
    """Open the BeadProject for write operations, auto-initializing if needed."""
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


def get_read_view() -> BeadProject:
    """Open the same single bead store used by write commands."""
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
) -> bool:
    """Best-effort commit/push for non-in-tree SDD bead store mutations."""
    try:
        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import SddStore

        location = resolve_beads_location(cwd=cwd, require_existing=True)
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
        return commit_sdd_store_files(
            store,
            message,
            auto_commit_type="beads",
            paths=[location.beads_dir],
            **commit_kwargs,
        )
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if isinstance(exc, (SddMaterializationError, SddRepositoryHealthError)):
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
) -> Iterator[_BeadStoreMutation]:
    """Keep one CLI bead mutation and its commit under one store lock."""
    from sase.bead.sync import bead_store_write_lock

    committed = False
    with get_project(cwd=cwd) as project:
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
                committed = auto_commit(mutation.commit_message, **commit_kwargs)
    if committed and not no_push:
        if cwd is None:
            _push_committed_bead_store()
        else:
            _push_committed_bead_store(cwd=cwd)
        _require_published_bead_mutation(
            description=mutation.commit_message,
            cwd=cwd,
        )


def _require_published_bead_mutation(
    *,
    description: str | None,
    cwd: Path | None = None,
) -> None:
    """Fail the mutation when its commit never reached the canonical remote."""
    location = resolve_beads_location(cwd=cwd, require_existing=True)
    if location is None or location.is_in_tree or location.read_only:
        return
    ensure_bead_mutation_published(location.beads_dir, description=description)


def ensure_bead_mutation_published(
    beads_dir: Path,
    *,
    description: str | None = None,
) -> None:
    """Verify a committed bead mutation was published; publish it if not.

    The configured push policy may be queued, detached, or aimed at a
    different checkout than the one holding the commit, so this runs above it:
    it asks whether the commit actually reached the remote and, when it did
    not, forces one synchronous push against the store that holds it. A store
    with no upstream is not applicable and stays silent.

    Raises ``BeadPublicationError`` when bead commits remain unpublished.
    """
    from sase.bead.sync import (
        MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        bead_publication_failure_lines,
        push_bead_work_launch,
        verify_bead_store_published,
    )

    try:
        status = verify_bead_store_published(beads_dir)
        if status.published:
            return
        push_bead_work_launch(
            beads_dir,
            worker_lock_wait=MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        )
        status = verify_bead_store_published(beads_dir)
        if status.published:
            return
        lines = bead_publication_failure_lines(status, description=description)
    except Exception:
        # Verification must never turn an otherwise healthy mutation into a
        # failure because the check itself broke.
        _logger.warning(
            "Failed to verify publication of committed bead state",
            exc_info=True,
        )
        return

    for line in lines:
        print(line, file=sys.stderr)
    raise BeadPublicationError(lines[0])


def _push_committed_bead_store(*, cwd: Path | None = None) -> None:
    """Apply the configured push policy after the mutation lock is released."""
    try:
        from sase.sdd._commit_store import (
            push_sdd_store_after_commit,
            sdd_commit_targets,
        )
        from sase.sdd.store import SddStore

        location = resolve_beads_location(cwd=cwd, require_existing=True)
        if location is None or location.is_in_tree:
            return
        store = location.store or SddStore(
            storage="local",
            sdd_dir=location.root,
            repo_root=location.root,
        )
        for target_store, _paths in sdd_commit_targets(
            store,
            [location.beads_dir],
        ):
            push_sdd_store_after_commit(target_store, push_after_commit=None)
    except Exception:
        _logger.warning(
            "Failed to synchronize committed SDD bead store changes",
            exc_info=True,
        )


def normalize_workspace_path(resolved: Path) -> Path:
    """Normalize a path from an ephemeral workspace to the primary workspace.

    If ``resolved`` is inside a sibling workspace (same parent directory as the
    primary workspace), rewrite it to be rooted at the primary workspace instead.
    This prevents ephemeral ``sase_<N>`` prefixes from leaking into stored paths.
    """
    from sase.bead.workspace import resolve_primary_workspace

    primary = resolve_primary_workspace()
    if not primary:
        return resolved

    try:
        resolved.relative_to(primary)
        return resolved  # already inside primary
    except ValueError:
        pass

    # Check if inside a sibling workspace (same parent directory)
    try:
        rel_to_parent = resolved.relative_to(primary.parent)
    except ValueError:
        return resolved  # not in a sibling workspace

    parts = rel_to_parent.parts
    if len(parts) > 1:
        return primary / Path(*parts[1:])
    return resolved


def storage_plan_path(resolved: Path) -> str:
    """Return the plan path representation to persist on a bead.

    Plans below a known SDD or local-archive plans root use canonical
    ``plans:`` references. External paths keep the legacy relative/absolute
    fallback after workspace-prefix normalization.
    """
    canonical = _canonical_storage_plan_path(resolved)
    if canonical is not None:
        return canonical

    normalized = normalize_workspace_path(resolved)

    for root in _storage_relative_roots():
        try:
            return str(normalized.relative_to(root))
        except ValueError:
            continue

    return str(normalized)


def _canonical_storage_plan_path(resolved: Path) -> str | None:
    location = resolve_beads_location(require_existing=True)
    if location is None:
        return None

    try:
        from sase.core.paths import sase_subdir
        from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots
    except (AttributeError, ImportError):
        return None

    roots: list[Path] = []
    if location.store is not None:
        try:
            roots.append(location.store.kind_root("plans"))
        except ValueError:
            pass
    elif location.beads_dirname == BEADS_DIRNAME:
        roots.append(location.root / "sdd" / "plans")
    else:
        roots.append(location.root / "plans")
    roots.append(sase_subdir("plans"))

    try:
        return canonicalize_plan_reference_from_roots(
            resolved,
            roots=tuple(roots),
        )
    except (AttributeError, ImportError, RuntimeError, ValueError):
        return None


def _storage_relative_roots() -> list[Path]:
    """Trusted roots that can produce stable storage-relative plan paths."""
    from sase.bead.workspace import resolve_primary_workspace

    roots: list[Path] = []
    primary = resolve_primary_workspace()
    if primary:
        roots.append(primary.resolve())
        return roots

    root, _beads_dirname = find_beads_location()
    roots.append(root.resolve())

    cwd = Path.cwd().resolve()
    if cwd not in roots:
        roots.append(cwd)

    return roots


def status_icon(status: Status) -> str:
    from sase.bead_status_presentation import bead_status_presentation

    return bead_status_presentation(status).glyph


def created_cell(issue: Issue, *, use_color: bool) -> str:
    """Return the trailing ``⧖ <age>`` fragment for a single-line bead row.

    Every compact CLI row surface (list, search, dependency list and tree)
    appends this so the bead's own creation time reads identically across all
    of them, and stays distinct from the dependency edge's ``added <ts> by
    <who>`` provenance line. Empty when the bead carries no usable timestamp,
    so the row simply ends where it used to instead of trailing whitespace.
    """
    from sase.bead_time_presentation import bead_created_cli

    cell = bead_created_cli(issue.created_at, use_color=use_color)
    return f"  {cell}" if cell else ""


# --- Subcommand handlers ---
