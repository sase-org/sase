"""Project-scope detection and inventory for initialization commands."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.vcs_provider import VCSProviderNotFoundError, detect_vcs_family


@dataclass(frozen=True)
class InitProjectTarget:
    """One enabled main project considered by ``sase init --all``."""

    project_name: str
    display_name: str
    project_file: Path
    workspace_dir: Path | None
    warnings: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def reference(self) -> str:
        """Return a display label that retains the stable directory key."""
        if self.display_name == self.project_name:
            return self.display_name
        return f"{self.display_name} ({self.project_name})"


@dataclass(frozen=True)
class InitProjectInventory:
    """Resolved initialization targets or a global inventory failure."""

    targets: tuple[InitProjectTarget, ...]
    error: str | None = None


def is_project_directory(cwd: Path | str | None = None) -> bool:
    """Return whether *cwd* is inside a version-controlled project."""
    path = Path.cwd() if cwd is None else Path(cwd)
    try:
        return detect_vcs_family(str(path)) is not None
    except VCSProviderNotFoundError:
        # ``detect_vcs_family`` only reaches provider classification after a
        # marker such as .git has already been found. For init scoping, that
        # marker is enough even if the checkout has no classifiable provider.
        return True


def _record_sort_key(record: ProjectRecordWire) -> tuple[str, str]:
    return (effective_project_name(record).casefold(), record.project_name)


def _contains_warning(warnings: tuple[str, ...], fragment: str) -> bool:
    folded_fragment = fragment.casefold()
    return any(folded_fragment in warning.casefold() for warning in warnings)


def _target_for_record(record: ProjectRecordWire) -> InitProjectTarget:
    display_name = effective_project_name(record)
    warnings = tuple(dict.fromkeys((*record.warnings, *record.parse_warnings)))
    project_file = Path(record.project_file).expanduser()
    workspace_dir = (
        Path(record.workspace_dir).expanduser() if record.workspace_dir else None
    )
    unavailable_reason: str | None = None

    if not project_file.is_file():
        if not _contains_warning(warnings, "projectspec file not found"):
            unavailable_reason = f"project file is unavailable: {project_file}"
        else:
            unavailable_reason = "project file is unavailable"
    elif workspace_dir is None:
        if not _contains_warning(warnings, "workspace_dir"):
            unavailable_reason = "no primary workspace is recorded"
        else:
            unavailable_reason = "primary workspace is unavailable"
    elif not workspace_dir.is_dir():
        unavailable_reason = f"primary workspace is unavailable: {workspace_dir}"

    return InitProjectTarget(
        project_name=record.project_name,
        display_name=display_name,
        project_file=project_file,
        workspace_dir=workspace_dir,
        warnings=warnings,
        unavailable_reason=unavailable_reason,
        aliases=tuple(dict.fromkeys(record.aliases)),
    )


def resolve_init_project_inventory() -> InitProjectInventory:
    """Resolve every enabled, non-system main project through the core facade."""
    try:
        records = list_project_records(
            sase_projects_dir(),
            "enabled",
            include_home=False,
            projects_only=True,
        )
    except Exception as exc:  # pragma: no cover - facade failures are rare
        return InitProjectInventory(
            targets=(),
            error=f"project inventory could not be loaded: {exc}",
        )

    targets = tuple(
        _target_for_record(record)
        for record in sorted(records, key=_record_sort_key)
        if record.is_project
        and record.state == "enabled"
        and record.project_name != "home"
        and not record.system_managed
    )
    return InitProjectInventory(targets=targets)


def _target_selectors(target: InitProjectTarget) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (target.project_name, target.display_name, *target.aliases)
            if value
        )
    )


def _valid_init_project_names(targets: Sequence[InitProjectTarget]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for target in targets:
        for value in _target_selectors(target):
            if value not in seen:
                seen.add(value)
                names.append(value)
    return tuple(names)


def select_init_project_targets(
    inventory: InitProjectInventory,
    names: Sequence[str],
) -> InitProjectInventory:
    """Filter *inventory* to the named enabled projects.

    Each name may be a project name, display name, or alias. Unknown or
    non-enabled names fail with an error listing the valid names. Repeated
    names are de-duplicated while preserving request order.
    """
    if inventory.error is not None:
        return inventory
    if not names:
        return InitProjectInventory(
            targets=(),
            error="at least one project name is required",
        )

    selected: list[InitProjectTarget] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.strip()
        matches = [
            target
            for target in inventory.targets
            if name and name in _target_selectors(target)
        ]
        if not matches:
            valid = _valid_init_project_names(inventory.targets)
            listed = ", ".join(valid) if valid else "(none)"
            return InitProjectInventory(
                targets=(),
                error=(
                    f"unknown or non-enabled project {raw_name!r}; "
                    f"valid names: {listed}"
                ),
            )
        if len(matches) > 1:
            matched = ", ".join(target.project_name for target in matches)
            return InitProjectInventory(
                targets=(),
                error=f"project {raw_name!r} is ambiguous; matches: {matched}",
            )
        target = matches[0]
        if target.project_name not in seen:
            seen.add(target.project_name)
            selected.append(target)
    return InitProjectInventory(targets=tuple(selected))


def resolve_cwd_init_project_identity() -> tuple[str, str]:
    """Return ``(name, display_name)`` for the current working directory."""
    inventory = resolve_init_project_inventory()
    cwd = Path.cwd().resolve()
    for target in inventory.targets:
        if target.workspace_dir is None:
            continue
        try:
            if target.workspace_dir.expanduser().resolve() == cwd:
                return target.project_name, target.display_name
        except OSError:
            continue
    from sase.bead.project_name import infer_project_name_from_cwd

    name = infer_project_name_from_cwd() or Path.cwd().name
    return name, name


__all__ = [
    "InitProjectInventory",
    "InitProjectTarget",
    "is_project_directory",
    "resolve_cwd_init_project_identity",
    "resolve_init_project_inventory",
    "select_init_project_targets",
]
