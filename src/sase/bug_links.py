"""Pure cross-linking between external bugs, epic beads, and ChangeSpecs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sase.ace.patch.models import ChangeSpec
from sase.bead.model import BeadTier, Issue, IssueType


@dataclass(frozen=True)
class BugLinks:
    """Local work records associated with one normalized external bug id."""

    bug_id: str
    epics: tuple[Issue, ...]
    changespecs: tuple[ChangeSpec, ...]

    @property
    def epic_beads(self) -> tuple[Issue, ...]:
        """Explicit alias used by consumers that label bead rows directly."""
        return self.epics

    @property
    def prs(self) -> tuple[ChangeSpec, ...]:
        """Presentation alias for ChangeSpecs shown in the Bugs pane."""
        return self.changespecs

    @property
    def patches(self) -> tuple[ChangeSpec, ...]:
        """Canonical presentation alias for linked patches."""
        return self.changespecs


def _normalize_bug_id(value: str | int | None) -> str:
    """Normalize common BUG-tag spellings to a comparable tracker id.

    Numeric ids, ``#42``, ``owner/repo#42``, GitHub issue URLs, and the
    historical ``http://b/42`` form all normalize to ``"42"``.  Other
    tracker ids are compared case-insensitively while retaining their internal
    punctuation.
    """
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if raw.casefold().startswith("bug:"):
        raw = raw[4:].strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if parsed.scheme and (parsed.netloc or parsed.path):
        path = parsed.path.rstrip("/")
        if path:
            raw = path.rsplit("/", 1)[-1]
        elif parsed.fragment:
            raw = parsed.fragment
    else:
        raw = raw.rstrip("/")
        if "#" in raw:
            raw = raw.rsplit("#", 1)[-1]
        elif raw.startswith("#"):
            raw = raw[1:]

    return raw.strip().removeprefix("#").casefold()


def find_bug_links(
    bug_id: str | int,
    beads: Iterable[Issue],
    changespecs: Iterable[ChangeSpec],
) -> BugLinks:
    """Return epic beads and ChangeSpecs whose existing bug fields match.

    Inputs are intentionally supplied by the caller: project/store resolution
    and I/O remain outside this pure helper, making it safe to run on cached TUI
    snapshots and straightforward to unit test.
    """
    normalized = _normalize_bug_id(bug_id)
    if not normalized:
        return BugLinks(bug_id="", epics=(), changespecs=())

    epics = tuple(
        bead
        for bead in beads
        if bead.issue_type == IssueType.PLAN
        and bead.tier == BeadTier.EPIC
        and _normalize_bug_id(bead.changespec_bug_id) == normalized
    )
    linked_changespecs = tuple(
        changespec
        for changespec in changespecs
        if _normalize_bug_id(changespec.bug) == normalized
    )
    return BugLinks(
        bug_id=normalized,
        epics=epics,
        changespecs=linked_changespecs,
    )


BugLinkResult = BugLinks

__all__ = [
    "BugLinkResult",
    "BugLinks",
    "find_bug_links",
]
