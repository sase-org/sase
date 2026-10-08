"""Navigation and action keybinding sections for the Agents help tab."""

from ...keymaps import KeymapRegistry, key_display_name, leader_key_display
from ...models.agent_live_query_engine import agents_unified_query_enabled
from ...widgets.decks.spec import active_deck_cycle
from ...widgets.decks.titles import DECK_PICKER_KEYS
from .binding_common import Sections, key_sequence_display, sk


def main_sections(km: KeymapRegistry) -> Sections:
    """Build the Navigation, action, query, and search help sections."""
    d = key_display_name
    a = km.app
    bm = km.bang_mode

    link_follow_row = _link_follow_row(d(a.follow_artifact_link))
    unified_query = agents_unified_query_enabled()
    filter_query_keys = (
        f"{d(a.edit_query)} / {d(a.agents_filters)}"
        if unified_query
        else d(a.edit_query)
    )
    deck_capitals = "/".join(
        DECK_PICKER_KEYS[deck].upper() for deck in active_deck_cycle()
    )
    pick_display = d(a.pick_deck)
    opener_capital = None
    if (
        len(pick_display) == 1
        and pick_display.isalpha()
        and pick_display.upper() != pick_display.lower()
    ):
        opener_capital = pick_display.upper()
    if pick_display and opener_capital is not None:
        pick_deck_other_rows = [
            (
                f"{pick_display} {opener_capital}/{deck_capitals}",
                "Show last deck or a deck in the other panel (decks)",
            )
        ]
    elif pick_display:
        pick_deck_other_rows = [
            (f"{pick_display} {deck_capitals}", "Show deck in other panel (decks)")
        ]
    else:
        pick_deck_other_rows = []

    return [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_patch)} / {d(a.prev_patch)}",
                    "Move row / selected panel",
                ),
                (
                    f"{d(a.next_patch)} / {d(a.prev_patch)}",
                    "Lone row: cycle whole panels",
                ),
                (
                    f"{d(a.focus_next_agent_panel)} / {d(a.focus_prev_agent_panel)}",
                    "Jump into next / prev open panel",
                ),
                (d(a.jump_to_entry), "Jump entry/head (' first/back stack)"),
                (
                    f"{d(a.jump_to_entry_fast)} / {d(a.jump_to_entry_forward)}",
                    "Jump stack back / forward",
                ),
                (d(a.jump_to_all_entries), "Jump to entry (all tabs, ` back)"),
                (d(a.jump_to_node), 'Find any node, even hidden ("" back)'),
                ("0-9", "Jump numbered member/neighbor"),
                ("Esc", "Enter selected panel / cancel member jump"),
                (
                    f"{d(a.next_deck_card)} / {d(a.prev_deck_card)}",
                    "Cycle deck card (decks)",
                ),
                (
                    f"{d(a.prev_card_block)} / {d(a.next_card_block)}",
                    "Older / newer card block",
                ),
                (
                    d(a.cycle_deck_view),
                    "Cycle deck view (auto: palette)",
                ),
                (
                    d(a.pick_deck),
                    "Pick a deck; press it again for the last deck",
                ),
                *pick_deck_other_rows,
                (
                    f"{d(a.next_deck)} / {d(a.prev_deck)}",
                    "Cycle deck (decks)",
                ),
                (
                    f"{d(a.toggle_deck_split_below)} / {d(a.toggle_deck_split_right)}",
                    "`\\` / `|` erase a full-span divider, else draw one through the focused pane, else turn a three-pane layout (decks)",
                ),
                (
                    f"{d(a.toggle_deck_focus)} / {d(a.toggle_deck_focus_reverse)}",
                    "Focus next / previous deck panel (decks)",
                ),
                (
                    f"{d(a.swap_deck_panel_next)} / {d(a.swap_deck_panel_prev)}",
                    "Swap focused panel with next / previous (decks)",
                ),
                (
                    f"{d(a.close_deck_panel)}",
                    "Close focused deck panel (decks)",
                ),
                (
                    f"{d(a.turn_deck_layout)}",
                    "Turn deck layout (decks)",
                ),
                (
                    f"{d(a.shrink_deck_panel)} / {d(a.grow_deck_panel)}",
                    "Shrink/grow deck panel (decks)",
                ),
                (
                    f"{d(a.toggle_node_panel)}",
                    "Toggle node rail",
                ),
                *(
                    [
                        (
                            f"{d(a.prev_agents_tab)} / {d(a.next_agents_tab)}",
                            "Prev / next agent tab",
                        )
                    ]
                    if (d(a.prev_agents_tab) and d(a.next_agents_tab))
                    else []
                ),
                *(
                    [(d(a.pick_agents_tab), "Go to agent tab…")]
                    if d(a.pick_agents_tab)
                    else []
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Scroll detail top / bottom; deck follows",
                ),
                (
                    f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
                    "Scroll focused deck down / up",
                ),
                *link_follow_row,
            ],
        ),
        (
            "Agent Actions",
            [
                (d(a.act_on_agent), "Review gate / go to Patch"),
                (d(a.start_custom_agent), "Run custom agent"),
                (
                    d(a.start_agent_from_patch),
                    "Repeat last launched VCS macro",
                ),
                (d(a.start_last_vcs_macro_in_editor), "Edit last VCS macro"),
                (d(a.restore_prompt_stash), "Restore stashed prompt"),
                (d(a.agents_retry), "Retry local or remote agent"),
                (
                    d(a.accept_proposal),
                    "Toggle %auto / answer local or remote attention",
                ),
                (d(a.rename_cl), "Name agent"),
                (d(a.edit_hooks), "Fork local or remote agent"),
                (
                    key_sequence_display(bm.prefix, sk(bm.keys, "start_rewind")),
                    "Revive dismissed (^k loads more)",
                ),
                (
                    d(a.add_tag),
                    "Start wait; @tribe binds next",
                ),
                (
                    d(a.reword),
                    "Edit wait deps/beads/time; keep name / run now",
                ),
                (d(a.save_marked_agents), "Save/dismiss marked agents"),
                (d(a.kill_agent), "Stop/clean row/panel/group/clan/marks"),
                (d(a.toggle_mark), "Mark/unmark current agent or focused group"),
                (d(a.toggle_agent_unread), "Toggle unread marker"),
                (d(a.clear_marks), "Clear all agent marks"),
                (d(a.open_agent_cleanup_panel), "Open cleanup panel"),
                (d(a.edit_spec), "Edit chat(s) / open remote content"),
                (d(a.edit_panel), "Edit focused deck in editor"),
                (d(a.view_files), "Hint files/tool calls/commits/clans"),
                (d(a.view_agent_metadata), "Page metadata, prompts & reply"),
                ("p (commit view)", "Toggle attached local plan / commit"),
                (d(a.zoom_panel), "Zoom deck (hides nodes)"),
                (
                    d(a.isolate_panels),
                    "Only panel ⇄ restore panels",
                ),
                (d(a.open_artifact_files), "Artifact files (or marked set)"),
                (d(a.toggle_attempt_view), "Toggle attempt history view"),
                (d(a.toggle_agent_header), "Expand / collapse agent header"),
                (d(a.toggle_agent_jump_panel), "Expand / collapse jump panel"),
                (d(a.toggle_hide_non_run_agents), "Show/hide non-run agents"),
                (d(a.start_tmux_mode), "Tmux chooser (mark many)"),
                (d(a.edit_agent_tribe), "Edit tribe (or marked set)"),
                (d(a.open_tmux), "Tmux in primary workspace"),
            ],
        ),
        (
            "Remote Machines",
            [
                (d(a.connect_agent_machine), "Show remote machine status"),
                (d(a.setup_agent_machine), "Connect a machine"),
                (d(a.agents_retry), "Retry selected remote row on its owner"),
                (d(a.edit_hooks), "Fork selected remote row on its owner"),
                (d(a.kill_agent), "Stop selected remote row on its owner"),
                (d(a.edit_spec), "Open remote chat/output/diff content"),
                (
                    d(a.accept_proposal),
                    "Answer remote question or approve remote gate",
                ),
                (d(a.check_dispatch_launch_outcome), "Check dispatch launch outcome"),
            ],
        ),
        (
            "Agent Query",
            [
                (filter_query_keys, "Filter agents by query"),
            ],
        ),
        (
            "Deck Search",
            [
                (
                    leader_key_display(km, "search_forward"),
                    "Start deck search forward",
                ),
                (d(a.search_reverse), "Reverse active search order"),
                ("n / N", "Next / previous match"),
                ("Enter / Esc / Ctrl+C", "Accept / cancel search query"),
                ("Esc / q", "Close committed search"),
                ("y / Y", "Yank selection/match / whole line"),
            ],
        ),
    ]


def _link_follow_row(key: str) -> list[tuple[str, str]]:
    return [
        (f"{key}{key} / {key}1-9 / {key}0", "Follow link / open links panel"),
        ("⊘ / ↻", "Panel: dangling / needs reveal"),
    ]
