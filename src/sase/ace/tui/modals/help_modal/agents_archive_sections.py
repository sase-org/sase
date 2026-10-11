"""Archive help box for the Agents help tab.

Read-only Archive view (child epic ``sase-1jm.3.1``): global toggle, filter,
and navigation belong here in help, while only conditionally available
actions appear in the footer. Descriptions stay within 32 chars and the box
renders at the shared 57-column width.
"""

from ...keymaps import KeymapRegistry, key_display_name, leader_key_display
from .binding_common import Sections


def archive_sections(km: KeymapRegistry) -> Sections:
    """Build the read-only Archive help box."""
    d = key_display_name
    a = km.app

    try:
        toggle_keys = leader_key_display(km, "toggle_agents_archive")
    except Exception:
        toggle_keys = ",a"
    return [
        (
            "Archive (read-only)",
            [
                (toggle_keys, "Open / close Archive"),
                (
                    f"{d(a.next_patch)} / {d(a.prev_patch)}",
                    "Move in Archive list",
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Top / bottom of list",
                ),
                (
                    f"{d(a.expand_or_layout)} / {d(a.hooks_or_collapse)}",
                    "Expand / collapse container",
                ),
                (
                    f"{d(a.focus_next_agent_panel)} / {d(a.focus_prev_agent_panel)}",
                    "Pulse / list focus",
                ),
                (d(a.act_on_agent), "Read archived run"),
                (
                    f"{d(a.toggle_mark)} / {d(a.clear_marks)}",
                    "Mark / unmark archived run",
                ),
                (d(a.choose_agent_grouping), "Archive grouping"),
                (f"{d(a.edit_query)} in:archive", "Scoped Archive filter"),
                ("x s w R (Inbox only)", "Live keys stay in Inbox"),
            ],
        ),
    ]
