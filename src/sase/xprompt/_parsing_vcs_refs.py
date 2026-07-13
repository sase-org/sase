"""VCS reference parsing helpers for xprompt prompt text."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_GENERIC_PROJECT_VCS_REF_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\"']))"
    r"#(?P<workflow>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(?:!!|\?\?)?"
    r"(?:[_:](?P<colon>[a-zA-Z0-9_.~/-]+)|\((?P<paren>[a-zA-Z0-9_.~/-]+)\))"
    r"(?=\s|$)"
)
_KNOWN_FALLBACK_VCS_PREFIXES = frozenset({"gh", "git", "jj", "p4"})
_VCS_UNDERSCORE_NORMALIZER: re.Pattern[str] | None = None
_LAUNCH_XPROMPT_AT_REF_RE: re.Pattern[str] | None = None


def _workspace_workflow_names() -> set[str]:
    """Return registered workspace workflows plus supported core fallbacks."""
    from sase.workspace_provider import get_workflow_names

    return set(get_workflow_names()) | set(_KNOWN_FALLBACK_VCS_PREFIXES)


def normalize_vcs_underscore_refs(prompt: str) -> str:
    """Normalize ``#gh_sase`` to ``#gh:sase`` for known VCS workflow names.

    The xprompt and embedded-workflow regex patterns treat ``_`` as part of the
    identifier, so ``#gh_sase`` is parsed as a single name ``gh_sase`` which
    doesn't match any workflow. Converting the first ``_`` after a known VCS
    prefix to ``:`` lets downstream patterns correctly split the VCS prefix
    from the ref name.
    """
    global _VCS_UNDERSCORE_NORMALIZER  # noqa: PLW0603
    if _VCS_UNDERSCORE_NORMALIZER is None:
        from sase.workspace_provider import get_workflow_names

        names = get_workflow_names()
        if not names:
            return prompt
        alts = "|".join(re.escape(n) for n in sorted(names))
        _VCS_UNDERSCORE_NORMALIZER = re.compile(
            rf"((?:^|(?<=\s)|(?<=[(\"']))#(?:{alts}))_",
            re.MULTILINE,
        )
    return _VCS_UNDERSCORE_NORMALIZER.sub(r"\1:", prompt)


def _markdown_code_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text.startswith("```", i):
            start = i
            close = text.find("```", i + 3)
            if close == -1:
                ranges.append((start, len(text)))
                break
            ranges.append((start, close + 3))
            i = close + 3
            continue
        if text[i] == "`":
            start = i
            close = text.find("`", i + 1)
            if close == -1:
                i += 1
                continue
            ranges.append((start, close + 1))
            i = close + 1
            continue
        i += 1
    return ranges


def _inside_any_range(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)


def _get_launch_xprompt_at_ref_pattern() -> re.Pattern[str]:
    """Return the scoped ``#workflow@ref`` launch-shorthand normalizer."""
    global _LAUNCH_XPROMPT_AT_REF_RE  # noqa: PLW0603
    if _LAUNCH_XPROMPT_AT_REF_RE is None:
        workflows = _workspace_workflow_names()
        alts = "|".join(re.escape(name) for name in sorted(workflows))
        _LAUNCH_XPROMPT_AT_REF_RE = re.compile(
            rf"(?P<context>^|(?<=[\s([{{\"']))"
            rf"#(?P<workflow>{alts})"
            r"(?P<marker>!!|\?\?)?"
            r"@(?P<ref>[A-Za-z0-9][A-Za-z0-9_.~/-]*)"
            r"(?=$|[\s)\]},.!?;:\"'])",
            re.IGNORECASE,
        )
    return _LAUNCH_XPROMPT_AT_REF_RE


def normalize_launch_xprompt_at_refs(prompt: str) -> str:
    """Normalize mobile/Telegram ``#workflow@ref`` launch shorthand.

    The rewrite is intentionally scoped to workspace/VCS workflow names and
    skips Markdown code spans so ordinary prose and code samples are preserved.
    """
    if "@" not in prompt or "#" not in prompt:
        return prompt

    code_ranges = _markdown_code_ranges(prompt)

    def replace(match: re.Match[str]) -> str:
        if _inside_any_range(match.start(), code_ranges):
            return match.group(0)
        marker = match.group("marker") or ""
        return f"{match.group('context')}#{match.group('workflow')}{marker}:{match.group('ref')}"

    return _get_launch_xprompt_at_ref_pattern().sub(replace, prompt)


def _known_project_workspace_path(value: object) -> Path | None:
    """Return the workspace path carried by a known-project mapping value."""
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)

    workspace_dir = getattr(value, "workspace_dir", None)
    if isinstance(workspace_dir, Path):
        return workspace_dir
    if isinstance(workspace_dir, str) and workspace_dir:
        return Path(workspace_dir)
    return None


