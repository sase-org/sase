"""Compute DELTAS for a ChangeSpec from VCS state.

The single entry point is :func:`compute_deltas`, which resolves the
parent and head refs, asks the VCS provider for a name-status diff, and
maps the raw status letters to the canonical ``A`` / ``M`` / ``D`` set
used by :class:`DeltaEntry`.

Renames (``R``) are split into a ``D`` of the source plus an ``A`` of
the target.  Anything outside ``{A, M, D, R}`` (``C``, ``T``, ``U``,
etc.) is folded to ``M`` and a warning is logged so the operator can
investigate.

This module owns the status-letter mapping so that every VCS provider
implementation of ``diff_name_status`` produces the same downstream
representation.
"""

import logging

from sase.ace.changespec import find_all_changespecs
from sase.ace.changespec.models import ChangeSpec, DeltaEntry
from sase.vcs_provider import VCSOperationError, VCSProvider

logger = logging.getLogger(__name__)


class DeltaComputationError(Exception):
    """Raised when DELTAS cannot be computed for a ChangeSpec.

    Distinct from :class:`VCSOperationError` so callers can decide
    whether a VCS hiccup or a missing-parent setup error is recoverable.
    """

    def __init__(self, changespec_name: str, message: str) -> None:
        self.changespec_name = changespec_name
        self.message = message
        super().__init__(f"compute_deltas[{changespec_name}]: {message}")


def resolve_parent_ref(
    changespec: ChangeSpec,
    vcs_provider: VCSProvider,
    cwd: str,
) -> str:
    """Resolve the parent ref for diff base.

    Uses the parent ChangeSpec's resolved branch when ``PARENT:`` is set;
    otherwise falls back to the project's mainline ref via
    :meth:`VCSProvider.get_default_parent_revision`.
    """
    if changespec.parent:
        for cs in find_all_changespecs():
            if cs.name == changespec.parent:
                return vcs_provider.resolve_revision(cs.name, cs.project_basename, cwd)
        logger.warning(
            "compute_deltas: parent %r of %r not found; "
            "falling back to default parent revision",
            changespec.parent,
            changespec.name,
        )
    return vcs_provider.get_default_parent_revision(cwd)


def resolve_head_ref(
    changespec: ChangeSpec,
    vcs_provider: VCSProvider,
    cwd: str,
) -> str:
    """Resolve the head ref for the ChangeSpec's diff target."""
    return vcs_provider.resolve_revision(
        changespec.name, changespec.project_basename, cwd
    )


_KNOWN_TYPES = {"A", "M", "D"}


def apply_status_mapping(
    raw_entries: list[tuple[str, str]],
) -> list[DeltaEntry]:
    """Map raw ``(letter, path)`` pairs from VCS to canonical DeltaEntries.

    - ``A`` / ``M`` / ``D`` pass through unchanged.
    - ``R<score>`` (rename) splits into ``D`` of the source path plus
      ``A`` of the target path; the path field is encoded as
      ``"<old>\\t<new>"`` by the provider helper.
    - ``C<score>`` (copy) emits ``A`` of the target only — the source
      file still exists in the parent and is unchanged from the diff's
      perspective, so it should not appear as deleted.
    - Anything else (``T``, ``U``, future letters) coerces to ``M`` with
      a warning so we never silently drop a real change.

    Result is sorted alphabetically by path.
    """
    out: list[DeltaEntry] = []
    for status, path in raw_entries:
        first = status[:1]
        if first == "R":
            old, _, new = path.partition("\t")
            if not new:
                logger.warning(
                    "compute_deltas: rename status %r missing target path; "
                    "treating as modified: %r",
                    status,
                    path,
                )
                out.append(DeltaEntry(path=path, change_type="M"))
                continue
            out.append(DeltaEntry(path=old, change_type="D"))
            out.append(DeltaEntry(path=new, change_type="A"))
        elif first == "C":
            _, _, new = path.partition("\t")
            out.append(DeltaEntry(path=new or path, change_type="A"))
        elif first in _KNOWN_TYPES:
            out.append(DeltaEntry(path=path, change_type=first))
        else:
            logger.warning(
                "compute_deltas: unmapped status letter %r for %r; coercing to M",
                status,
                path,
            )
            out.append(DeltaEntry(path=path, change_type="M"))

    return sorted(out, key=lambda e: e.path)


def compute_deltas(
    changespec: ChangeSpec,
    vcs_provider: VCSProvider,
    cwd: str,
) -> list[DeltaEntry]:
    """Compute the DELTAS list for a ChangeSpec from VCS state.

    Args:
        changespec: The ChangeSpec to compute deltas for.
        vcs_provider: The VCS provider for the repo containing the
            ChangeSpec's branch.
        cwd: A directory inside the repo (used by the VCS provider).

    Returns:
        Alphabetically sorted list of :class:`DeltaEntry`.  Empty when
        the parent and head refs point at the same tree.

    Raises:
        DeltaComputationError: If the underlying VCS query fails or a
            ref cannot be resolved.  Callers (sync hooks, refresh CLI)
            should catch this and leave the existing DELTAS untouched
            rather than half-write a stale or empty section.
    """
    try:
        parent_ref = resolve_parent_ref(changespec, vcs_provider, cwd)
        head_ref = resolve_head_ref(changespec, vcs_provider, cwd)
        raw_entries = vcs_provider.diff_name_status(parent_ref, head_ref, cwd)
    except VCSOperationError as exc:
        raise DeltaComputationError(changespec.name, str(exc)) from exc
    except NotImplementedError as exc:
        raise DeltaComputationError(changespec.name, str(exc)) from exc

    return apply_status_mapping(raw_entries)
