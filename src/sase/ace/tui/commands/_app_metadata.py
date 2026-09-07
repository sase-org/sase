"""App action metadata for the ace TUI command catalog.

The (action, label, category, tabs, aliases) table is split across sibling
modules to keep each file under the 500-line cap:

- :mod:`sase.ace.tui.commands._app_metadata_nav` — navigation, tabs, and
  artifact-pane commands.
- :mod:`sase.ace.tui.commands._app_metadata_actions` — patch, agent, axe,
  folding, and marking commands.
- :mod:`sase.ace.tui.commands._app_metadata_display` — grouping, queries,
  display, workspace, and mode commands.

Action names MUST match an :class:`~sase.ace.tui.keymaps.app_keymaps.AppKeymaps`
field. Labels are tuned for the palette; categories mirror the help modal
sections; tabs encode where the binding can ever fire (entry-level
applicability is layered on by ``availability.py``).
"""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands._app_metadata_actions import ACTION_COMMAND_META
from sase.ace.tui.commands._app_metadata_display import DISPLAY_COMMAND_META
from sase.ace.tui.commands._app_metadata_nav import NAV_COMMAND_META
from sase.ace.tui.commands.types import AppCommandMeta
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps

APP_COMMAND_META: tuple[AppCommandMeta, ...] = (
    *NAV_COMMAND_META,
    *ACTION_COMMAND_META,
    *DISPLAY_COMMAND_META,
)


def ensure_metadata_covers_app_keymaps(
    meta: tuple[AppCommandMeta, ...] = APP_COMMAND_META,
) -> None:
    """Fail loudly if metadata drifts from :class:`AppKeymaps`."""
    meta_actions = {row[0] for row in meta}
    field_names = {f.name for f in fields(AppKeymaps)}
    missing = field_names - meta_actions
    extra = meta_actions - field_names
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"AppKeymaps fields missing metadata: {sorted(missing)}")
        if extra:
            parts.append(f"metadata for nonexistent fields: {sorted(extra)}")
        raise RuntimeError(
            "_APP_COMMAND_META / AppKeymaps mismatch - " + "; ".join(parts)
        )


ensure_metadata_covers_app_keymaps()
