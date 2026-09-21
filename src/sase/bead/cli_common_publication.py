"""Publication verification for committed bead-store mutations."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.bead.operation_context import BeadOperationContext

_logger = logging.getLogger(__name__)


class BeadPublicationError(RuntimeError):
    """Raised when a committed bead mutation could not be published.

    The mutation exists in the local store only, so its command must fail
    loudly rather than report a success nobody else can observe. ``diagnostic``
    carries the full operator-facing report that was written to stderr, for
    callers that record the failure somewhere other than a terminal.
    """

    def __init__(self, message: str, *, diagnostic: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic or message


def routed_bead_context_requires_publication(
    bead_context: BeadOperationContext | None,
) -> bool:
    """Return whether a routed mutation must prove commit/publication success."""
    if bead_context is None or bead_context.project_key is None:
        return False
    location = bead_context.location
    return not location.is_in_tree and not location.read_only


def emit_routed_bead_publication_failure(
    description: str | None,
    *,
    bead_context: BeadOperationContext | None = None,
    cause: BaseException | None = None,
) -> BeadPublicationError:
    """Print and return the publication error for a failed routed commit."""
    beads_dir = None if bead_context is None else bead_context.beads_dir
    project = None if bead_context is None else bead_context.project_label
    operation = description or "bead mutation"
    location = "the routed bead store" if beads_dir is None else str(beads_dir)
    owner = "" if project is None else f" for project {project!r}"
    lines = [
        (
            f"routed bead mutation {operation!r}{owner} changed {location}, "
            "but the change could not be committed for publication"
        ),
        "Resolve the SDD bead-store commit/publish problem and rerun the command.",
    ]
    if cause is None:
        lines.append("The auto-commit hook reported that no commit was created.")
    else:
        lines.append(f"Commit failure: {cause}")
    diagnostic = "\n".join(lines)
    print(diagnostic, file=sys.stderr)
    return BeadPublicationError(lines[0], diagnostic=diagnostic)


def ensure_bead_mutation_published(
    beads_dir: Path,
    *,
    description: str | None = None,
) -> Any | None:
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
            return None
        outcome = push_bead_work_launch(
            beads_dir,
            worker_lock_wait=MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        )
        status = verify_bead_store_published(beads_dir)
        if status.published:
            return outcome
        lines = bead_publication_failure_lines(status, description=description)
    except Exception:
        # Verification must never turn an otherwise healthy mutation into a
        # failure because the check itself broke.
        _logger.warning(
            "Failed to verify publication of committed bead state",
            exc_info=True,
        )
        return None

    for line in lines:
        print(line, file=sys.stderr)
    raise BeadPublicationError(lines[0], diagnostic="\n".join(lines))
