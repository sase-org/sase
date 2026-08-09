"""Headless foundations for VCS ref-root completion inside workflow refs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.config import load_merged_config
from sase.core.paths import sase_projects_dir
from sase.workspace_provider import (
    VcsNamespaceEntry,
    list_ref_namespaces,
)
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
    vcs_project_catalog_signature,
)

VcsRefSeparator = Literal[":", "("]
VcsRefCandidate = VcsProjectEntry | VcsNamespaceEntry

VCS_REF_GOLDEN_CURSOR = "<CURSOR>"

# Tuple shape: marked prompt, known workflow names, selected ref, chain, expected
# prompt. Phase 4 mirrors this table in Rust for the parity contract.
VCS_REF_GOLDEN_VECTORS: tuple[
    tuple[str, tuple[str, ...], str, bool, str],
    ...,
] = (
    (
        f"#gh:{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase",
        False,
        "#gh:sase ",
    ),
    (
        f"#gh:sa{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase",
        False,
        "#gh:sase ",
    ),
    (
        f"Fix #gh:sa{VCS_REF_GOLDEN_CURSOR} now",
        ("gh",),
        "sase",
        False,
        "Fix #gh:sase now",
    ),
    (
        f"#gh!!:sa{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase",
        False,
        "#gh!!:sase ",
    ),
    (
        f"#gh:s{VCS_REF_GOLDEN_CURSOR}asex",
        ("gh",),
        "sase",
        False,
        "#gh:sase ",
    ),
    (
        f"#git:sa{VCS_REF_GOLDEN_CURSOR}suffix",
        ("git",),
        "sase",
        False,
        "#git:sase ",
    ),
    (
        f"#gh(s{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase",
        False,
        "#gh(sase)",
    ),
    (
        f"#gh(s{VCS_REF_GOLDEN_CURSOR}) next",
        ("gh",),
        "sase",
        False,
        "#gh(sase) next",
    ),
    (
        f"#gh??(s{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase",
        False,
        "#gh??(sase)",
    ),
    (
        f"#gh:{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase-org",
        True,
        "#gh:sase-org/",
    ),
    (
        f"#gh:{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase-org/",
        True,
        "#gh:sase-org/",
    ),
    (
        f"Fix #gh:sa{VCS_REF_GOLDEN_CURSOR} now",
        ("gh",),
        "sase-org",
        True,
        "Fix #gh:sase-org/ now",
    ),
    (
        f"#gh(sa{VCS_REF_GOLDEN_CURSOR}",
        ("gh",),
        "sase-org",
        True,
        "#gh(sase-org/",
    ),
    (
        f"#gh(sa{VCS_REF_GOLDEN_CURSOR}) next",
        ("gh",),
        "sase-org",
        True,
        "#gh(sase-org/) next",
    ),
)


@dataclass(frozen=True)
class _VcsRefCompletionConfig:
    """Configuration for VCS ref-root completion."""

    enabled: bool = True


@dataclass(frozen=True)
class VcsRefTrigger:
    """A detected VCS ref-root completion context."""

    start: int
    end: int
    workflow: str
    separator: VcsRefSeparator
    ref_start: int
    ref_end: int
    query: str
    query_span: tuple[int, int]

    @property
    def span(self) -> tuple[int, int]:
        """Return the full workflow token span."""
        return (self.start, self.end)

    @property
    def value_span(self) -> tuple[int, int]:
        """Return the ref-value span, excluding ``#tag:`` or ``#tag(...``."""
        return (self.ref_start, self.ref_end)


_NAMESPACE_CACHE: dict[tuple[str, object], tuple[VcsNamespaceEntry, ...]] = {}


def load_vcs_ref_completion_config(
    config: dict[str, Any] | None = None,
) -> _VcsRefCompletionConfig:
    """Return normalized VCS ref-root completion settings."""
    data = load_merged_config() if config is None else config
    section = data.get("vcs_ref_completion", {}) if isinstance(data, dict) else {}
    if not isinstance(section, dict):
        section = {}

    enabled = section.get("enabled", True)
    return _VcsRefCompletionConfig(
        enabled=enabled if isinstance(enabled, bool) else True
    )


def find_vcs_ref_trigger(
    prompt: str,
    cursor: int,
    workflow_names: set[str] | list[str] | tuple[str, ...],
) -> VcsRefTrigger | None:
    """Detect a ref-root completion trigger inside a VCS workflow ref."""
    if cursor < 0 or cursor > len(prompt):
        return None

    known_names = tuple(
        sorted((name for name in workflow_names if name), key=len, reverse=True)
    )
    if not known_names:
        return None

    start = cursor
    while start > 0 and not prompt[start - 1].isspace():
        start -= 1

    if start >= len(prompt) or prompt[start] != "#":
        return None

    matched = _match_workflow_and_separator(prompt, start + 1, known_names)
    if matched is None:
        return None
    workflow, sep_pos = matched

    separator = prompt[sep_pos]
    ref_start = sep_pos + 1
    if cursor < ref_start:
        return None
    if ")" in prompt[ref_start:cursor]:
        return None

    ref_end, token_end = _find_ref_end(prompt, cursor, separator)
    if cursor > ref_end:
        return None

    full_ref = prompt[ref_start:ref_end]
    if separator == ":" and ")" in full_ref:
        return None
    if "://" in full_ref or "/" in full_ref:
        return None
    if full_ref and full_ref[0] in {"~", "."}:
        return None

    query = prompt[ref_start:cursor]
    return VcsRefTrigger(
        start=start,
        end=token_end,
        workflow=workflow,
        separator=separator,  # type: ignore[arg-type]
        ref_start=ref_start,
        ref_end=ref_end,
        query=query,
        query_span=(ref_start, cursor),
    )


