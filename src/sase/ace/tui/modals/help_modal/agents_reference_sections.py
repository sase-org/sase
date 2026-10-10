"""Query syntax and legend reference sections for the Agents help tab."""

from ...keymaps import KeymapRegistry, key_display_name
from ...widgets._agent_list_render_rail import RAIL_LEGEND
from ...widgets.update_accents import UPDATE_RECOVERY_GLYPH
from .binding_common import Sections, key_sequence_display


def reference_sections(km: KeymapRegistry) -> Sections:
    """Build the query-syntax, grouping, badge, glyph, and rail sections."""
    d = key_display_name
    a = km.app

    grouping_opener_rows = (
        [(d(a.choose_agent_grouping), "Choose grouping")]
        if d(a.choose_agent_grouping)
        else []
    )
    panel_layout_rows = (
        [
            (
                key_sequence_display(a.choose_agent_grouping, "o"),
                "Panel layout (Split / Merged / All tabs)",
            )
        ]
        if d(a.choose_agent_grouping)
        else []
    )

    return [
        (
            "Agent Query Syntax",
            (
                [
                    ("status:VAL", "Enum on status; Tab-completed"),
                    ("kind:VAL", "Kind enum; Tab-completed"),
                    ("cl:VAL", "Substring on Patch name"),
                    ("project:VAL", "Exact project; Tab-completed"),
                    ("name:VAL", "Exact agent name"),
                    ("session:VAL  clan:VAL", "Exact session / clan name"),
                    ("role:VAL", "code | plan | monitor"),
                    ("workflow:VAL", "Substring on workflow name"),
                    ("model:VAL", "Substring on model"),
                    ("provider:VAL", "Enum on llm provider"),
                    ("machine:VAL  machine:", "Exact machine/here / any remote"),
                    ("tribe:VAL", "Exact user-defined live tribe"),
                    ("source:VAL", "axe | manual"),
                    ("needs:input", "Question / waiting input"),
                    ("attention:BOOL", "true | false (needs attention)"),
                    ("pinned:BOOL  unread:BOOL", "true | false"),
                    ("hidden:BOOL  retry:BOOL", "true | false"),
                    ("since:2h  until:2h", "Started at/after / at-before"),
                    ("after:2h  before:2h", "Finished at/after / at-before"),
                    ("min:5m  max:1h", "Runtime at least / at most"),
                    ("attempt:N", "Retry attempt number (equality)"),
                    ('text:"..."', "Quoted substring (whole hay)"),
                    ('c"FAILED"', "Case-sensitive quoted"),
                    ("AND OR NOT ( )", "Boolean ops; juxtapose = AND"),
                    ("legacy type:run", "Use kind:agent"),
                    ("legacy age>2h", "Use until:2h / since:5m"),
                ]
            ),
        ),
        (
            "Grouping",
            [
                *grouping_opener_rows,
                *panel_layout_rows,
                ("p/d/s/m", "Project/date/status/machine"),
                ("by date", "Sub-grouped by hour, day, or week"),
                ("by machine", "here + remotes, status subgroups"),
                ("⏳ Waiting", "Timer or dependency wait"),
                ("▲ Stopped", "User must act"),
                ("▶ Running", "Actively executing"),
                (f"{UPDATE_RECOVERY_GLYPH} RESTARTING", "Auto-restart in flight"),
                ("✗ Failed", "Failed and retried"),
                ("✓ Done", "Completed"),
            ],
        ),
        (
            "Waiting Badges",
            [
                ("▶2 ✓1 ?1", "Agent wait counts"),
                ("○2 ◐1", "Bead wait counts"),
                ("▶1 ◐2", "Bead follows matching agent"),
                ("✓1 ●1", "Closed bead follows done agent"),
                ("◇1 ◈1", "Unmatched beads trail"),
                ("?1 ?2", "Unknown agent + bead"),
                ("?N", "Unknown agent or bead"),
                ("↪ epic…", "Epic launch in flight"),
                ("↪ ◐ sase-7k", "Following a launched epic"),
                ("↪ ◐2", "Following several epics"),
                ("↪ !", "Epic follow blocked"),
                ("▶ ◐ … ⏳ ✓ ✗ ▲", "Agent states (see Grouping)"),
                ("!", "Reserved tribe never resolves"),
                ("[tribes] @t → name ✓", "Bound tribe entity/status"),
                ("[tribes] @t (next launch)", "Pending tribe wait"),
                ("[tribes] @default !", "Reserved tribe wait"),
                ("[beads] id ◐", "Bead wait target status"),
                ("[agents] name ✓ ↪ id ◐", "Followed epic narration"),
            ],
        ),
        (
            "Agent Row Glyphs",
            [
                ("×N", "N steps (collapsed)"),
                ("×N +M / −M", "M shown / hidden steps or session members"),
                ("⚙", "Monitor turn, running (amber)"),
                ("⚙", "Monitor turn, finished (grey)"),
                ("⚙N", "N running monitors (amber)"),
                ("⚙N", "N finished monitors (grey)"),
                ("⋔", "Gate turn, pending/running (cyan)"),
                ("⋔", "Gate turn, settled (grey)"),
                ("⋔", "Gate turn, failed (red)"),
                ("⋔N", "N pending/running gates (cyan)"),
                ("⋔N", "N settled gates (grey)"),
                ("⋔N", "N failed gates (red)"),
                ("❯", "Bash / python step"),
                ("◆", "Bead-linked agent"),
                ("↺", "Reverted (changes undone)"),
                (UPDATE_RECOVERY_GLYPH, "Auto-restarted replacement"),
                ("↻N", "N attempts / retry depth"),
                ("≡", "Workflow row"),
                ("❑", "Patch row"),
                ("⚡", "Auto-approve (plan)"),
                ("⚡T", "Auto-approve as tale"),
                ("⚡E", "Auto-approve as epic"),
                ("◌", "Hidden by default"),
                ("↳", "Retry chain attempt"),
            ],
        ),
        (
            "Node Rail",
            [(glyph.plain, meaning) for glyph, meaning in RAIL_LEGEND],
        ),
    ]
