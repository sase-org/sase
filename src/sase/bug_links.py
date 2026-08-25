"""Pure cross-linking between external bugs, epic beads, and Patches."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit

_PROJECT_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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


__all__ = ["normalize_external_ref"]
