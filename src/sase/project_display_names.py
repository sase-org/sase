"""Immutable project identity-to-display projection helpers.

Storage and query layers provide canonical project keys. Human-facing renderers
consume labels from a preloaded :class:`ProjectDisplaySnapshot` and retain the
paired key for interactions, joins, persistence, and structured output.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import re
from threading import RLock
from types import MappingProxyType
from typing import Any

from sase.core.paths import make_safe_filename, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)


@dataclass(frozen=True, slots=True)
class ProjectDisplayProjection:
    """Paired canonical identity and human-facing label for one project."""

    project_key: str
    project_label: str

    @property
    def sort_key(self) -> tuple[str, str]:
        """Return the visible-label/canonical-key presentation sort key."""
        return (self.project_label.casefold(), self.project_key)


@dataclass(frozen=True, slots=True)
class ProjectDisplaySnapshot(Mapping[str, str]):
    """Immutable batch projection from canonical project keys to labels.

    Duplicate labels remain distinct entries because canonical keys own
    identity. Unknown or deleted keys resolve to themselves through
    :meth:`label_for` and :meth:`projection_for`.
    """

    labels_by_key: Mapping[str, str] = field(default_factory=dict, repr=False)
    projections: tuple[ProjectDisplayProjection, ...] = field(init=False)
    signature: tuple[tuple[str, str], ...] = field(init=False)

    def __post_init__(self) -> None:
        labels = MappingProxyType(dict(self.labels_by_key))
        projections = tuple(
            sorted(
                (
                    ProjectDisplayProjection(project_key, project_label)
                    for project_key, project_label in labels.items()
                ),
                key=lambda projection: projection.sort_key,
            )
        )
        object.__setattr__(self, "labels_by_key", labels)
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "signature", tuple(sorted(labels.items())))

    @classmethod
    def from_records(
        cls,
        records: Iterable[ProjectRecordWire],
    ) -> ProjectDisplaySnapshot:
        """Build one immutable snapshot from one lifecycle-record batch."""
        return cls(
            {record.project_name: effective_project_name(record) for record in records}
        )

    def __getitem__(self, project_key: str) -> str:
        return self.labels_by_key[project_key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.labels_by_key)

    def __len__(self) -> int:
        return len(self.labels_by_key)

    def label_for(self, project_key: str) -> str:
        """Resolve *project_key* to its label, falling back to the key."""
        return self.labels_by_key.get(project_key, project_key)

    def projection_for(self, project_key: str) -> ProjectDisplayProjection:
        """Return a paired identity/label projection for *project_key*."""
        return ProjectDisplayProjection(project_key, self.label_for(project_key))


_PROJECT_DISPLAY_NAME_CACHE: dict[str, ProjectDisplaySnapshot] | None = None
_PROJECT_DISPLAY_NAME_CACHE_LOCK = RLock()
_CL_NAME_TOKEN_RE = re.compile(
    r"(?P<prefix>^|(?<=[\s(\[{]))"
    r"(?P<name>[A-Za-z0-9_.~-]+)"
    r"(?P<suffix>(?=$|[\s)\]},.!?;:\"']))"
)


def _projects_root(projects_root: Path | str | None) -> Path:
    if projects_root is None:
        return sase_projects_dir()
    return Path(projects_root).expanduser()


def _projects_root_cache_key(projects_root: Path | str | None) -> str:
    return str(_projects_root(projects_root).absolute())


def load_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectDisplaySnapshot:
    """Fresh-load a snapshot from one lifecycle inventory read.

    This entry point is intended for worker/off-thread refresh paths. Inventory
    failures degrade to an empty snapshot, whose lookups fall back to canonical
    keys.
    """
    root = _projects_root(projects_root)
    try:
        records = list_project_records(root, "all", include_home=True)
    except Exception:
        return ProjectDisplaySnapshot()
    return ProjectDisplaySnapshot.from_records(records)


def _get_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectDisplaySnapshot:
    """Return the explicitly managed cached snapshot for convenience callers.

    Cache freshness never depends on filesystem metadata. Call
    :func:`invalidate_project_display_snapshot` after a supported mutation.
    """
    global _PROJECT_DISPLAY_NAME_CACHE  # noqa: PLW0603

    cache_key = _projects_root_cache_key(projects_root)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        if _PROJECT_DISPLAY_NAME_CACHE is None:
            _PROJECT_DISPLAY_NAME_CACHE = {}
        cached = _PROJECT_DISPLAY_NAME_CACHE.get(cache_key)
        if cached is None:
            cached = load_project_display_snapshot(projects_root)
            _PROJECT_DISPLAY_NAME_CACHE[cache_key] = cached
        return cached


def invalidate_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> None:
    """Invalidate the cached snapshot for *projects_root* without disk I/O."""
    cache_key = _projects_root_cache_key(projects_root)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        if _PROJECT_DISPLAY_NAME_CACHE is not None:
            _PROJECT_DISPLAY_NAME_CACHE.pop(cache_key, None)


def _project_display_name_map_cached(
    projects_root: Path | str | None = None,
) -> Mapping[str, str]:
    """Return the immutable cached ``canonical key -> label`` mapping."""
    return _get_project_display_snapshot(projects_root)


def _display_names(
    projects_root: Path | str | None,
    snapshot: ProjectDisplaySnapshot | None,
) -> Mapping[str, str]:
    if snapshot is not None:
        return snapshot
    return _project_display_name_map_cached(projects_root)


def project_display_name_map_signature(
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return a stable signature for a supplied or cached display snapshot."""
    if snapshot is not None:
        return snapshot.signature
    return tuple(sorted(_project_display_name_map_cached(projects_root).items()))


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
    label = _project_display_name_map_cached(projects_root).get(
        project_key, project_key
    )
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
    """Project a canonical project/ChangeSpec name to a display label."""
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
    """Project standalone canonical project/ChangeSpec tokens in display text."""
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
) -> str:
    """Project canonical project keys in VCS tags to display labels.

    A supplied snapshot makes the helper a pure presentation operation. The
    root-based compatibility path uses the explicit convenience cache and does
    not inspect filesystem mtimes.
    """
    from sase.project_aliases import humanize_project_refs_in_prompt

    return humanize_project_refs_in_prompt(
        text,
        _display_names(projects_root, snapshot),
    )


# symvision: https://github.com/sase-org/sase-telegram.git
def humanize_safe_stem(
    stem: str,
    projects_root: Path | str | None = None,
    *,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> str:
    """Project a filename-safe project/ChangeSpec stem prefix for display."""
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


__all__ = [
    "ProjectDisplayProjection",
    "ProjectDisplaySnapshot",
    "attach_project_display_names",
    "humanize_cl_names_in_text",
    "humanize_cl_name",
    "humanize_safe_stem",
    "humanize_vcs_refs_in_text",
    "invalidate_project_display_snapshot",
    "load_project_display_snapshot",
    "project_display_for",
    "project_display_name_map_signature",
    "project_display_name_for",
]
