"""Presentation helpers over cached or supplied project-display snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import re
from typing import Any

from sase._project_display_cache import (
    cached_project_display_snapshot,
    humanize_cl_name_cached,
)
from sase._project_display_snapshot import (
    ProjectDisplayProjection,
    ProjectDisplaySnapshot,
)
from sase.core.paths import make_safe_filename


_CL_NAME_TOKEN_RE = re.compile(
    r"(?P<prefix>^|(?<=[\s(\[{]))"
    r"(?P<name>[A-Za-z0-9_.~-]+)"
    r"(?P<suffix>(?=$|[\s)\]},.!?;:\"']))"
)


def _display_names(
    projects_root: Path | str | None,
    snapshot: ProjectDisplaySnapshot | None,
) -> Mapping[str, str]:
    if snapshot is not None:
        return snapshot
    return cached_project_display_snapshot(projects_root)


def project_display_name_map_signature(
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return a stable signature for a supplied or cached display snapshot."""
    if snapshot is not None:
        return snapshot.signature
    return tuple(sorted(cached_project_display_snapshot(projects_root).items()))


def attach_project_display_names(
    agents: Iterable[Any],
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> None:
    """Populate display-only labels on duck-typed agent objects.

    Supplying *snapshot* keeps this presentation operation free of lifecycle
    filesystem reads. Canonical identity continues to come from ``project_file``.
    """
    candidates: list[tuple[Any, str]] = []
    for agent in agents:
        if not hasattr(agent, "project_display_name"):
            continue
        project_file = getattr(agent, "project_file", None)
        if not project_file:
            continue
        key = Path(str(project_file)).parent.name
        candidates.append((agent, key))

    if not candidates:
        return

    display_names = _display_names(projects_root, snapshot)
    for agent, key in candidates:
        display = display_names.get(key)
        agent.project_display_name = display if display and display != key else None


def project_display_for(
    project_key: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> ProjectDisplayProjection:
    """Pair canonical *project_key* with its supplied or cached display label."""
    if snapshot is not None:
        return snapshot.projection_for(project_key)
    label = cached_project_display_snapshot(projects_root).get(project_key, project_key)
    return ProjectDisplayProjection(project_key, label)


def project_display_name_for(
    key: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> str:
    """Return the project label for canonical *key*, falling back to *key*.

    Renderers should supply a preloaded *snapshot*. Omitting it uses the
    explicitly managed convenience cache for non-rendering callers.
    """
    return project_display_for(
        key,
        projects_root,
        snapshot=snapshot,
    ).project_label


def _humanize_cl_name_with_map(
    name: str,
    display_names: Mapping[str, str],
) -> str:
    if not display_names or not name:
        return name

    if name in display_names:
        return display_names[name]
    if "_" not in name:
        return name

    for key, display in sorted(
        display_names.items(),
        key=lambda item: (-len(item[0]), item[0]),
    ):
        prefix = f"{key}_"
        if name.startswith(prefix):
            return f"{display}_{name[len(prefix) :]}"
    return name


def humanize_cl_name(
    name: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> str:
    """Project a canonical project/Patch name to a display label."""
    if snapshot is None and projects_root is None:
        return humanize_cl_name_cached(
            name,
            lambda: _humanize_cl_name_with_map(name, _display_names(None, None)),
        )
    return _humanize_cl_name_with_map(
        name,
        _display_names(projects_root, snapshot),
    )


def humanize_cl_names_in_text(
    text: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> str:
    """Project standalone canonical project/Patch tokens in display text."""
    display_names = _display_names(projects_root, snapshot)
    if not text or not display_names:
        return text

    def replace(match: re.Match[str]) -> str:
        return (
            match.group("prefix")
            + _humanize_cl_name_with_map(match.group("name"), display_names)
            + match.group("suffix")
        )

    return _CL_NAME_TOKEN_RE.sub(replace, text)


def humanize_vcs_refs_in_text(
    text: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
    project_tags: bool = True,
) -> str:
    """Project canonical project keys in VCS tags to display labels.

    A supplied snapshot makes the helper a pure presentation operation. The
    root-based compatibility path uses the explicit convenience cache and does
    not inspect filesystem mtimes. When *project_tags* is true (default),
    project refs that resolve to a taggable project render as ``+<name>``
    (D5); tagify falls back to today's ``#`` form when the tag catalog is
    cold. Pass ``project_tags=False`` only where the result is re-parsed
    by a reader that cannot understand tags, with a comment saying why.
    """
    from sase.project_aliases import humanize_project_refs_in_prompt

    return humanize_project_refs_in_prompt(
        text,
        _display_names(projects_root, snapshot),
        project_tags=project_tags,
    )


def humanize_safe_stem(
    stem: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> str:
    """Project a filename-safe project/Patch stem prefix for display."""
    display_names = _display_names(projects_root, snapshot)
    if not stem or not display_names:
        return stem

    safe_prefixes: list[tuple[str, str, str]] = []
    for key, display in display_names.items():
        safe_key = make_safe_filename(key)
        if safe_key:
            safe_prefixes.append((safe_key, display, key))
    for safe_key, display, _key in sorted(
        safe_prefixes,
        key=lambda item: (-len(item[0]), item[2]),
    ):
        if stem == safe_key:
            return display
        for separator in ("-", "_"):
            prefix = f"{safe_key}{separator}"
            if stem.startswith(prefix):
                return f"{display}{separator}{stem[len(prefix) :]}"
    return stem
