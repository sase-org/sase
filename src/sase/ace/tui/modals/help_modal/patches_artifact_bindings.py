"""Artifact-pane keybinding sections for the Patches help tab."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import Sections


def artifact_sections(km: KeymapRegistry) -> Sections:
    """Build artifact-pane help sections."""
    d = key_display_name
    a = km.app
    artifact_list_navigation = [
        (
            f"{d(a.toggle_mark)} / {d(a.clear_marks)}",
            "Mark current / clear pane marks",
        ),
        (
            f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
            "Select first / last entry",
        ),
        (
            f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
            "Scroll right detail down / up",
        ),
        (
            f"{d(a.scroll_prompt_down)} / {d(a.scroll_prompt_up)}",
            "Move down / up 10 entries",
        ),
        (d(a.jump_to_entry), "Hint jump (' first / back)"),
    ]

    return [
        (
            "Artifact Views",
            [
                (
                    "1 / 2 / 3 / 4",
                    "Jump fixed top-level views",
                ),
                (
                    f"{d(a.cycle_artifacts_subtab_reverse)} / {d(a.cycle_artifacts_subtab)}",
                    "Cycle top-level views",
                ),
                (
                    d(a.pick_artifacts_project),
                    "Pick; Stitches rewrites project:",
                ),
                (
                    d(a.open_command_palette),
                    "Jump directly to any artifact pane",
                ),
            ],
        ),
        (
            "Stitch Pane",
            [
                (
                    f"{d(a.stitches_next)} / {d(a.stitches_prev)}",
                    "Move to next / previous commit",
                ),
                (
                    d(a.stitches_view_selected),
                    "Open full commit message and diff",
                ),
                ("p (commit view)", "Toggle attached local plan / commit"),
                (d(a.stitches_copy_sha), "Copy full commit SHA"),
                (
                    f"{d(a.edit_query)} / {d(a.stitches_filters)}",
                    "Focus persistent commit filter",
                ),
                ("project:NAME", "Single; omitted = all projects"),
                ("repo: / author:", "Filter repository / author substring"),
                ("since: / until:", "until:DAY includes the full day"),
                ("sidecar:true / false", "Include / exclude sidecars"),
                ("merges:hide / show / only", "Merge-commit visibility"),
                ("origin:stitch/auto/manual", "Commit origin"),
                ("limit:N / limit:all", "N caps; omitted/all unlimited"),
                (
                    "[P/N] / [P/N+]",
                    "Selected position / matched total; + is a lower bound",
                ),
                ("bare text", "Match subject words"),
                ("Enter / Esc", "Commit / restore; row stays"),
                (
                    f"{d(a.stitches_toggle_sdd)} / {d(a.stitches_toggle_all_projects)}",
                    "Sidecars / project: off/on",
                ),
                (d(a.stitches_cycle_merges), "Cycle merge visibility"),
                (
                    f"{d(a.stitches_fetch)} / {d(a.stitches_refresh)}",
                    "Fetch remote refs / refresh from local refs",
                ),
                *artifact_list_navigation,
            ],
        ),
        (
            "Bead Pane",
            [
                (
                    f"{d(a.beads_next)} / {d(a.beads_prev)}",
                    "Next / previous bead",
                ),
                (d(a.beads_view_selected), "Open selected bead"),
                (d(a.beads_filters), "Open bead filter bar"),
                (
                    "type: / tier: / status:",
                    "Filter bead kind or state",
                ),
                ("size: / project: / has:", "Filter scope or metadata"),
                ("bug: / label:", "Filter linked issue state or labels"),
                (
                    "assignee: / owner: / model:",
                    "Filter people or runtime",
                ),
                ("since: / until: / bare text", "Filter recency or words"),
                (
                    f"{d(a.beads_expand)} / {d(a.beads_collapse)}",
                    "Expand / collapse epic",
                ),
                (d(a.beads_cycle_status), "Cycle selected bead status"),
                (d(a.beads_edit), "Edit selected bead"),
                (d(a.beads_add_note), "Append a bead note"),
                (d(a.beads_create), "Create task bead"),
                (d(a.beads_close), "Close / reopen bead"),
                (d(a.beads_snooze), "Snooze / re-snooze task bead"),
                (d(a.beads_launch_work), "Launch bead work"),
                (d(a.beads_open_bug), "Open linked issue"),
                (d(a.beads_copy_bug), "Copy linked issue ref"),
                (d(a.start_bead_issue_mode), "Issue actions"),
                ("b v/e/s/u/a/c", "View, edit, state, URL, attach, create"),
                (d(a.beads_open_plan), "Go to linked plan"),
                (d(a.beads_refresh), "Refresh beads"),
                *artifact_list_navigation,
            ],
        ),
        (
            "Document Panes",
            [
                (f"{d(a.plans_next)} / {d(a.plans_prev)}", "Next / previous row"),
                (d(a.plans_view_selected), "Open selected document"),
                (
                    f"{d(a.edit_query)} / {d(a.plans_filters)}",
                    "Open inline document filter bar",
                ),
                ("kind: / status: / tier:", "Filter kind, status, or tier"),
                ("kind:<sidecar role>", "Filter archived document kind"),
                ("project: / since: / until:", "Filter project or creation date"),
                ("bare text", "Title/body/id/metadata (AND)"),
                (d(a.plans_approve), "Approve selected proposal"),
                (d(a.plans_reject), "Reject selected proposal"),
                (d(a.plans_open_bead), "Go to linked bead"),
                (d(a.plans_refresh), "Refresh documents"),
                *artifact_list_navigation,
            ],
        ),
        (
            "File Pane",
            [
                (f"{d(a.files_next)} / {d(a.files_prev)}", "Next / previous row"),
                (
                    f"{d(a.files_prev_version)} / {d(a.files_next_version)}",
                    "Previous / next version",
                ),
                (d(a.files_view_selected), "View selected artifact file"),
                (d(a.files_open_viewer), "Open in rich viewer"),
                (d(a.files_open_external), "Open externally"),
                (d(a.files_open_agent), "Open producing agent"),
                (d(a.files_filters), "Open artifact-file filters"),
                (d(a.files_cycle_kind), "Cycle file kind"),
                (d(a.files_copy_reference), "Copy artifact-file reference"),
                (d(a.files_copy_path), "Copy stored path"),
                (d(a.files_refresh), "Refresh artifact files"),
                *artifact_list_navigation,
            ],
        ),
        (
            "Preview Reader",
            [
                ("j/k · Ctrl+D/U · g/G", "Line / page / edge scrolling"),
                ("y / Y", "Copy contents / source path"),
                ("%", "Open active pane Copy as… palette"),
                ("R", "Toggle Markdown rendered/source view"),
                ("p", "XPrompt properties view"),
                ("/ · n/N", "Search source · next/previous match"),
                ("o / Z", "Open editor / rich viewer"),
                ("Esc / q", "Clear search then close / always close"),
            ],
        ),
    ]
