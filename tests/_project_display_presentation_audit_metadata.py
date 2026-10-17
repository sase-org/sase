"""Project-metadata worker-boundary and pure-render audits."""

from __future__ import annotations

import ast

import pytest

from _project_display_presentation_audit_helpers import (
    call_name,
    enclosing_function,
    parent_map,
    parse_source,
)

pytestmark = pytest.mark.contract

_PROJECT_METADATA_FLOW_FILES = (
    "src/sase/ace/tui/actions/_state_init_late.py",
    "src/sase/stats/loader.py",
    "src/sase/ace/tui/modals/statistics_pane_rendering.py",
    "src/sase/ace/tui/modals/statistics_pane_projects.py",
    "src/sase/ace/tui/modals/statistics_pane_views.py",
    "src/sase/ace/tui/modals/project_discovery.py",
    "src/sase/ace/tui/modals/project_select_modal.py",
    "src/sase/ace/tui/modals/prompt_stash_row.py",
    "src/sase/ace/tui/modals/_prompt_stash_preview.py",
    "src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash_store.py",
    "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
    "src/sase/ace/tui/actions/agents/_archive_controller_build.py",
    "src/sase/ace/tui/actions/agents/_loading_compute.py",
    "src/sase/ace/tui/models/agent_loader.py",
    "src/sase/ace/dismissed_agents_bundles.py",
    "src/sase/ace/tui/actions/event_refresh/_auto_refresh_surfaces.py",
    "src/sase/agents/_wait_live_rows.py",
    "src/sase/axe/lumberjack.py",
)
_PROJECT_METADATA_LOADER_NAMES = {
    "list_project_records",
    "load_project_display_snapshot",
    "load_project_ref_display_snapshot",
    "refresh_project_display_snapshot",
}
_ALLOWED_METADATA_LOADERS = {
    (
        "src/sase/ace/tui/actions/_state_init_late.py",
        "_project_commits_startup_display_name",
        "load_project_ref_display_snapshot",
    ): "Commits projects one merged scope before mount so first paint and collection agree.",
    (
        "src/sase/stats/loader.py",
        "load_statistics_view",
        "load_project_display_snapshot",
    ): "Statistics loads its display snapshot in the threaded view loader.",
    (
        "src/sase/ace/tui/modals/project_discovery.py",
        "load_launchable_project_snapshot",
        "list_project_records",
    ): "Project picker discovery runs inside its off-thread loader.",
    (
        "src/sase/ace/tui/modals/project_discovery.py",
        "is_launchable_project",
        "list_project_records",
    ): "Explicit launch-target validation is a resolution boundary, not rendering.",
    (
        "src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash_store.py",
        "_read_prompt_stash_presentation_snapshot",
        "load_project_display_snapshot",
    ): "Prompt-stash entries and labels are batch-loaded together on a worker.",
    (
        "src/sase/ace/tui/actions/agents/_notification_launch_approval.py",
        "_read_launch_approval_task_metadata",
        "load_project_display_snapshot",
    ): "Launch approval resolves its task label inside the tracked task worker.",
    (
        "src/sase/ace/tui/actions/agents/_archive_controller_build.py",
        "_load_display_snapshot",
        "load_project_display_snapshot",
    ): "Archive corpus worker warms project labels off-thread for project banners.",
    (
        "src/sase/ace/tui/actions/agents/_loading_compute.py",
        "compute_apply_loaded_agents",
        "refresh_project_display_snapshot",
    ): "Agent-load worker revalidates cross-process labels before attaching names.",
    (
        "src/sase/ace/tui/models/agent_loader.py",
        "_filter_and_cap_windowed_agents_live",
        "refresh_project_display_snapshot",
    ): "Windowed live-query path revalidates before attaching names.",
    (
        "src/sase/ace/dismissed_agents_bundles.py",
        "_load_bundle_paths",
        "refresh_project_display_snapshot",
    ): "Dismissed-bundle loads revalidate before attaching names.",
    (
        "src/sase/ace/tui/actions/event_refresh/_auto_refresh_surfaces.py",
        "_run_auto_refresh_surfaces",
        "refresh_project_display_snapshot",
    ): "Auto-refresh tick revalidates off-thread and dirties label surfaces.",
    (
        "src/sase/agents/_wait_live_rows.py",
        "build_wait_live_rows",
        "refresh_project_display_snapshot",
    ): "Wait live rows revalidate once per poll iteration.",
    (
        "src/sase/axe/lumberjack.py",
        "_run_tick",
        "refresh_project_display_snapshot",
    ): "Lumberjack revalidates once per cycle, not per log line.",
}


def _metadata_loadercall_name(call: ast.Call) -> str | None:
    """Return the tracked loader a call invokes, including via ``to_thread``."""
    name = call_name(call)
    if name in _PROJECT_METADATA_LOADER_NAMES:
        return name
    if name == "to_thread" and call.args:
        target = call.args[0]
        if isinstance(target, ast.Name) and target.id in _PROJECT_METADATA_LOADER_NAMES:
            return target.id
        if (
            isinstance(target, ast.Attribute)
            and target.attr in _PROJECT_METADATA_LOADER_NAMES
        ):
            return target.attr
    return None


def test_project_metadata_loaders_stay_at_reviewed_tui_worker_boundaries() -> None:
    """Audited render/navigation flows cannot grow lifecycle metadata I/O."""
    actual: set[tuple[str, str, str]] = set()
    for path in _PROJECT_METADATA_FLOW_FILES:
        tree = parse_source(path)
        parents = parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = _metadata_loadercall_name(call)
            if name is None:
                continue
            actual.add((path, enclosing_function(call, parents), name))

    assert actual == set(_ALLOWED_METADATA_LOADERS), (
        "project metadata loader sites changed:\n"
        f"unexpected={sorted(actual - set(_ALLOWED_METADATA_LOADERS))}\n"
        f"missing={sorted(set(_ALLOWED_METADATA_LOADERS) - actual)}"
    )
    assert all(reason.strip() for reason in _ALLOWED_METADATA_LOADERS.values())


_PURE_TUI_RENDER_FILES = (
    "src/sase/ace/tui/modals/statistics_pane_rendering.py",
    "src/sase/ace/tui/modals/statistics_pane_projects.py",
    "src/sase/ace/tui/modals/statistics_pane_views.py",
    "src/sase/ace/tui/modals/prompt_stash_row.py",
    "src/sase/ace/tui/modals/_prompt_stash_preview.py",
    "src/sase/ace/tui/widgets/_agent_list_render_agent.py",
    "src/sase/ace/tui/widgets/prompt_panel/_agent_display_clan_identity.py",
)
_FORBIDDEN_RENDER_CALLS = {
    "Popen",
    "exists",
    "glob",
    "is_dir",
    "is_file",
    "list_project_records",
    "load_project_display_snapshot",
    "lstat",
    "open",
    "read_bytes",
    "read_text",
    "refresh_project_display_snapshot",
    "rglob",
    "run",
    "stat",
    "system",
}


def test_audited_tui_render_helpers_are_free_of_io_and_subprocess_calls() -> None:
    violations: list[str] = []
    for path in _PURE_TUI_RENDER_FILES:
        tree = parse_source(path)
        parents = parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = call_name(call)
            if name in _FORBIDDEN_RENDER_CALLS:
                violations.append(
                    f"{path}:{call.lineno} {enclosing_function(call, parents)} calls {name}"
                )
    assert not violations, "\n".join(violations)
