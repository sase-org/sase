"""Feature ID scheme for Footprint.

A feature ID has the form ``<ns>:<path>`` and matches
``^[a-z]+:[a-z0-9_.~#-]+$``. There are no spaces, no uppercase letters, and
nothing user-authored: unrecognized values collapse to ``<ns>:~other`` and
user-defined names (custom macros, custom modes, saved-query contents)
become ``~custom``. ``tui:saved_query.<n>`` slot numbers are fine.

The recorder (a later phase) and the catalog generator both build IDs through
the helpers here so IDs cannot drift between them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

ID_PATTERN = r"^[a-z]+:[a-z0-9_.~#-]+$"
_ID_RE = re.compile(ID_PATTERN)

NAMESPACES: tuple[str, ...] = (
    "cli",
    "tui",
    "view",
    "macro",
    "skill",
    "config",
    "auto",
    "plugin",
)

CATALOG_SCHEMA = "sase.footprint.catalog/1"
OVERLAY_SCHEMA = "sase.footprint.overlay/1"

ROOT_COMMAND_ID = "cli:_root"

OTHER_SENTINEL = "~other"
CUSTOM_SENTINEL = "~custom"

#: First-party plugin command words. Third-party plugin words are recorded as
#: ``plugin:~third_party`` and never enter the catalog.
FIRST_PARTY_PLUGIN_COMMANDS: tuple[str, ...] = ("listen",)

#: Legacy top-level command words and the canonical command they resolve to.
#: Mirrors the completion compat layer's alias marking; the generator and its
#: tests pin the two together, and the recorder normalizes through this map.
CLI_ALIASES: dict[str, str] = {
    "artifact-file": "artifact",
    # Retained legacy aliases (compat boundary), normalized before recording.
    "changespec": "patch",
    "task": "proc",
    "vcs": "stitch",
}

#: Navigation chrome: app-scope cursor movement, scroll, and focus/tab
#: cycling. These actions move attention rather than do things, so they are
#: neither catalogued nor counted: a catalogued action that is never recorded
#: would look like a false deletion candidate. Pane-scope bindings (for
#: example ``tui:statistics.scroll_down``) stay catalogued so each pane's
#: usage remains visible, and tab destinations are still recorded as
#: ``view:tab.*`` through the view-entry seam.
NAVIGATION_ACTIONS: frozenset[str] = frozenset(
    {
        "tui:app.agents_next",
        "tui:app.agents_prev",
        "tui:app.beads_next",
        "tui:app.beads_prev",
        "tui:app.files_next",
        "tui:app.files_next_version",
        "tui:app.files_prev",
        "tui:app.files_prev_version",
        "tui:app.focus_next_agent_panel",
        "tui:app.focus_next_service_panel",
        "tui:app.focus_prev_agent_panel",
        "tui:app.focus_prev_service_panel",
        "tui:app.jump_to_all_entries",
        "tui:app.jump_to_entry",
        "tui:app.jump_to_entry_fast",
        "tui:app.jump_to_entry_forward",
        "tui:app.jump_to_node",
        "tui:app.next_agents_tab",
        "tui:app.next_card_block",
        "tui:app.next_chop_run",
        "tui:app.next_deck",
        "tui:app.next_deck_card",
        "tui:app.next_patch",
        "tui:app.next_query",
        "tui:app.next_tab",
        "tui:app.plans_next",
        "tui:app.plans_prev",
        "tui:app.prev_agents_tab",
        "tui:app.prev_card_block",
        "tui:app.prev_chop_run",
        "tui:app.prev_deck",
        "tui:app.prev_deck_card",
        "tui:app.prev_patch",
        "tui:app.prev_query",
        "tui:app.prev_tab",
        "tui:app.scroll_detail_down",
        "tui:app.scroll_detail_up",
        "tui:app.scroll_prompt_down",
        "tui:app.scroll_prompt_up",
        "tui:app.scroll_to_bottom",
        "tui:app.scroll_to_top",
        "tui:app.stitches_next",
        "tui:app.stitches_prev",
        "tui:app.toggle_deck_focus",
        "tui:app.toggle_deck_focus_reverse",
    }
)


def is_valid_feature_id(value: str) -> bool:
    """Return whether *value* matches the feature ID pattern."""
    return _ID_RE.match(value) is not None


_DISALLOWED_RE = re.compile(r"[^a-z0-9_.~#-]")


def sanitize(value: str) -> str:
    """Map an arbitrary registry name to its ID-safe form.

    Lowercases *value* and replaces every ID-disallowed character with
    ``_``. Applied to real registry names that predate the scheme (for
    example the ``sase bead +1`` subcommand, ``ref:plan`` artifact
    references, and config keys containing ``/`` or ``@``). Both the
    generator and the recorder sanitize through this helper, so IDs cannot
    drift between them.
    """
    return _DISALLOWED_RE.sub("_", value.lower())


def other_id(ns: str) -> str:
    """Return the ``~other`` collapse ID for namespace *ns*."""
    return f"{ns}:{OTHER_SENTINEL}"


def custom_id(ns: str) -> str:
    """Return the ``~custom`` collapse ID for namespace *ns*."""
    return f"{ns}:{CUSTOM_SENTINEL}"


def cli_id(words: Sequence[str]) -> str:
    """Return the command ID for parser path *words*."""
    if not words:
        return ROOT_COMMAND_ID
    return "cli:" + ".".join(sanitize(word) for word in words)


def cli_option_id(cmd_id: str, dest: str) -> str:
    """Return the option ID for command *cmd_id* and option *dest*."""
    return f"{cmd_id}#{sanitize(dest)}"


def tui_id(scope: str, action: str) -> str:
    """Return the TUI ID for *scope* and *action* field."""
    return f"tui:{sanitize(scope)}.{sanitize(action)}"


def tab_view_id(name: str) -> str:
    """Return the view ID for top-level tab *name*."""
    return f"view:tab.{name}"


def admin_view_id(name: str) -> str:
    """Return the view ID for config-center tab *name*."""
    return f"view:admin.{name}"


def stats_view_id(name: str) -> str:
    """Return the view ID for statistics view *name*."""
    return f"view:stats.{name}"


def _camel_to_snake(name: str) -> str:
    snake = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake).lower()


def modal_id(class_name: str) -> str:
    """Return the modal view ID for a ``ModalScreen`` subclass name.

    A trailing ``Modal`` or ``Screen`` suffix is dropped, so
    ``AddMacroModal`` becomes ``view:modal.add_macro``.
    """
    base = class_name
    for suffix in ("Modal", "Screen"):
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    return f"view:modal.{_camel_to_snake(base)}"


__all__ = [
    "CATALOG_SCHEMA",
    "CUSTOM_SENTINEL",
    "FIRST_PARTY_PLUGIN_COMMANDS",
    "ID_PATTERN",
    "NAMESPACES",
    "NAVIGATION_ACTIONS",
    "OTHER_SENTINEL",
    "OVERLAY_SCHEMA",
    "ROOT_COMMAND_ID",
    "admin_view_id",
    "cli_id",
    "cli_option_id",
    "custom_id",
    "is_valid_feature_id",
    "modal_id",
    "CLI_ALIASES",
    "other_id",
    "sanitize",
    "stats_view_id",
    "tab_view_id",
    "tui_id",
]
