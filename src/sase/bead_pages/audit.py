"""Attribution audit for commit links on published bead pages.

A rendered Commits table qualifies a commit label with its owning repository
(``sase-core@1290667``) only when that commit landed outside the project's
primary repository. A bare short SHA therefore *claims* the primary
repository, so a bare label whose link resolves against some other remote is
the visible fingerprint of an association projection that walked the wrong
repository. That symptom stayed invisible across 21 lineages, so it is worth
detecting from the published bytes alone: this module needs no store, no bead
projection, and no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import re

from sase._git_remote import git_remotes_match

_COMMIT_LINK_RE = re.compile(
    r"\[`(?P<label>[^`\n]+)`\]\("
    r"(?P<repo_url>[^)\s]+?)/commit/(?P<sha>[0-9a-fA-F]{7,64})\)"
)
_BARE_SHA_RE = re.compile(r"[0-9a-fA-F]{7,64}")


@dataclass(frozen=True, slots=True)
class _MisattributedCommitLink:
    """One published commit link that resolves against the wrong repository."""

    page: Path
    label: str
    url: str


def audit_commit_link_attribution(
    pages_root: Path,
    *,
    primary_remote_url: str | None,
) -> tuple[_MisattributedCommitLink, ...]:
    """Return every unqualified commit link that is not the primary repository.

    Returns nothing when the primary remote is unknown; an unresolvable remote
    proves no page wrong.
    """

    if not primary_remote_url or not pages_root.is_dir():
        return ()
    findings: list[_MisattributedCommitLink] = []
    for page in sorted(pages_root.rglob("*.md")):
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(
            _MisattributedCommitLink(page, label, url)
            for label, repo_url, url in _commit_links(text)
            if _BARE_SHA_RE.fullmatch(label) is not None
            and not _same_repository(repo_url, primary_remote_url)
        )
    return tuple(findings)


def _commit_links(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield ``(label, repository url, full commit url)`` for one page."""

    for match in _COMMIT_LINK_RE.finditer(text):
        yield (
            match.group("label"),
            match.group("repo_url"),
            match.group(0)[match.group(0).index("](") + 2 : -1],
        )


def _same_repository(repo_url: str, primary_remote_url: str) -> bool:
    try:
        return git_remotes_match(repo_url, primary_remote_url)
    except Exception:  # noqa: BLE001 - an unparsable remote proves nothing.
        return True


__all__ = [
    "audit_commit_link_attribution",
]
