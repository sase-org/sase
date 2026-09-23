"""Cached project-tag catalog (D2) and tag-spelling helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_wire import effective_project_name

_TAG_NAME_RE = re.compile(r"[A-Za-z](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?")


def is_project_tag_name(name: str) -> bool:
    """Return whether *name* can be written as a ``+<project>`` tag (D1)."""

    return _TAG_NAME_RE.fullmatch(name) is not None


@dataclass(frozen=True)
class ProjectTagTarget:
    """One Python-side project-tag target (D2 resolution target)."""

    key: str
    name: str
    aliases: tuple[str, ...] = ()
    tag: str | None = None
    workflow_type: str | None = None
    vcs_ref: str | None = None
    provider_display: str = ""
    state: str = "enabled"
    workspace_dir: str | None = None
    accent: str | None = None
    accent_index: int | None = None
    # Python-side only (never sent over the wire): whether the project can
    # launch. Completion rows are built from launchable targets only.
    launchable: bool = True

    def to_wire(self) -> dict[str, object]:
        """Return the ``ProjectTagTargetWire`` dict for the core bindings."""

        return {
            "key": self.key,
            "name": self.name,
            "aliases": list(self.aliases),
            "workflow_type": self.workflow_type,
            "state": self.state,
            "workspace_dir": self.workspace_dir,
        }


@dataclass(frozen=True)
class ProjectTagCatalog:
    """Snapshot of every tag target plus the accent palette (D2/D6)."""

    targets: tuple[ProjectTagTarget, ...] = ()
    accent_palette: tuple[str, ...] = ()
    signature: object = None

    def wire_targets(self) -> list[dict[str, object]]:
        """Return core ``ProjectTagTargetWire`` dicts in catalog order."""

        return [target.to_wire() for target in self.targets]

    def target(self, index: int) -> ProjectTagTarget:
        """Return the target at core index *index*."""

        return self.targets[index]

    def known_tags(self) -> list[str]:
        """Return sorted ``+<name>`` spellings for taggable targets."""

        return sorted(target.tag for target in self.targets if target.tag is not None)


# Module-level cache: (signature, catalog). Invalidated by ProjectSpec file
# mtimes so both project membership and provider detection are picked up, and
# explicitly clearable via :func:`_clear_project_tag_catalog_cache`.
_CATALOG_CACHE: tuple[object, ProjectTagCatalog] | None = None


def _catalog_signature(projects_dir: Path) -> object | None:
    """Return a cheap cache signature covering tag targets, or ``None``."""

    from sase.ace.patch import iter_patch_project_files

    try:
        project_files = iter_patch_project_files(
            projects_dir=projects_dir,
            include_states=("enabled", "disabled"),
            include_home=True,
        )
    except OSError:
        return None

    file_signatures: list[tuple[str, int, int]] = []
    for project_file in project_files:
        try:
            stat = project_file.stat()
        except OSError:
            continue
        file_signatures.append((str(project_file), stat.st_mtime_ns, stat.st_size))
    return (str(projects_dir), tuple(sorted(file_signatures)))


def build_targets(
    records: Any,
    *,
    detect_workflow_type: Any | None = None,
    get_display_name: Any | None = None,
) -> list[ProjectTagTarget]:
    """Build tag targets from lifecycle *records* (no filesystem access).

    ``detect_workflow_type`` / ``get_display_name`` default to the workspace
    registry; pass alternates to share one source with completion rows.
    Only true projects and the system home entry are kept; siblings are the
    caller's responsibility to exclude.
    """

    from sase.project_accents import (
        accent_among_keys,
        project_accent,
        project_accent_index,
    )

    if detect_workflow_type is None:
        from sase.workspace_provider import (
            detect_workflow_type as _detect_workflow_type,
        )

        detect_workflow_type = _detect_workflow_type
    if get_display_name is None:
        from sase.workspace_provider import get_display_name as _get_display_name

        get_display_name = _get_display_name

    kept = [
        record
        for record in records
        if getattr(record, "is_project", True)
        or getattr(record, "system_managed", False)
    ]
    among = accent_among_keys(kept)

    targets: list[ProjectTagTarget] = []
    for record in kept:
        display_name = effective_project_name(record)
        tag = f"+{display_name}" if is_project_tag_name(display_name) else None
        try:
            workflow_type: str | None = detect_workflow_type(record.project_file)
        except ValueError:
            workflow_type = None
        if not workflow_type:
            workflow_type = None
        provider_display = ""
        if workflow_type:
            provider_display = get_display_name(workflow_type) or workflow_type
        if record.system_managed:
            state = "system"
        else:
            state = record.state
        # Accents are null for disabled projects and home (D2).
        accent: str | None = None
        accent_index: int | None = None
        if state == "enabled" and record.project_name.casefold() != "home":
            accent = project_accent(record.project_name, among=among)
            accent_index = project_accent_index(record.project_name, among=among)
        vcs_ref = f"#{workflow_type}:{display_name}" if workflow_type else None
        targets.append(
            ProjectTagTarget(
                key=record.project_name,
                name=display_name,
                aliases=tuple(record.aliases),
                tag=tag,
                workflow_type=workflow_type,
                vcs_ref=vcs_ref,
                provider_display=provider_display,
                state=state,
                workspace_dir=record.workspace_dir,
                accent=accent,
                accent_index=accent_index,
                launchable=bool(getattr(record, "launchable", True)),
            )
        )

    targets.sort(key=lambda target: target.name.casefold())
    return targets


def _synthetic_home_target() -> ProjectTagTarget:
    """Return the always-present system ``home`` tag target (D2).

    ``home`` is a launch target even before its ProjectSpec exists, so
    ``+home`` expands to ``#git:home`` and bootstraps exactly as
    ``#git:home`` does on a fresh ``SASE_HOME``. It carries no accent.
    """

    from sase.workspace_provider import get_display_name

    try:
        provider_display = get_display_name("git") or "git"
    except Exception:  # noqa: BLE001 - display degrades to the raw type.
        provider_display = "git"
    return ProjectTagTarget(
        key="home",
        name="home",
        aliases=(),
        tag="+home",
        workflow_type="git",
        vcs_ref="#git:home",
        provider_display=provider_display,
        state="system",
        workspace_dir=None,
        accent=None,
        accent_index=None,
        launchable=True,
    )


def _build_catalog(projects_dir: Path) -> ProjectTagCatalog:
    """Build a fresh catalog snapshot from *projects_dir*."""

    from sase.core.project_lifecycle_facade import list_project_records
    from sase.project_accents import PROJECT_ACCENTS

    records = list_project_records(
        projects_dir,
        ("enabled", "disabled"),
        include_home=True,
    )
    targets = list(build_targets(records))
    if not any(target.key.casefold() == "home" for target in targets):
        targets.append(_synthetic_home_target())
        targets.sort(key=lambda target: target.name.casefold())
    return ProjectTagCatalog(
        targets=tuple(targets),
        accent_palette=tuple(PROJECT_ACCENTS),
    )


def load_project_tag_catalog(
    projects_dir: Path | str | None = None,
    *,
    use_cache: bool = True,
) -> ProjectTagCatalog:
    """Return the project-tag catalog, rebuilding while specs are unchanged.

    Args:
        projects_dir: Projects root to enumerate. Defaults to the SASE
            projects directory.
        use_cache: When ``True`` (default), reuse the cached snapshot while
            the project-spec signature is unchanged.

    Returns:
        The current :class:`ProjectTagCatalog` snapshot.
    """

    global _CATALOG_CACHE  # noqa: PLW0603

    resolved = Path(projects_dir) if projects_dir is not None else sase_projects_dir()
    signature = _catalog_signature(resolved)

    if use_cache and signature is not None and _CATALOG_CACHE is not None:
        cached_signature, cached_catalog = _CATALOG_CACHE
        if cached_signature == signature:
            return cached_catalog

    catalog = _build_catalog(resolved)
    catalog = ProjectTagCatalog(
        targets=catalog.targets,
        accent_palette=catalog.accent_palette,
        signature=signature,
    )
    if use_cache:
        _CATALOG_CACHE = (signature, catalog)
    return catalog


def peek_project_tag_catalog() -> ProjectTagCatalog | None:
    """Return the last catalog snapshot without building, or ``None``.

    Never touches disk or spawns processes; render and keystroke paths must
    use this and fall back when it returns ``None`` (catalog cold).
    """

    if _CATALOG_CACHE is None:
        return None
    return _CATALOG_CACHE[1]


def _clear_project_tag_catalog_cache() -> None:
    """Drop the cached catalog snapshot (test-only helper)."""

    global _CATALOG_CACHE  # noqa: PLW0603
    _CATALOG_CACHE = None


def peek_project_tag_catalog_signature() -> object | None:
    """Return the warm catalog signature without building, or ``None``.

    Render paths key this into their caches so tagify and tag colors
    refresh once the catalog warms instead of serving the cold ``#``
    rendering forever. Never touches disk or spawns processes.
    """

    if _CATALOG_CACHE is None:
        return None
    return _CATALOG_CACHE[1].signature


__all__ = [
    "ProjectTagCatalog",
    "ProjectTagTarget",
    "build_targets",
    "is_project_tag_name",
    "load_project_tag_catalog",
    "peek_project_tag_catalog",
    "peek_project_tag_catalog_signature",
]
