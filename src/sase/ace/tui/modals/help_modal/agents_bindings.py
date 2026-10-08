"""Agents tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name
from .agents_main_sections import main_sections
from .agents_mode_sections import mode_sections
from .agents_reference_sections import reference_sections
from .binding_common import (
    ADMIN_CENTER_TASKS_SECTION,
    ADMIN_CENTER_UPDATES_SECTION,
    admin_center_machines_section,
    PROMPT_INPUT_SECTION,
    admin_center_opener_help_label,
    admin_center_projects_section,
    Sections,
    custom_mode_sections,
    memory_panel_section,
    refresh_help_label,
    snippets_panel_section,
)

__all__ = ["agents_bindings"]


def agents_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the Agents tab."""
    d = key_display_name
    a = km.app

    sections: Sections = [
        *main_sections(km),
        *mode_sections(km),
        *reference_sections(km),
    ]
    # Insert custom mode sections before "General".
    sections.extend(custom_mode_sections(km))
    sections.append(PROMPT_INPUT_SECTION)
    sections.append(memory_panel_section(km))
    sections.append(snippets_panel_section(km))
    sections.append(ADMIN_CENTER_TASKS_SECTION)
    sections.append(admin_center_machines_section(km))
    sections.append(admin_center_projects_section(km))
    sections.append(ADMIN_CENTER_UPDATES_SECTION)
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                ("[ / ]", "Switch Keymaps / Guide"),
                (
                    d(a.open_config_center),
                    admin_center_opener_help_label(),
                ),
                (d(a.show_help), "Show this help"),
                (
                    d(a.show_notifications),
                    "All unread notifications (Enter opens; d debugs)",
                ),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.stop_axe_and_quit), "Quit / restart menu"),
                (d(a.agents_refresh), refresh_help_label()),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
                (d(a.open_command_line), "Open command line"),
            ],
        ),
    )
    return sections
