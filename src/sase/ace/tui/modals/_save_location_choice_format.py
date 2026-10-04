"""Row labels, previews, and badges for save-location picker choices."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.ace.tui.modals.mini_macro_target_catalog import destination_target_for_name
from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_CONFIG_LABEL,
    MACRO_PROJECT_DIR_LABEL,
    MACRO_PROJECT_HOME_LABEL_PREFIX,
    MACRO_USER_CONFIG_LABEL,
    MACRO_USER_OVERLAY_LABEL_PREFIX,
    shorten_macro_location_path,
)
from sase.macro.snippet_targets import (
    SNIPPET_PROJECT_CONFIG_LABEL,
    SNIPPET_USER_CONFIG_LABEL,
    SNIPPET_USER_OVERLAY_LABEL_PREFIX,
)
from sase.macro.write_targets import resolve_macro_write_target

__all__ = [
    "badges",
    "macro_preview",
    "matches_path",
    "project_section",
    "short_label",
    "snippet_preview",
    "via_chezmoi",
]


def short_label(discovery_label: str) -> str:
    """Return the compact picker label for a discovery label."""
    if discovery_label == MACRO_PROJECT_DIR_LABEL:
        return "Project macros"
    if discovery_label in (
        MACRO_PROJECT_CONFIG_LABEL,
        SNIPPET_PROJECT_CONFIG_LABEL,
    ):
        return "Project config"
    if discovery_label.startswith(MACRO_PROJECT_HOME_LABEL_PREFIX):
        return "Project, personal"
    if discovery_label == MACRO_HOME_DIR_LABEL:
        return "Home macros"
    if discovery_label in (MACRO_USER_CONFIG_LABEL, SNIPPET_USER_CONFIG_LABEL):
        return "User config"
    if discovery_label.startswith(
        MACRO_USER_OVERLAY_LABEL_PREFIX
    ) or discovery_label.startswith(SNIPPET_USER_OVERLAY_LABEL_PREFIX):
        return discovery_label.removeprefix("User ")
    return discovery_label


def _write_path_for(path: str) -> str:
    """Return the resolved write path for *path*, falling back to *path*."""
    try:
        return str(resolve_macro_write_target(path).write_path)
    except Exception:
        return path


def via_chezmoi(path: str) -> bool:
    """Return whether edits to *path* redirect through a chezmoi source."""
    try:
        return resolve_macro_write_target(path).via_chezmoi
    except Exception:
        return False


def matches_path(row_path: str, wanted: str | None) -> bool:
    """Return whether *wanted* names *row_path* or its resolved write path."""
    if not wanted:
        return False
    return wanted == row_path or wanted == _write_path_for(row_path)


def project_section(project: str | None) -> str:
    return f"Project · {project}" if project else "Project"


def _callable_reference(namespace: str | None, name: str) -> str:
    """Return the ``#`` reference previewed for *name* at a destination."""
    if not name:
        return f"#{namespace}/<name>" if namespace else "#<name>"
    if namespace and "/" not in name:
        return f"#{namespace}/{name}"
    return f"#{name}"


def _storage_name(namespace: str | None, name: str) -> str:
    """Return the physical entry name written for callable *name*."""
    if namespace:
        prefix = f"{namespace}/"
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def macro_preview(
    row: UnifiedSaveLocation,
    rows: Sequence[UnifiedSaveLocation],
    *,
    name: str,
) -> str:
    """Return the footer preview for one macro destination row."""
    count = len(row.names)
    noun = "macro" if count == 1 else "macros"
    if row.location.location_type == "directory":
        reference = _callable_reference(row.namespace, name)
        if name:
            try:
                target = destination_target_for_name(row, name, destinations=rows)
                concrete = shorten_macro_location_path(
                    target.path, str(Path.cwd()), str(Path.home())
                )
            except Exception:
                concrete = f"{row.display_path}/<name>.md"
            return f"→ {concrete} · called as {reference} · {count} {noun} here"
        return (
            f"→ {row.display_path}/<name>.md · called as {reference} "
            f"· {count} {noun} here"
        )
    entry = _storage_name(row.namespace, name) if name else "<name>"
    return f"→ {row.display_path} · macros.{entry}"


def snippet_preview(display_path: str, *, trigger: str, count: int) -> str:
    """Return the footer preview for one snippet destination row."""
    return (
        f"→ {display_path} · ace.snippets.{trigger or '<trigger>'} "
        f"· {count} snippets here"
    )


def badges(
    *,
    default_reason: str | None,
    is_current: bool,
    has_name: bool,
    has_label: str,
    is_new: bool,
    chezmoi: bool,
    shadowed_by: str | None = None,
) -> tuple[str, ...]:
    """Assemble picker badges in display order."""
    items: list[str] = []
    if default_reason is not None:
        items.append(f"★ {default_reason}")
    elif is_current:
        items.append("● current")
    if shadowed_by:
        items.append(f"⚠ shadowed by {shadowed_by}")
    if has_name:
        items.append(has_label)
    if is_new:
        items.append("new")
    if chezmoi:
        items.append("chezmoi")
    return tuple(items)
