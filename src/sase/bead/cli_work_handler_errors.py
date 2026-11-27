"""Epic bead-work error types for ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

type EpicLaunchState = Literal[
    "already_running",
    "declined",
    "dry_run",
    "launched",
]


class BeadWorkError(RuntimeError):
    """A recoverable ``sase bead work`` orchestration failure.

    ``agents_spawned`` records that at least one runner crossed the spawn
    boundary, so plan-file callers must preserve the recoverable epic state.
    ``agents_launched`` remains available for compatibility with host callers.

    ``graph_published`` records that the pre-launch visibility barrier
    completed. ``preserve_epic_state`` is reserved for failures where the
    locally committed graph is the safe resume point even though no runner
    spawned, such as a rejected ``--no-push`` detached-store launch.

    ``publication_conflict`` marks a graph publication that left the local
    store holding commits that cannot merge with concurrently published
    history. The plan-launch retry loop may discard that unpublished graph
    and re-mint instead of preserving it. ``checkpoint_sha`` /
    ``attempt_tip_sha`` record this attempt's beads-repo commits for that
    loop's safety check.
    """

    def __init__(
        self,
        message: str,
        *,
        agents_spawned: bool = False,
        agents_launched: bool = False,
        graph_published: bool = False,
        preserve_epic_state: bool = False,
        retry_requires_push: bool = False,
        publication_conflict: bool = False,
    ) -> None:
        super().__init__(message)
        self.agents_spawned = agents_spawned or agents_launched
        self.agents_launched = agents_launched
        self.graph_published = graph_published
        self.preserve_epic_state = preserve_epic_state
        self.retry_requires_push = retry_requires_push
        self.publication_conflict = publication_conflict
        self.checkpoint_sha: str | None = None
        self.attempt_tip_sha: str | None = None


class EpicGraphRelocatedError(BeadWorkError):
    """The launch's own epic graph moved during publication; nothing launched."""

    def __init__(
        self,
        original_epic_id: str,
        relocated_epic_id: str,
        *,
        bead_relocations: tuple[Any, ...] = (),
    ) -> None:
        super().__init__(
            f"epic {original_epic_id} was renumbered to {relocated_epic_id} "
            f"during publication because {original_epic_id} was already "
            "published by another clone; no agents were spawned. "
            f"Resume with: sase bead work {relocated_epic_id}",
            agents_spawned=False,
            graph_published=True,
        )
        self.original_epic_id = original_epic_id
        self.relocated_epic_id = relocated_epic_id
        self.bead_relocations = tuple(bead_relocations)


class EpicGraphPublicationConflictError(BeadWorkError):
    """The launch's own epic graph cannot merge with published history.

    Raised when the managed sync backing graph publication aborts with
    unsupported conflicts: the local checkpoint commit is unpublished and
    unmergeable, and no agents were spawned. The plan-launch retry loop may
    discard the unpublished graph under a recovery ref and re-mint.

    ``semantic_cause`` is the cause-first integration error,
    ``log_path`` the managed sync log holding the full git output, and
    ``checkpoint_sha`` / ``attempt_tip_sha`` the SHAs this attempt recorded
    in the beads repo, for the replay safety check.
    """

    def __init__(
        self,
        message: str,
        *,
        semantic_cause: str | None = None,
        log_path: Path | None = None,
    ) -> None:
        super().__init__(
            message,
            agents_spawned=False,
            graph_published=False,
            preserve_epic_state=False,
            publication_conflict=True,
        )
        self.semantic_cause = semantic_cause
        self.log_path: Path | None = log_path


__all__ = [
    "BeadWorkError",
    "EpicGraphPublicationConflictError",
    "EpicGraphRelocatedError",
    "EpicLaunchState",
]
