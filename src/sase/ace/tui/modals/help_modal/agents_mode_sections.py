"""Mode keybinding sections for the Agents help tab."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import (
    Sections,
    key_sequence_display,
    leader_full_history_help_rows,
    sk,
)


def mode_sections(km: KeymapRegistry) -> Sections:
    """Build the folding, leader/bang/copy mode, and modal help sections."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode
    fm = km.fold_mode

    ag_copy = cm.keys["agents"]
    assert isinstance(ag_copy, dict)
    ag_fold = fm.keys["agents"]
    assert isinstance(ag_fold, dict)

    return [
        (
            "Panel / Group / Clan / Workflow Folding",
            [
                (
                    d(a.expand_or_layout),
                    "Expand fold / enter panel (❯)",
                ),
                (
                    d(a.hooks_or_collapse),
                    "Up: workflow/session/clan/tribe",
                ),
                (
                    d(a.hooks_or_collapse),
                    "Collapse selected panel",
                ),
                (
                    d(a.hooks_or_collapse),
                    "From collapsed panel: select last expanded panel",
                ),
                (
                    d(a.expand_all_folds),
                    "Toggle tribe fold by hint key",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Panel: collapse fold by hint key",
                ),
                (
                    key_sequence_display(
                        lm.prefix, sk(lm.keys, "collapse_fold_by_hint")
                    ),
                    "Row: tribe hints; panel: all",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Collapse selected workflow/session one level",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Then remaining sase agents in scope",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Then selected clan / group clans",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Compact expanded LLM Calls detail",
                ),
                (
                    d(a.collapse_panel_folds),
                    "Collapse panel folds ⇄ restore ▿",
                ),
                (
                    d(a.collapse_all_panel_folds),
                    "All-panel folds ⇄ restore ▿",
                ),
            ],
        ),
        (
            f"Metadata Fold Mode ({d(fm.prefix)})",
            [
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 3)
                    ),
                    "Set session level 1-2",
                ),
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 4)
                    ),
                    "Set clan/sase agent level 1-3",
                ),
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 5)
                    ),
                    "Set selected tribe level 1-4",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["cycle_level"]),
                    "Cycle panel fold level forward",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["toggle_all"]),
                    "Toggle all metadata folds",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["cycle_section"]),
                    "Cycle foldable section/member",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["toggle_section"]),
                    "Toggle foldable section/member",
                ),
                ("Roster entry", "Inherit MEMBERS then panel"),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'repeat_last'))}",
                    "Repeat last leader command",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_home")),
                    "Run agent (home)",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_from_cl")),
                    "Run agent from selected agent",
                ),
                (f"{d(lm.prefix)}{d(sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    key_sequence_display(
                        lm.prefix, sk(lm.keys, "collapse_fold_by_hint")
                    ),
                    "Collapse fold by hint",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_next_unread_done_agent'))}",
                    "Jump to next unread done agent",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_next_stopped_agent'))}",
                    "Jump to next stopped agent",
                ),
                *leader_full_history_help_rows(km, refresh_action="agents_refresh"),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'mark_all_unread_done_agents_read'))}",
                    "Mark all unread done agents read (repeat within 10s to undo)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'kill_and_edit'))}",
                    "Kill & edit (marked or focused)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'kill_and_edit_last'))}",
                    "Kill & edit last launched agent",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'revert_agent'))}",
                    "Revert agent + opened repos",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (^k older)",
                ),
                (
                    f"{d(lm.prefix)} {d(sk(lm.keys, 'prompt_history_edit_first'))}",
                    "Edit first prompt history entry",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history_cancelled'))}",
                    "History +cancelled (^k older)",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "open_prompt_stash")),
                    "Open stashed prompts panel",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'capture_agents_repro'))}",
                    "Capture repro bundle",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'toggle_agents_repro_checks'))}",
                    "Toggle repro auto-checks",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'models_panel'))}",
                    "Config > Launch",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'update_sase'))}",
                    "Update panel (SASE, providers)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'update_everything'))}",
                    "Update Everything (no confirmation)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_last_error'))}",
                    "Jump to last error log",
                ),
            ],
        ),
        (
            f"Bang Mode ({d(bm.prefix)})",
            [
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'run_cmd'))}",
                    "Run background command",
                ),
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'toggle_axe'))}",
                    "Start / stop service host (or select process)",
                ),
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'mark_pr_origin'))}",
                    "Mark PR origin",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (f"{d(cm.prefix)}{d(ag_copy['chat'])}", "Copy chat file path"),
                (f"{d(cm.prefix)}{d(ag_copy['name'])}", "Copy agent name"),
                (f"{d(cm.prefix)}{d(ag_copy['prompt'])}", "Copy agent prompt"),
                (
                    key_sequence_display(cm.prefix, ag_copy["reference"]),
                    "Copy @agent reference",
                ),
                (
                    f"{d(cm.prefix)}{d(ag_copy['tool_run_id'])}",
                    "Copy tool run id",
                ),
                (f"{d(cm.prefix)}{d(ag_copy['snapshot'])}", "Copy sase tui snapshot"),
            ],
        ),
        (
            "Artifact Files Modal",
            [
                (d(cm.prefix), "Open file Copy as… palette"),
                ("@ / l", "Copy @file ref / Markdown link"),
                ("c / y", "Copy Markdown contents"),
                ("p / P", "Copy stored / source path"),
                ("J", "Copy artifact-file metadata JSON"),
                ("Y", "Copy preferred stored/source path"),
                ("s", "Copy sase tui snapshot"),
            ],
        ),
        (
            "Wait Modal",
            [
                ("Ctrl-J / Ctrl-K", "Next / prev field, wraps"),
                ("Ctrl-N / Ctrl-P", "Next / prev completion row"),
                ("Tab", "Accept completion / next field"),
                ("Ctrl-R", "Run now"),
                ("Enter", "Apply wait spec"),
            ],
        ),
    ]