def _workspace_path_key(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _github_owner_repo_workspace(ref: str) -> Path | None:
    parts = ref.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return Path.home() / "projects" / "github" / parts[0] / parts[1]


def _project_for_owner_repo_workspace(
    ref: str,
    known_projects: Mapping[str, object],
) -> str | None:
    expected = _github_owner_repo_workspace(ref)
    if expected is None:
        return None

    expected_key = _workspace_path_key(expected)
    matches = [
        project
        for project, value in known_projects.items()
        if (
            (workspace_path := _known_project_workspace_path(value)) is not None
            and _workspace_path_key(workspace_path) == expected_key
        )
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _unambiguous_basename_project(
    ref: str,
    known_projects: Mapping[str, object],
) -> str | None:
    basename = ref.rsplit("/", 1)[-1]
    candidates: set[str] = set()
    if basename in known_projects:
        candidates.add(basename)

    for project, value in known_projects.items():
        workspace_path = _known_project_workspace_path(value)
        if workspace_path is not None and workspace_path.name == basename:
            candidates.add(project)

    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def resolve_known_project_ref(
    ref: str, known_projects: Mapping[str, object]
) -> str | None:
    """Return the registered project name for *ref* or ``None``.

    Exact project names are accepted first. GitHub-style ``owner/repo`` refs
    then match a known project whose workspace is
    ``~/projects/github/<owner>/<repo>``. A legacy basename fallback is kept
    only when it identifies a single plausible project.
    """
    if ref in known_projects:
        return ref
    if "/" in ref:
        workspace_project = _project_for_owner_repo_workspace(ref, known_projects)
        if workspace_project is not None:
            return workspace_project
        return _unambiguous_basename_project(ref, known_projects)
    return None


def extract_known_project_vcs_ref(
    prompt: str,
    include_states: Sequence[str] | str = ("enabled",),
) -> tuple[str, str] | None:
    """Return ``(workflow_type, ref)`` for a generic known-project VCS ref.

    This recognizes project refs such as ``#gh:sase`` or ``#gh:sase-org/sase``
    even when the ``gh`` workspace provider is not registered in the current
    process. The project must be known via ``~/.sase/projects/*/*.sase`` (or
    legacy ``.gp``) to avoid treating ordinary xprompt references as workspace
    selectors. The returned ``ref`` preserves the form that appears in
    *prompt*; callers needing the registered project name should pass it
    through :func:`resolve_known_project_ref`.
    """
    if "#" not in prompt:
        return None

    from sase.xprompt.loader import get_known_project_workspaces

    try:
        known_projects = get_known_project_workspaces(include_states=include_states)
    except TypeError as exc:
        if "include_states" not in str(exc):
            raise
        known_projects = get_known_project_workspaces()
    if not known_projects:
        return None

    refs = iter_known_project_vcs_refs(prompt, known_projects)
    if refs:
        return refs[0]
    return None


def iter_known_project_vcs_refs(
    prompt: str,
    known_projects: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Return all generic VCS refs that resolve to known projects.

    The returned refs preserve the user-written ref value, so owner/repo forms
    like ``sase-org/sase`` remain available to callers that need history or
    display context while still checking the registered project basename.
    """
    if not known_projects or "#" not in prompt:
        return []

    workflow_names = _workspace_workflow_names()
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    normalized = normalize_vcs_underscore_refs(prompt)
    for match in _GENERIC_PROJECT_VCS_REF_PATTERN.finditer(normalized):
        workflow_type = match.group("workflow")
        if workflow_type not in workflow_names:
            continue
        ref = match.group("colon") or match.group("paren")
        if resolve_known_project_ref(ref, known_projects) is None:
            continue
        key = (workflow_type, ref)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs


def strip_known_project_vcs_refs(prompt: str) -> str:
    """Remove generic VCS refs that point at known projects."""
    from sase.xprompt.loader import get_known_project_workspaces

    known_projects = get_known_project_workspaces()
    if not known_projects or "#" not in prompt:
        return prompt.strip()

    workflow_names = _workspace_workflow_names()

    def _replace(match: re.Match[str]) -> str:
        workflow_type = match.group("workflow")
        if workflow_type not in workflow_names:
            return match.group(0)
        ref = match.group("colon") or match.group("paren")
        if resolve_known_project_ref(ref, known_projects) is not None:
            return ""
        return match.group(0)

    return _GENERIC_PROJECT_VCS_REF_PATTERN.sub(_replace, prompt).strip()


__all__ = [
    "extract_known_project_vcs_ref",
    "iter_known_project_vcs_refs",
    "normalize_launch_xprompt_at_refs",
    "normalize_vcs_underscore_refs",
    "resolve_known_project_ref",
    "strip_known_project_vcs_refs",
]
