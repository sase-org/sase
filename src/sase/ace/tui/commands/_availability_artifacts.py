"""Artifacts-tab applicability predicates for command palette entries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.commands.types import CommandContext, CommandSpec

if TYPE_CHECKING:
    from sase.ace.tui.artifact_tabs import PaneCapability


# Statuses used by footer for editable PR gating.
_EDITABLE_STATUSES: frozenset[str] = frozenset({"WIP", "Draft", "Ready", "Mailed"})

# Patch actions that require a selected PR with a PR number.
_REQUIRES_CL_NUMBER: frozenset[str] = frozenset(
    {
        "app.show_diff",
        "app.reword",
        "app.add_tag",
        "app.view_files",
        "app.mark_pr_origin",
    }
)

# Patch actions that require an editable status (WIP/Draft/Ready/Mailed).
_REQUIRES_EDITABLE_STATUS: frozenset[str] = frozenset(
    {
        "app.reword",
        "app.add_tag",
        "app.rebase",
        "app.sync",
    }
)

# Patch actions that don't apply to Submitted / Reverted Patches.
_REQUIRES_NON_TERMINAL_STATUS: frozenset[str] = frozenset(
    {
        "app.start_rewind",
        "app.rename_cl",
    }
)

_NON_PRS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.cycle_artifacts_subtab",
        "app.cycle_artifacts_subtab_reverse",
        "app.cycle_artifacts_split",
        "app.cycle_artifacts_split_reverse",
        "app.pick_artifacts_project",
        "app.files_next_version",
        "app.files_prev_version",
        "app.next_tab",
        "app.prev_tab",
        "app.quit",
        "app.stop_axe_and_quit",
        "app.start_custom_agent",
        "app.start_agent_home",
        "app.start_last_vcs_xprompt_in_editor",
        "app.restore_prompt_stash",
        "app.show_notifications",
        "app.show_help",
        "app.open_config_center",
        "app.open_command_palette",
        "app.dismiss_toasts",
        "app.refresh",
        "app.artifacts_copy_reference",
        "app.artifacts_link_marked",
        "app.artifacts_load_more",
        "app.artifacts_unload",
        "app.start_saved_query_mode",
        "app.open_saved_query_picker",
        "projects",
        "logs",
        "tasks",
    }
)

_PLANS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.plans_next",
        "app.plans_prev",
        "app.plans_view_selected",
        "app.plans_filters",
        "app.plans_approve",
        "app.plans_reject",
        "app.plans_open_bead",
    }
)

_BEADS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.beads_next",
        "app.beads_prev",
        "app.beads_view_selected",
        "app.beads_filters",
        "app.beads_expand",
        "app.beads_collapse",
        "app.beads_cycle_status",
        "app.beads_edit",
        "app.beads_add_note",
        "app.beads_create",
        "app.beads_close",
        "app.beads_snooze",
        "app.beads_launch_work",
        "app.beads_open_bug",
        "app.start_bead_issue_mode",
        "app.beads_open_plan",
    }
)

_AGENTS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.agents_next",
        "app.agents_prev",
        "app.agents_revive",
    }
)

_FILES_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.files_next",
        "app.files_prev",
        "app.files_view_selected",
        "app.files_open_viewer",
        "app.files_open_external",
        "app.files_open_agent",
        "app.files_filters",
        "app.files_cycle_kind",
        "app.files_copy_path",
    }
)

_SAVED_QUERY_COMMANDS: frozenset[str] = frozenset(
    {
        "app.start_saved_query_mode",
        "app.open_saved_query_picker",
    }
)

_STITCHES_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.stitches_next",
        "app.stitches_prev",
        "app.stitches_view_selected",
        "app.stitches_filters",
        "app.stitches_toggle_sdd",
        "app.stitches_cycle_merges",
        "app.stitches_toggle_all_projects",
        "app.stitches_fetch",
    }
)


def _get_base_status(status: str) -> str:
    """Lazy-import wrapper for ``patch.get_base_status``."""
    from sase.ace.patch import get_base_status

    return get_base_status(status)


def _artifacts_copy_group(subtab: str) -> str:
    from sase.ace.tui.artifact_tabs import copy_group_for_artifacts_pane

    return copy_group_for_artifacts_pane(subtab)


def _artifacts_subtab_has_capability(
    subtab: str,
    capability: PaneCapability,
) -> bool:
    from sase.ace.tui.artifact_tabs import (
        LEGACY_ARTIFACTS_SUBTABS,
        artifacts_pane_contract,
    )

    pane_id = LEGACY_ARTIFACTS_SUBTABS.get(subtab, subtab)
    contract = artifacts_pane_contract(pane_id)
    return contract is not None and contract.has(capability)


def artifacts_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    """Return whether an Artifacts-tab command is runnable."""
    if spec.id.startswith("copy.artifacts_"):
        copy_group = _artifacts_copy_group(ctx.artifacts_subtab)
        if not spec.id.startswith(f"copy.{copy_group}."):
            return False
        if ctx.artifact_selection_present is False:
            return False
        if ctx.artifact_available_targets is not None:
            return spec.id.rsplit(".", 1)[-1] in ctx.artifact_available_targets
        return True
    if spec.id in _SAVED_QUERY_COMMANDS or spec.id.startswith("saved_query."):
        from sase.ace.tui.artifact_tabs import PaneCapability

        return _artifacts_subtab_has_capability(
            ctx.artifacts_subtab,
            PaneCapability.SAVED_QUERIES,
        )
    if spec.id == "app.edit_query":
        from sase.ace.tui.artifact_tabs import (
            PaneCapability,
            artifacts_pane_contract,
        )

        if ctx.artifacts_subtab in {"patches", "stitches", "beads", "files"}:
            return True
        contract = artifacts_pane_contract(ctx.artifacts_subtab)
        if contract is not None:
            return contract.has(PaneCapability.FILTER_SESSION)
        from sase.ace.tui.artifact_tabs import is_document_artifacts_pane

        return is_document_artifacts_pane(ctx.artifacts_subtab)
    if spec.id in {
        "app.cycle_grouping_mode",
        "app.cycle_grouping_mode_reverse",
    }:
        from sase.ace.tui.artifact_tabs import (
            PaneCapability,
            artifacts_pane_contract,
        )

        contract = artifacts_pane_contract(ctx.artifacts_subtab)
        return contract is not None and contract.has(PaneCapability.GROUPING)
    if spec.id == "app.patches_filters":
        return ctx.artifacts_subtab == "patches"
    if spec.id in {"app.cycle_files_subtab", "app.cycle_files_subtab_reverse"}:
        return False
    if spec.id in _STITCHES_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "stitches"
    if spec.id in _PLANS_ARTIFACT_COMMANDS:
        from sase.ace.tui.artifact_tabs import (
            PaneCapability,
            artifacts_pane_contract,
        )

        contract = artifacts_pane_contract(ctx.artifacts_subtab)
        if contract is None:
            from sase.ace.tui.artifact_tabs import is_document_artifacts_pane

            if not is_document_artifacts_pane(ctx.artifacts_subtab):
                return False
            if spec.id in {
                "app.plans_approve",
                "app.plans_reject",
                "app.plans_open_bead",
            }:
                return ctx.artifacts_subtab in {"ref:plan", "plans"}
            return True
        if not contract.is_document_provider():
            return False
        if spec.id == "app.plans_approve":
            return contract.has(PaneCapability.PLAN_APPROVE)
        if spec.id == "app.plans_reject":
            return contract.has(PaneCapability.PLAN_REJECT)
        if spec.id == "app.plans_open_bead":
            return contract.has(PaneCapability.PLAN_OPEN_BEAD)
        return True
    if spec.id in _BEADS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "beads"
    if spec.id in _AGENTS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "agents"
    if spec.id.startswith("bead_issue."):
        return ctx.artifacts_subtab == "beads"
    if spec.id in _FILES_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "files"
    if spec.id == "app.artifacts_link_marked":
        return (
            ctx.artifacts_subtab != "patches"
            and ctx.artifact_selection_present is not False
        )
    if ctx.artifacts_subtab != "patches":
        return spec.id.startswith("artifacts.") or spec.id in _NON_PRS_ARTIFACT_COMMANDS
    if spec.id == "app.pick_artifacts_project":
        return False
    cs = ctx.patch
    # Patch-required commands need a selected Patch.
    if spec.id in _REQUIRES_CL_NUMBER and (cs is None or cs.pr_url is None):
        return False

    # Mail requires Ready status.
    if spec.id == "app.mail":
        if cs is None or cs.pr_url is None:
            return False
        return _get_base_status(cs.status) == "Ready"

    # Editable-status gates (reword, add_tag, rebase, sync).
    if spec.id in _REQUIRES_EDITABLE_STATUS:
        if cs is None:
            return False
        # sync also needs a PR number? Footer requires editable only.
        if spec.id in _REQUIRES_CL_NUMBER and cs.pr_url is None:
            return False
        return _get_base_status(cs.status) in _EDITABLE_STATUSES

    # Non-terminal-status gates.
    if spec.id in _REQUIRES_NON_TERMINAL_STATUS:
        if cs is None:
            return False
        return _get_base_status(cs.status) not in {"Submitted", "Reverted"}

    # accept_proposal needs a proposed entry.
    if spec.id == "app.accept_proposal":
        if cs is None or not cs.commits:
            return False
        return any(getattr(e, "is_proposed", False) for e in cs.commits)

    # bulk_change_status / clear_marks only when marks exist.
    if spec.id in {"app.bulk_change_status", "app.clear_marks"}:
        return ctx.mark_count > 0

    # change_status / run_workflow / edit_spec / toggle_mark / rename_cl
    # / edit_hooks all need a selected Patch row but no further gating in
    # Phase 1 - the action methods already no-op when invalid.
    if spec.id in {
        "app.change_status",
        "app.run_workflow",
        "app.edit_spec",
        "app.toggle_mark",
        "app.rename_cl",
        "app.edit_hooks",
        "app.start_agent_from_patch",
    }:
        return cs is not None

    # Copy-mode commands scoped to patches need a Patch row.
    if spec.id.startswith("copy.patches."):
        if cs is None:
            return False
        if (
            spec.id in {"copy.patches.pr_number", "copy.patches.cl_number"}
            and not cs.pr_url
        ):
            return False
        if spec.id == "copy.patches.link" and not cs.pr_url:
            return False
        if spec.id == "copy.patches.bug" and not getattr(cs, "bug", None):
            return False
        return True

    # Leader commands scoped to Patch only.
    if spec.id in {
        "leader.run_cmd",
        "leader.kill_mentors",
        "leader.review_mentors",
        "leader.clear_comments",
        "leader.agent_run_log",
    }:
        return cs is not None

    # Default: visible.
    return True
