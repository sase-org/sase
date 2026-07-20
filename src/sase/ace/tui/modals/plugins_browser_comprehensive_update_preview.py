"""Planning and confirmation rendering for comprehensive updates."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUpdatePlan,
)
from sase.dev_update.models import DevUpdatePlan
from sase.uv_tool.commands import build_upgrade_all
from sase.version._git import GitUpstreamStatus, git_fetch_upstream_args

from .plugin_action_confirm_modal import PluginActionPreviewSection
from .plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    DroppedProviderCandidate,
    error_text,
)
from .plugins_browser_dev_update import dev_update_preview_summary


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
        )
    if preview.sase_blocker is not None or preview.sase_preview is None:
        return PluginActionPreviewSection(
            title=title,
            summary="This leg will not run.",
            skipped=(preview.sase_blocker or "SASE update unavailable",),
        )
    sase = preview.sase_preview
    if sase.plan is None:
        return PluginActionPreviewSection(
            title=title,
            summary="Upgrades SASE core and every installed plugin.",
            commands=(shlex.join(tuple(build_upgrade_all(color="never"))),),
        )

    plan = sase.plan
    skipped = tuple(
        f"{package.record.name}: {package.reason}" for package in plan.skipped
    )
    return PluginActionPreviewSection(
        title=title,
        summary=dev_update_preview_summary(plan, subject="sase"),
        commands=dev_update_commands(plan, managed_argv=sase.managed_argv),
        skipped=skipped,
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
    return PluginActionPreviewSection(
        title=title,
        summary=(
            f"{len(runnable)} safe provider command"
            f"{'s' if len(runnable) != 1 else ''} from the captured snapshot."
        ),
        commands=commands,
        details=details,
        skipped=tuple(skipped),
    )


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
