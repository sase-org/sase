"""Planning and confirmation rendering for comprehensive updates."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUpdatePlan,
)
from sase.agents_sync.models import ProjectSyncStatus
from sase.ace.tui.agents_sync_format import (
    agents_sync_status_detail,
    agents_sync_status_needs_attention,
)
from sase.dev_update.models import DevUpdatePlan
from sase.uv_tool.commands import build_upgrade_all
from sase.version._git import GitUpstreamStatus, git_fetch_upstream_args

from .plugin_action_confirm_modal import (
    PluginActionComponentState,
    PluginActionPreviewComponent,
    PluginActionPreviewSection,
)
from .plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    DroppedProviderCandidate,
    error_text,
)
from .plugins_browser_dev_update import dev_update_preview_summary, short_root


def plan_captured_providers(
    captured_names: tuple[str, ...] | None,
    statuses: Sequence[AgentCliStatus],
    *,
    offline: bool,
    source_error: str | None = None,
) -> tuple[
    AgentCliUpdatePlan | None,
    tuple[DroppedProviderCandidate, ...],
    str | None,
]:
    """Intersect captured identities with live status; never broaden scope."""
    if not captured_names:
        return AgentCliNothingToUpdate(entries=(), all_clis=False), (), None

    unique_names = tuple(dict.fromkeys(captured_names))
    live_by_name = {status.name: status for status in statuses}
    selected_names = tuple(name for name in unique_names if name in live_by_name)
    missing_names = tuple(name for name in unique_names if name not in live_by_name)
    dropped = (
        ()
        if source_error
        else tuple(DroppedProviderCandidate(name) for name in missing_names)
    )
    selected_statuses = tuple(live_by_name[name] for name in selected_names)
    try:
        from . import plugins_browser_pane as pane_module

        plan = pane_module._plan_agent_cli_updates(
            selected_names,
            all_clis=False,
            refresh=False,
            offline=offline,
            status_fn=lambda **_kwargs: selected_statuses,
        )
    except Exception as exc:  # noqa: BLE001 - preserve independently valid SASE.
        return None, dropped, error_text(exc)
    provider_error = (
        f"provider inventory unavailable: {source_error}" if source_error else None
    )
    return plan, dropped, provider_error


def sase_preview_section(
    preview: ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    """Render the SASE leg of a comprehensive-update confirmation."""
    title = "SASE, core & plugins"
    if preview.sase_current:
        return PluginActionPreviewSection(
            title=title,
            summary="Already current in the live Updates inventory.",
            components=(
                PluginActionPreviewComponent(
                    "SASE, core & plugins",
                    "already current in the live Updates inventory",
                    "current",
                ),
            ),
            counts=("current",),
        )
    if preview.sase_blocker is not None or preview.sase_preview is None:
        return PluginActionPreviewSection(
            title=title,
            summary="This leg will not run.",
            components=(
                PluginActionPreviewComponent(
                    "SASE update",
                    preview.sase_blocker or "SASE update unavailable",
                    "skipped",
                ),
            ),
            skipped=(preview.sase_blocker or "SASE update unavailable",),
            counts=("skipped",),
        )
    sase = preview.sase_preview
    if sase.plan is None:
        return PluginActionPreviewSection(
            title=title,
            summary="Upgrades SASE core and every installed plugin.",
            components=(
                PluginActionPreviewComponent(
                    "sase + installed plugins", "managed upgrade", "update"
                ),
            ),
            commands=(shlex.join(tuple(build_upgrade_all(color="never"))),),
            counts=("1 command",),
        )

    plan = sase.plan
    components: list[PluginActionPreviewComponent] = []
    for root in plan.actionable_roots:
        behind = root.behind or 0
        noun = "commit" if behind == 1 else "commits"
        components.append(
            PluginActionPreviewComponent(
                short_root(root.git_root),
                f"{root.upstream or 'upstream'} · {behind} incoming {noun}",
                "update",
            )
        )
    for package in plan.actionable:
        components.append(
            PluginActionPreviewComponent(
                package.record.name,
                _version_transition(package.current_version, package.latest_version),
                "update",
            )
        )
    for step in plan.reconcile_steps:
        components.append(
            PluginActionPreviewComponent(
                step.label,
                "reconcile step" if step.available else (step.reason or "unavailable"),
                "update" if step.available else "skipped",
            )
        )
    for managed_package in sase.managed_packages:
        components.append(
            PluginActionPreviewComponent(
                managed_package.name,
                _version_transition(managed_package.current_version, None),
                "update",
            )
        )
    skipped = tuple(
        f"{package.record.name}: {package.reason}" for package in plan.skipped
    )
    components.extend(
        PluginActionPreviewComponent(
            package.record.name,
            package.reason,
            "skipped",
        )
        for package in plan.skipped
    )
    counts = [
        _count_label(len(plan.actionable_roots), "checkout"),
        _count_label(len(plan.reconcile_steps) + int(bool(sase.managed_argv)), "step"),
    ]
    if skipped:
        counts.append(_count_label(len(skipped), "skipped", plural="skipped"))
    return PluginActionPreviewSection(
        title=title,
        summary=dev_update_preview_summary(plan, subject="sase"),
        components=tuple(components),
        commands=dev_update_commands(plan, managed_argv=sase.managed_argv),
        skipped=skipped,
        counts=tuple(counts),
    )


def provider_preview_section(
    preview: ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    """Render the agent-CLI leg of a comprehensive-update confirmation."""
    title = "Agent CLIs"
    names = preview.request.provider_names
    if names is None:
        return PluginActionPreviewSection(
            title=title,
            summary="No completed automatic provider snapshot was available.",
        )
    if not names:
        return PluginActionPreviewSection(
            title=title,
            summary="The completed automatic snapshot had no provider candidates.",
        )

    entries = getattr(preview.provider_plan, "entries", ())
    runnable = tuple(entry for entry in entries if entry.argv is not None)
    commands = tuple(
        f"{entry.status.display_name}: {shlex.join(entry.argv or ())}"
        for entry in runnable
    )
    details = tuple(
        f"{entry.status.display_name} documentation: {entry.status.docs_url}"
        for entry in runnable
        if entry.status.docs_url
    )
    skipped = [
        f"{entry.status.display_name}: {entry.skip_reason or 'skipped'}"
        for entry in entries
        if entry.argv is None
    ]
    skipped.extend(f"{item.name}: {item.reason}" for item in preview.provider_dropped)
    if preview.provider_error:
        skipped.append(f"Provider planning failed: {preview.provider_error}")
    components = [
        PluginActionPreviewComponent(
            entry.status.display_name,
            _version_transition(
                entry.status.installed_version, entry.status.latest_version
            ),
            "update",
        )
        for entry in runnable
    ]
    for entry in entries:
        if entry.argv is not None:
            continue
        reason = entry.skip_reason or "skipped"
        is_current = "already up to date" in reason.lower()
        components.append(
            PluginActionPreviewComponent(
                entry.status.display_name,
                reason,
                "current" if is_current else "skipped",
            )
        )
    components.extend(
        PluginActionPreviewComponent(item.name, item.reason, "skipped")
        for item in preview.provider_dropped
    )
    if preview.provider_error:
        components.append(
            PluginActionPreviewComponent(
                "Provider planning", preview.provider_error, "skipped"
            )
        )
    counts = [_count_label(len(runnable), "command")]
    if skipped:
        counts.append(_count_label(len(skipped), "skipped", plural="skipped"))
    return PluginActionPreviewSection(
        title=title,
        summary=(
            f"{len(runnable)} safe provider command"
            f"{'s' if len(runnable) != 1 else ''} from the captured snapshot."
        ),
        components=tuple(components),
        commands=commands,
        details=details,
        skipped=tuple(skipped),
        counts=tuple(counts),
    )


def agents_preview_section(
    preview: ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    """Render the no-network agents-repository snapshot for confirmation."""
    title = "Agents repos"
    if preview.agents_error:
        return PluginActionPreviewSection(
            title=title,
            summary="Agents-repository status could not be planned.",
            components=(
                PluginActionPreviewComponent(
                    "Agents repositories",
                    preview.agents_error,
                    "skipped",
                ),
            ),
            skipped=(preview.agents_error,),
            counts=("1 error",),
        )
    snapshot = preview.agents_status
    if snapshot is None or not snapshot.projects:
        return PluginActionPreviewSection(
            title=title,
            summary="No agents repositories are present in the project inventory.",
        )

    statuses = tuple(sorted(snapshot.projects, key=lambda item: item.project_key))
    components = tuple(_agents_status_component(status) for status in statuses)
    enabled = tuple(status for status in statuses if status.state != "disabled")
    pending = tuple(
        status for status in enabled if agents_sync_status_needs_attention(status)
    )
    current = tuple(status for status in enabled if status not in pending)
    skipped = tuple(
        f"{status.project}: {agents_sync_status_detail(status)}"
        for status in statuses
        if status.state == "disabled"
    )
    counts = [
        _count_label(len(pending), "pending", plural="pending"),
        _count_label(len(current), "current", plural="current"),
    ]
    if skipped:
        counts.append(_count_label(len(skipped), "skipped", plural="skipped"))
    return PluginActionPreviewSection(
        title=title,
        summary=(
            f"Synchronizes all {len(enabled)} enabled agents "
            f"repositor{'y' if len(enabled) == 1 else 'ies'}."
            if enabled
            else "All agents repositories in the inventory are disabled."
        ),
        components=components,
        skipped=skipped,
        counts=tuple(counts),
    )


def _agents_status_component(
    status: ProjectSyncStatus,
) -> PluginActionPreviewComponent:
    if status.state == "disabled":
        state: PluginActionComponentState = "skipped"
    elif agents_sync_status_needs_attention(status):
        state = "update"
    else:
        state = "current"
    return PluginActionPreviewComponent(
        status.project,
        agents_sync_status_detail(status),
        state,
    )


def _version_transition(current: str | None, latest: str | None) -> str:
    if current and latest:
        return f"{current} → {latest}"
    if current:
        return f"{current} → latest"
    if latest:
        return f"installed version unknown → {latest}"
    return "update available"


def _count_label(count: int, singular: str, *, plural: str | None = None) -> str:
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"


def dev_update_commands(
    plan: DevUpdatePlan,
    *,
    managed_argv: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the commands represented by an editable-install update plan."""
    commands: list[str] = []
    for root in plan.actionable_roots:
        status = GitUpstreamStatus(
            root=root.git_root,
            upstream=root.upstream,
            remote=root.remote,
            remote_branch=root.remote_branch,
            detached=False,
            dirty=False,
            ahead=root.ahead,
            behind=root.behind,
        )
        commands.append(
            shlex.join(
                (
                    "git",
                    "-C",
                    root.git_root,
                    *git_fetch_upstream_args(status),
                )
            )
        )
        if root.upstream:
            commands.append(
                shlex.join(
                    ("git", "-C", root.git_root, "merge", "--ff-only", root.upstream)
                )
            )
    for step in plan.reconcile_steps:
        if step.command:
            commands.append(shlex.join(step.command))
        if step.repair_command:
            commands.append("fallback: " + shlex.join(step.repair_command))
    if managed_argv:
        commands.append(shlex.join(managed_argv))
    return tuple(commands)
