"""Planning and confirmation rendering for comprehensive updates."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Collection, Sequence

from sase.ace.tui.agents_sync_format import captured_agent_hood_label
from sase.ace.tui.update_preview_inputs import UpdatePreviewInputs
from sase.ace.update_scope import UpdateLeg, UpdateScope
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUpdatePlan,
)
from sase.agents_sync import get_agents_sync_status
from sase.agents_sync.models import CapturedIncomingHood
from sase.dev_update.models import DevUpdatePlan
from sase.updates import UpdateStatus
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.version._git import GitUpstreamStatus, git_fetch_upstream_args

from .plugin_action_confirm_modal import (
    PluginActionPreviewComponent,
    PluginActionPreviewSection,
)
from .plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
    DroppedProviderCandidate,
    error_text,
)
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_blocking_reason,
    dev_update_preview_summary,
    make_sase_dev_update_preview,
    short_root,
)
from .plugins_browser_sase_update_summary import load_receipt_for_summary

_EVERYTHING_INTRO = (
    "Confirm the snapshot-gated SASE, provider, and agents-repository "
    "work below. Agent CLI commands run first and sequentially; "
    "agent updates use only the captured cache."
)
_CONFIRM_COPY: dict[UpdateScope, tuple[str, str]] = {
    UpdateScope.EVERYTHING: ("Update everything", _EVERYTHING_INTRO),
    UpdateScope.SASE: (
        "Update SASE, core & plugins",
        "Confirm the SASE, core, and plugin work below.",
    ),
    UpdateScope.PROVIDERS: (
        "Update providers",
        "Confirm the exact provider update commands below; they run sequentially.",
    ),
    UpdateScope.AGENTS: (
        "Import published agents",
        "Confirm the cached agent hoods to import. Only the captured cache is used.",
    ),
}
_CURRENT_MESSAGES: dict[UpdateScope, str] = {
    UpdateScope.EVERYTHING: (
        "Everything in the captured comprehensive update is already current."
    ),
    UpdateScope.SASE: (
        "SASE, core, and plugins in the captured update are already current."
    ),
    UpdateScope.PROVIDERS: (
        "Captured providers in the selected update are already current."
    ),
    UpdateScope.AGENTS: (
        "Captured agent hoods in the selected update are already current."
    ),
}
_DROPPED_LEADS: dict[UpdateScope, str] = {
    UpdateScope.EVERYTHING: "No captured updates remain",
    UpdateScope.SASE: "No captured SASE updates remain",
    UpdateScope.PROVIDERS: "No captured provider updates remain",
    UpdateScope.AGENTS: "No captured agent updates remain",
}


def _plan_captured_providers(
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


def build_comprehensive_update_preview(
    request: ComprehensiveUpdateRequest,
    inputs: UpdatePreviewInputs,
    *,
    already_refreshed_roots: Collection[str] = (),
) -> ComprehensiveUpdatePreview:
    """Plan only the legs selected by *request* from explicit *inputs*."""
    selected = request.scope.legs
    agents_updates, agents_error = _plan_agents_leg(selected)
    provider_plan, dropped, provider_error = _plan_providers_leg(
        request, inputs, selected
    )
    sase_preview, sase_current, sase_blocker = _plan_sase_leg(
        inputs,
        selected,
        already_refreshed_roots=already_refreshed_roots,
    )
    return ComprehensiveUpdatePreview(
        request=request,
        sase_preview=sase_preview,
        sase_current=sase_current,
        sase_blocker=sase_blocker,
        provider_plan=provider_plan,
        provider_dropped=dropped,
        provider_error=provider_error,
        agents_updates=agents_updates,
        agents_error=agents_error,
    )


def _plan_agents_leg(
    selected: frozenset[UpdateLeg],
) -> tuple[tuple[CapturedIncomingHood, ...], str | None]:
    if UpdateLeg.AGENTS not in selected:
        return (), None
    try:
        agents_status = get_agents_sync_status(revalidate_only=True)
        updates = tuple(
            sorted(
                (
                    item
                    for status in agents_status.projects
                    for item in status.pending_updates
                ),
                key=lambda item: (
                    item.project_key,
                    item.source_username or "",
                    item.source_machine,
                    item.top_hood,
                    item.cache_id,
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - preserve independently valid legs.
        return (), error_text(exc)
    return updates, None


def _plan_providers_leg(
    request: ComprehensiveUpdateRequest,
    inputs: UpdatePreviewInputs,
    selected: frozenset[UpdateLeg],
) -> tuple[
    AgentCliUpdatePlan | None,
    tuple[DroppedProviderCandidate, ...],
    str | None,
]:
    if UpdateLeg.PROVIDERS not in selected:
        return None, (), None
    return _plan_captured_providers(
        request.provider_names,
        inputs.agent_cli_statuses,
        offline=inputs.offline,
        source_error=inputs.agent_cli_error,
    )


def _plan_sase_leg(
    inputs: UpdatePreviewInputs,
    selected: frozenset[UpdateLeg],
    *,
    already_refreshed_roots: Collection[str],
) -> tuple[DevUpdatePreview | None, bool, str | None]:
    if UpdateLeg.SASE not in selected:
        return None, False, None
    if _sase_is_cached_current(inputs.cached_status):
        return None, True, None
    install = inputs.uv_tool
    if isinstance(install, NotUvToolInstall):
        return None, False, str(NotAUvToolInstallError(install))
    try:
        receipt = load_receipt_for_summary(install)
        sase_preview = make_sase_dev_update_preview(
            receipt,
            already_refreshed_roots=frozenset(already_refreshed_roots),
        )
        blocker = sase_preview.error
        if blocker is None and sase_preview.plan is not None:
            plan_blocker = dev_update_blocking_reason(sase_preview.plan)
            managed_can_proceed = bool(
                sase_preview.managed_argv and not sase_preview.plan.actionable_roots
            )
            if plan_blocker is not None and not managed_can_proceed:
                blocker = plan_blocker
    except Exception as exc:  # noqa: BLE001 - preserve independently valid legs.
        return None, False, error_text(exc)
    return sase_preview, False, blocker


def _sase_is_cached_current(status: UpdateStatus | None) -> bool:
    return bool(
        status is not None
        and status.core_source.successful
        and status.plugin_source.successful
        and status.component_count == 0
    )


def _sase_preview_section(
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
        commands=_dev_update_commands(plan, managed_argv=sase.managed_argv),
        skipped=skipped,
        counts=tuple(counts),
    )


def _provider_preview_section(
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


def _agents_preview_section(
    preview: ComprehensiveUpdatePreview,
) -> PluginActionPreviewSection:
    """Render the no-network agents-repository snapshot for confirmation."""
    title = "Cached agent hoods"
    if preview.agents_error:
        return PluginActionPreviewSection(
            title=title,
            summary="Cached agent-hood status could not be planned.",
            components=(
                PluginActionPreviewComponent(
                    "Cached agent hoods",
                    preview.agents_error,
                    "skipped",
                ),
            ),
            skipped=(preview.agents_error,),
            counts=("1 error",),
        )
    updates = preview.agents_updates
    if not updates:
        return PluginActionPreviewSection(
            title=title,
            summary="No cached incoming agent hoods from other owners were captured.",
        )

    ordered = tuple(
        sorted(
            updates,
            key=lambda item: (
                item.project_key,
                item.source_username or "",
                item.source_machine,
                item.top_hood,
                item.cache_id,
            ),
        )
    )
    components = tuple(_captured_agents_component(item) for item in ordered)
    project_count = len({item.project_key for item in ordered})
    return PluginActionPreviewSection(
        title=title,
        summary=(
            f"Imports {len(ordered)} captured incoming "
            f"hood{'s' if len(ordered) != 1 else ''} from other owners across "
            f"{project_count} project{'s' if project_count != 1 else ''} "
            "without network access."
        ),
        components=components,
        counts=(
            _count_label(project_count, "project"),
            _count_label(len(ordered), "hood"),
        ),
    )


def comprehensive_preview_sections(
    preview: ComprehensiveUpdatePreview,
) -> tuple[PluginActionPreviewSection, ...]:
    """Render confirmation sections for the selected legs only."""
    sections: list[PluginActionPreviewSection] = []
    selected = preview.selected_legs
    if UpdateLeg.SASE in selected:
        sections.append(_sase_preview_section(preview))
    if UpdateLeg.PROVIDERS in selected:
        sections.append(_provider_preview_section(preview))
    if UpdateLeg.AGENTS in selected:
        sections.append(_agents_preview_section(preview))
    return tuple(sections)


def comprehensive_confirm_copy(scope: UpdateScope) -> tuple[str, str, str]:
    """Return ``(title, intro, panel_title)`` for the confirmation modal."""
    title, intro = _CONFIRM_COPY[scope]
    panel_title = (
        "Confirm comprehensive update" if scope is UpdateScope.EVERYTHING else title
    )
    return title, intro, panel_title


def _comprehensive_current_message(scope: UpdateScope) -> str:
    """Return the already-current noop toast for *scope*."""
    return _CURRENT_MESSAGES[scope]


def _comprehensive_dropped_message(scope: UpdateScope, names: str) -> str:
    """Return the dropped-candidate noop toast for *scope*."""
    lead = _DROPPED_LEADS[scope]
    return f"{lead}: available components are current; no longer present: {names}."


def handle_comprehensive_noop(
    preview: ComprehensiveUpdatePreview,
    *,
    notify: Callable[..., None],
) -> None:
    """Toast the scoped no-op outcome; never treat an unselected leg as current."""
    if preview.manual_provider_entries:
        notify(
            "No safe automatic Agent CLI command is available. Review the "
            "manual command and vendor documentation in the Admin Center "
            "Updates tab.",
            severity="warning",
        )
        return
    selected = preview.selected_legs
    errors = tuple(
        item
        for item, selected_leg in (
            (preview.sase_blocker, UpdateLeg.SASE),
            (preview.provider_error, UpdateLeg.PROVIDERS),
            (preview.agents_error, UpdateLeg.AGENTS),
        )
        if item and selected_leg in selected
    )
    if errors:
        notify("; ".join(errors), severity="error")
        return
    if preview.provider_dropped:
        names = ", ".join(item.name for item in preview.provider_dropped)
        notify(
            _comprehensive_dropped_message(preview.request.scope, names),
            severity="information",
        )
        return
    notify(
        _comprehensive_current_message(preview.request.scope),
        severity="information",
    )


def _captured_agents_component(
    item: CapturedIncomingHood,
) -> PluginActionPreviewComponent:
    run_noun = "run" if item.run_count == 1 else "runs"
    family_noun = "family" if item.family_count == 1 else "families"
    return PluginActionPreviewComponent(
        item.project,
        f"{captured_agent_hood_label(item)} · "
        f"{item.run_count} {run_noun} · "
        f"{item.family_count} {family_noun}",
        "update",
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


def _dev_update_commands(
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
