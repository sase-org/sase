"""Artifact-pane keybinding sections for the Patches help tab."""

from ..._artifact_tab_actions import action_applies_to_contract
from ...artifact_tabs import PaneCapability, resolve_artifacts_subtabs
from ...keymaps import KeymapRegistry, key_display_name
from sase.core.artifact_relation_layout import (
    RelationRole,
    assign_relation_roles,
)
from .binding_common import Sections


def artifact_sections(km: KeymapRegistry) -> Sections:
    """Build artifact-pane help sections."""
    d = key_display_name
    a = km.app
    contracts = {
        descriptor.id: descriptor.contract for descriptor in resolve_artifacts_subtabs()
    }
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
        (
            f"{d(a.artifacts_load_more)} / {d(a.artifacts_unload)}",
            "Load more / unload one page",
        ),
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
                    f"{d(a.cycle_artifacts_split_reverse)} / {d(a.cycle_artifacts_split)}",
                    "Narrow / widen the list panel",
                ),
                (
                    d(a.pick_artifacts_project),
                    "Pick (seeded); rewrite project:",
                ),
                (
                    d(a.open_command_palette),
                    "Jump directly to any artifact pane",
                ),
            ],
        ),
        (
            "Patch Pane",
            [
                (
                    f"{d(a.patches_filters)} / {d(a.edit_query)}",
                    "Focus persistent Patch filter",
                ),
                ("+PROJECT / project:NAME", "Filter (seeds current)"),
                ("^NAME / ancestor:NAME", "Patch plus descendants"),
                ("~NAME / sibling:NAME", "Revert-family siblings"),
                ("&NAME / name:NAME", "Exact Patch name"),
                *_relation_rows(km, contracts.get("patches")),
                ("%w/%d/%y/%m/%s/%r", "Status macros"),
                ("!!! / !!", "Has / lacks error suffixes"),
                ("@@@ / !@", "Has / lacks running agents"),
                ("$$$ / !$ / *", "Process state / any special state"),
                ("#N QUERY / #N", "Save / delete slot N"),
                ("limit:N / limit:all", "Host cap; omitted/all unlimited"),
                ("Enter / Esc", "Commit / restore query and selection"),
                *artifact_list_navigation,
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
                (d(a.artifacts_copy_reference), "Copy @stitch: reference"),
                (
                    f"{d(a.edit_query)} / {d(a.stitches_filters)}",
                    "Focus persistent commit filter",
                ),
                ("project:NAME", "Single; omitted seeds current"),
                ("repo: / author:", "Filter repository / author substring"),
                ("since: / until:", "until:DAY includes the full day"),
                ("sidecar:true / false", "Include / exclude sidecars"),
                ("merges:hide / show / only", "Merge-commit visibility"),
                ("origin:stitch/auto/manual", "Commit origin"),
                ("type:manual/automatic/stitch/merge/patch", "Commit labels"),
                ("limit:N / limit:all", "Host cap; default page size; all unlimited"),
                (
                    "[P/N] / [P/N+]",
                    "Selected position / matched total; + is a lower bound",
                ),
                ("bare text", "Match subject words"),
                ("Enter / Esc", "Commit / restore; row stays"),
                *_relation_rows(km, contracts.get("stitches")),
                (
                    f"{d(a.stitches_toggle_sdd)} / {d(a.stitches_toggle_all_projects)}",
                    "Sidecars / project: off/on",
                ),
                (d(a.stitches_cycle_merges), "Cycle merge visibility"),
                (
                    f"{d(a.stitches_fetch)} / {d(a.refresh)}",
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
                ("limit:N / limit:all", "Host cap; default page size; all unlimited"),
                (
                    f"{d(a.beads_expand)} / {d(a.beads_collapse)}",
                    "Expand / collapse epic",
                ),
                *_relation_rows(km, contracts.get("beads")),
                (d(a.beads_cycle_status), "Cycle selected bead status"),
                (d(a.beads_edit), "Edit selected bead"),
                (d(a.beads_add_note), "Append a bead note"),
                (d(a.beads_create), "Create bead"),
                (d(a.beads_close), "Close / reopen bead"),
                (d(a.beads_snooze), "Snooze / re-snooze task bead"),
                (d(a.beads_launch_work), "Launch bead work"),
                (d(a.beads_open_bug), "Open linked issue"),
                (d(a.artifacts_copy_reference), "Copy @bead: reference"),
                (d(a.start_bead_issue_mode), "Issue actions"),
                ("b v/e/s/u/a/c", "View, edit, state, URL, attach, create"),
                ("% u", "Copy linked issue reference (copy mode)"),
                (d(a.beads_open_plan), "Go to linked plan"),
                (d(a.refresh), "Refresh beads"),
                *artifact_list_navigation,
            ],
        ),
        *_document_contract_sections(km, artifact_list_navigation),
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
                ("limit:N / limit:all", "Host cap; default page size; all unlimited"),
                (d(a.files_cycle_kind), "Cycle file kind"),
                (d(a.artifacts_copy_reference), "Copy @file: reference"),
                (d(a.files_copy_path), "Copy stored path"),
                (d(a.refresh), "Refresh artifact files"),
                *_relation_rows(km, contracts.get("files")),
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


def _document_contract_sections(
    km: KeymapRegistry,
    artifact_list_navigation: list[tuple[str, str]],
) -> Sections:
    """Build one help section per compiled document-provider contract."""

    d = key_display_name
    a = km.app
    sections: Sections = []
    for descriptor in resolve_artifacts_subtabs():
        contract = descriptor.contract
        if contract is None or not contract.is_document_provider():
            continue
        rows: list[tuple[str, str]] = [
            (f"{d(a.plans_next)} / {d(a.plans_prev)}", "Next / previous row"),
            (d(a.plans_view_selected), f"Open selected {contract.label.lower()}"),
            (
                f"{d(a.edit_query)} / {d(a.plans_filters)}",
                f"Open inline {contract.label.lower()} filter bar",
            ),
        ]
        if contract.has(PaneCapability.FILTER_SESSION):
            rows.extend(
                (
                    ("kind: / status: / tier:", "Filter kind, status, or tier"),
                    ("kind:<sidecar role>", "Filter archived document kind"),
                    (
                        "project: / since: / until:",
                        "Filter project or creation date",
                    ),
                    ("bare text", "Title/body/id/metadata (AND)"),
                    (
                        "limit:N / limit:all",
                        "Host cap; default page size; all unlimited",
                    ),
                )
            )
        if contract.has(PaneCapability.PLAN_APPROVE) and action_applies_to_contract(
            contract, "plans_approve"
        ):
            rows.append((d(a.plans_approve), "Approve selected proposal"))
        if contract.has(PaneCapability.PLAN_REJECT) and action_applies_to_contract(
            contract, "plans_reject"
        ):
            rows.append((d(a.plans_reject), "Reject selected proposal"))
        if contract.has(PaneCapability.PLAN_OPEN_BEAD) and action_applies_to_contract(
            contract, "plans_open_bead"
        ):
            rows.append((d(a.plans_open_bead), "Go to linked bead"))
        rows.extend(_relation_rows(km, contract))
        rows.append(
            (d(a.artifacts_copy_reference), f"Copy {contract.label.lower()} reference")
        )
        rows.append((d(a.refresh), f"Refresh {contract.label.lower()}s"))
        rows.extend(artifact_list_navigation)
        title = (
            f"{contract.label} Pane"
            if contract.is_plan_adapter()
            else f"{contract.label} Documents"
        )
        sections.append((title, rows))
    if not sections:
        sections.append(
            (
                "Document Panes",
                [
                    (
                        f"{d(a.plans_next)} / {d(a.plans_prev)}",
                        "Next / previous row",
                    ),
                    ("kind: / status: / tier:", "Filter kind, status, or tier"),
                    (
                        "project: / since: / until:",
                        "Filter project or creation date",
                    ),
                    ("bare text", "Title/body/id/metadata (AND)"),
                    *artifact_list_navigation,
                ],
            )
        )
    return sections


def _relation_rows(
    km: KeymapRegistry, contract: object | None
) -> list[tuple[str, str]]:
    """Return help rows for relation key modes declared by *contract*."""
    if contract is None or not contract.has(PaneCapability.RELATIONS):  # type: ignore[attr-defined]
        return []
    roles = assign_relation_roles(contract.relations)  # type: ignore[attr-defined]
    action_for_role = {
        RelationRole.ANCESTOR: "start_ancestor_mode",
        RelationRole.DESCENDANT: "start_child_mode",
        RelationRole.FAMILY: "start_sibling_mode",
    }
    rows: list[tuple[str, str]] = []
    for relation in contract.relations:  # type: ignore[attr-defined]
        role = roles.get(relation.name)
        if role is None:
            continue
        action = action_for_role.get(role)
        if action is None:
            continue
        rows.append(
            (
                key_display_name(getattr(km.app, action)),
                _truncate_relation_description(f"Navigate {relation.label.lower()}"),
            )
        )
    rows.append(
        (
            key_display_name(km.app.toggle_relation_panel),
            "Collapse / expand relations",
        )
    )
    return rows


def _truncate_relation_description(description: str) -> str:
    if len(description) <= 32:
        return description
    return f"{description[:31]}…"
