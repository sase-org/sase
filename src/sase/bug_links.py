"""Pure cross-linking between external bugs, epic beads, and Patches."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from urllib.parse import SplitResult, urlsplit

from sase.ace.patch.models import Patch
from sase.bead.model import Issue

_PROJECT_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class _ExternalRefLinks:
    """Local work records associated with one project-qualified external issue."""

    external_ref: str
    beads: tuple[Issue, ...]
    patches: tuple[Patch, ...]

    @property
    def prs(self) -> tuple[Patch, ...]:
        """Presentation alias for Patches shown alongside external bugs."""
        return self.patches

    @property
    def changespecs(self) -> tuple[Patch, ...]:
        """Legacy alias for callers not yet renamed to ``patches``."""
        return self.patches


def normalize_external_ref(value: str | int | None, *, project: str) -> str:
    """Return canonical ``bug:<project-key>#<issue-id>`` identity.

    Blank, projectless, or malformed inputs return ``""``.  Explicit project
    namespaces in ``bug:<project>#<issue>`` or ``<project>#<issue>`` override
    the supplied project; bare numbers and ``#number`` use the supplied project.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""
    if raw.casefold().startswith("bug:"):
        raw = raw[4:].strip()
    if not raw:
        return ""

    explicit_project, issue_id = _split_external_ref(raw)
    project_ref = explicit_project or project
    stable_project = _normalize_external_project(project_ref)
    stable_issue_id = _normalize_external_issue_id(issue_id)
    if not stable_project or not stable_issue_id:
        return ""
    return f"bug:{stable_project}#{stable_issue_id}"


def _split_external_ref(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if parsed.scheme and (parsed.netloc or parsed.path):
        return _split_external_url(parsed)

    if "#" in value:
        project_ref, issue_id = value.rsplit("#", 1)
        return project_ref.strip(), issue_id.strip()
    return "", value.strip().removeprefix("#")


def _split_external_url(parsed: SplitResult) -> tuple[str, str]:
    path_parts = [part for part in parsed.path.split("/") if part]
    netloc = parsed.netloc.casefold()
    if netloc == "github.com" and len(path_parts) >= 4:
        owner, repo, kind, issue_id = path_parts[:4]
        if kind in {"issues", "pull"}:
            return f"gh_{owner}__{repo}", issue_id

    if not path_parts:
        return "", parsed.fragment.strip()
    return "", path_parts[-1].strip()


def _normalize_external_project(project: str | int | None) -> str:
    raw = "" if project is None else str(project).strip()
    if not raw:
        return ""
    if _GITHUB_REPO_RE.fullmatch(raw):
        owner, repo = raw.split("/", 1)
        raw = f"gh_{owner}__{repo}"
    elif "/" in raw:
        return ""

    if not _PROJECT_REF_RE.fullmatch(raw):
        return ""

    from sase.project_aliases import resolve_project_alias_ref

    resolved = resolve_project_alias_ref(raw)
    if _GITHUB_REPO_RE.fullmatch(resolved):
        owner, repo = resolved.split("/", 1)
        resolved = f"gh_{owner}__{repo}"
    if not _PROJECT_REF_RE.fullmatch(resolved):
        return ""
    return resolved


def _normalize_external_issue_id(issue_id: str | int | None) -> str:
    raw = "" if issue_id is None else str(issue_id).strip().removeprefix("#")
    if not raw or not _ISSUE_ID_RE.fullmatch(raw):
        return ""
    return raw.casefold()


def find_external_ref_links(
    external_ref: str | int,
    beads: Iterable[Issue],
    patches: Iterable[Patch],
    *,
    project: str,
) -> _ExternalRefLinks:
    """Return beads and Patches matching one project-qualified external ref."""
    normalized = normalize_external_ref(external_ref, project=project)
    if not normalized:
        return _ExternalRefLinks(external_ref="", beads=(), patches=())

    linked_beads = tuple(
        bead
        for bead in beads
        if _bead_matches_external_ref(bead, normalized, project=project)
    )
    linked_patches = tuple(
        patch
        for patch in patches
        if normalize_external_ref(
            patch.bug,
            project=_patch_project_name(patch) or project,
        )
        == normalized
    )
    return _ExternalRefLinks(
        external_ref=normalized,
        beads=linked_beads,
        patches=linked_patches,
    )


def _bead_matches_external_ref(
    bead: Issue,
    target: str,
    *,
    project: str,
) -> bool:
    if normalize_external_ref(bead.external_ref, project=project) == target:
        return True
    return any(
        ref.strip().casefold().startswith("bug:")
        and normalize_external_ref(ref, project=project) == target
        for ref in bead.refs
    )


def _patch_project_name(patch: Patch) -> str:
    project_name = getattr(patch, "project_name", "")
    return project_name if isinstance(project_name, str) else ""


ExternalRefLinkResult = _ExternalRefLinks

__all__ = [
    "ExternalRefLinkResult",
    "find_external_ref_links",
    "normalize_external_ref",
]