def _match_workflow_and_separator(
    prompt: str,
    start: int,
    workflow_names: tuple[str, ...],
) -> tuple[str, int] | None:
    for name in workflow_names:
        if not prompt.startswith(name, start):
            continue
        pos = start + len(name)
        if prompt.startswith("!!", pos) or prompt.startswith("??", pos):
            pos += 2
        if pos < len(prompt) and prompt[pos] in {":", "("}:
            return (name, pos)
    return None


def _find_ref_end(
    prompt: str,
    cursor: int,
    separator: str,
) -> tuple[int, int]:
    end = cursor
    if separator == "(":
        while end < len(prompt) and not prompt[end].isspace() and prompt[end] != ")":
            end += 1
        token_end = end + 1 if end < len(prompt) and prompt[end] == ")" else end
        return end, token_end

    while end < len(prompt) and not prompt[end].isspace():
        end += 1
    return end, end


def apply_vcs_ref_selection(
    prompt: str,
    trigger: VcsRefTrigger,
    selected_ref: str,
    *,
    chain: bool = False,
) -> str:
    """Return *prompt* with *trigger*'s ref value replaced by *selected_ref*."""
    start, end = trigger.value_span
    before = prompt[:start]
    after = prompt[end:]

    if chain:
        selected_ref = f"{selected_ref.rstrip('/')}/"
        return f"{before}{selected_ref}{after}"

    if trigger.separator == "(":
        suffix = "" if after.startswith(")") else ")"
        return f"{before}{selected_ref}{suffix}{after}"

    suffix = "" if after.startswith(tuple(" \t\r\n")) else " "
    return f"{before}{selected_ref}{suffix}{after}"


def build_vcs_ref_candidates(
    workflow: str,
    projects_dir: Path | str | None = None,
    *,
    use_cache: bool = True,
    config: _VcsRefCompletionConfig | None = None,
) -> list[VcsRefCandidate]:
    """Return ordered project, Patch, and namespace candidates."""
    settings = config or load_vcs_ref_completion_config()
    if not settings.enabled:
        return []

    entries = [
        entry
        for entry in build_vcs_project_completion_entries(
            projects_dir,
            use_cache=use_cache,
        )
        if entry.vcs_prefix == workflow
    ]
    namespaces = _list_cached_namespaces(
        workflow,
        projects_dir,
        use_cache=use_cache,
    )
    return [*entries, *namespaces]


def vcs_ref_namespaces_by_workflow(
    workflow_names: set[str] | list[str] | tuple[str, ...],
    projects_dir: Path | str | None = None,
    *,
    use_cache: bool = True,
    config: _VcsRefCompletionConfig | None = None,
) -> dict[str, tuple[VcsNamespaceEntry, ...]]:
    """Return namespace candidates keyed by workflow name."""
    settings = config or load_vcs_ref_completion_config()
    if not settings.enabled:
        return {}

    return {
        workflow: tuple(
            _list_cached_namespaces(
                workflow,
                projects_dir,
                use_cache=use_cache,
            )
        )
        for workflow in sorted({name for name in workflow_names if name})
    }


def _list_cached_namespaces(
    workflow: str,
    projects_dir: Path | str | None,
    *,
    use_cache: bool,
) -> tuple[VcsNamespaceEntry, ...]:
    projects_root = (
        Path(projects_dir) if projects_dir is not None else sase_projects_dir()
    )
    signature = vcs_project_catalog_signature(projects_root)
    if use_cache and signature is not None:
        key = (workflow, signature)
        cached = _NAMESPACE_CACHE.get(key)
        if cached is not None:
            return cached

    entries = tuple(list_ref_namespaces(workflow).entries)
    if use_cache and signature is not None:
        _NAMESPACE_CACHE[(workflow, signature)] = entries
    return entries


def filter_vcs_ref_candidates(
    candidates: list[VcsRefCandidate] | tuple[VcsRefCandidate, ...],
    query: str,
) -> list[VcsRefCandidate]:
    """Return candidates whose name or alias prefix-matches *query*."""
    project_entries = [
        candidate for candidate in candidates if isinstance(candidate, VcsProjectEntry)
    ]
    namespace_entries = [
        candidate
        for candidate in candidates
        if isinstance(candidate, VcsNamespaceEntry)
    ]

    filtered_projects = filter_vcs_project_entries(project_entries, query)
    needle = query.casefold()
    if needle:
        filtered_namespaces = [
            entry
            for entry in namespace_entries
            if entry.name.casefold().startswith(needle)
        ]
    else:
        filtered_namespaces = list(namespace_entries)
    return [*filtered_projects, *filtered_namespaces]


__all__ = [
    "VCS_REF_GOLDEN_CURSOR",
    "VCS_REF_GOLDEN_VECTORS",
    "VcsRefCandidate",
    "VcsRefSeparator",
    "VcsRefTrigger",
    "apply_vcs_ref_selection",
    "build_vcs_ref_candidates",
    "filter_vcs_ref_candidates",
    "find_vcs_ref_trigger",
    "load_vcs_ref_completion_config",
    "vcs_ref_namespaces_by_workflow",
]
