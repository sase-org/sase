"""Wire records for the VCS log (commit-history) facade.

Sidecar to :mod:`sase.core.git_query_wire`. Defines the **stable**
boundary between Python and the Rust implementation of the
provider-agnostic commit-history parser/aggregator that backs
``sase vcs log``.

Scope of the contract
---------------------

The VCS-log wire models *pure parsing* of a ``git log`` stream the host
already collected, and *pure interleaving* of per-repo commit lists into
one chronological timeline. Repo resolution, ``git`` execution, and all
rendering stay in Python and are NEVER described by these records.

Two records are needed:

- :class:`VcsCommitWire` — one commit from a single repository. This is
  the provider-agnostic return shape of the abstract ``vcs_log`` provider
  hook, so field names avoid git-specific vocabulary (``full_id`` /
  ``short_id`` rather than "sha").
- :class:`AggregatedCommitWire` — a :class:`VcsCommitWire` tagged with the
  label of the repo it came from. Rust serializes this as a *flat* JSON
  object (``repo`` beside the commit fields); :func:`aggregated_commit_from_dict`
  rehydrates that flat shape into the nested Python form the renderer
  consumes (``entry.repo`` + ``entry.commit``).

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- ``timestamp`` is the epoch author time in seconds (``git log %at``) so
  ordering is timezone-independent; wall-clock formatting is the host's
  job.
- ``AggregatedCommitWire`` JSON is flat:
  ``{"repo", "full_id", "short_id", "author_name", "author_email",
  "timestamp", "parent_ids", "subject", "body", "presence"}``.

Schema version
--------------

:data:`VCS_LOG_WIRE_SCHEMA_VERSION` is bumped whenever the shape changes
incompatibly. The Rust implementation pins the same version constant in
its serde structs; mismatches surface immediately in the rehydrators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VCS_LOG_WIRE_SCHEMA_VERSION = 3

CommitPresence = Literal["synced", "remote_only", "local_only", "unknown"]

_PRESENCE_VALUES: frozenset[str] = frozenset(
    ("synced", "remote_only", "local_only", "unknown")
)


@dataclass(frozen=True)
class VcsCommitWire:
    """One commit from a single repository's history.

    Attributes:
        full_id: Full commit identifier (git: 40-char SHA).
        short_id: Abbreviated commit identifier (git: short SHA).
        author_name: Commit author display name.
        author_email: Commit author email address.
        timestamp: Epoch author time in seconds. Used for
            timezone-independent sorting; the host formats wall-clock time
            from this.
        parent_ids: Full parent commit ids (git: ``%P``). Empty for a root
            commit, one entry for an ordinary commit, two or more for a
            merge.
        subject: First line of the commit message.
        body: Remaining commit-message body (may be empty or multi-line).
        presence: Local/remote presence classification.
    """

    full_id: str
    short_id: str
    author_name: str
    author_email: str
    timestamp: int
    parent_ids: tuple[str, ...] = field(default=(), kw_only=True)
    subject: str
    body: str
    presence: CommitPresence = "unknown"

    @property
    def is_merge(self) -> bool:
        """Whether this commit has more than one parent."""
        return len(self.parent_ids) > 1


@dataclass(frozen=True)
class AggregatedCommitWire:
    """A :class:`VcsCommitWire` tagged with its source repo label.

    Attributes:
        repo: Human-facing repo label (primary project name, a linked-repo
            name, or the SDD store label).
        commit: The commit itself.
    """

    repo: str
    commit: VcsCommitWire


def vcs_commit_from_dict(data: dict[str, Any]) -> VcsCommitWire:
    """Rehydrate a :class:`VcsCommitWire` from a JSON-safe dict.

    Inverse of :func:`dataclasses.asdict`. Used by the PyO3 binding
    adapter and by tests that round-trip a commit through JSON.
    """
    return VcsCommitWire(
        full_id=str(data["full_id"]),
        short_id=str(data["short_id"]),
        author_name=str(data["author_name"]),
        author_email=str(data["author_email"]),
        timestamp=int(data["timestamp"]),
        parent_ids=_parent_ids_from_dict(data),
        subject=str(data["subject"]),
        body=str(data["body"]),
        presence=_presence_from_dict(data),
    )


def aggregated_commit_from_dict(data: dict[str, Any]) -> AggregatedCommitWire:
    """Rehydrate an :class:`AggregatedCommitWire` from a *flat* dict.

    The Rust side flattens the commit fields beside ``repo`` (no nested
    ``commit`` key), so this reads the repo label and reuses
    :func:`vcs_commit_from_dict` for the remaining fields.
    """
    return AggregatedCommitWire(
        repo=str(data["repo"]),
        commit=vcs_commit_from_dict(data),
    )


__all__ = [
    "VCS_LOG_WIRE_SCHEMA_VERSION",
    "AggregatedCommitWire",
    "CommitPresence",
    "VcsCommitWire",
    "aggregated_commit_from_dict",
    "vcs_commit_from_dict",
]


def _presence_from_dict(data: dict[str, Any]) -> CommitPresence:
    raw = str(data.get("presence", "unknown"))
    if raw in _PRESENCE_VALUES:
        return raw  # type: ignore[return-value]
    return "unknown"


def _parent_ids_from_dict(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("parent_ids")
    if raw is None:
        return ()
    return tuple(str(item) for item in raw)
