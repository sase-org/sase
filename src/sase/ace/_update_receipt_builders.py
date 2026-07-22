"""Normalize update-operation results into ACE toast receipts."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import replace

from sase.ace._update_receipt_models import (
    MAX_COMMIT_GROUPS,
    MAX_PLUGIN_LINES,
    MAX_PROVIDER_LINES,
    ProviderUpdateReceiptResult,
    ProviderReceiptStatus,
    RepoCommitGroup,
    ReceiptKind,
    UpdateToastReceipt,
    UpdateVersionTransition,
)
from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.agent_clis.models import AgentCliUpdateResult
from sase.dev_update.models import DevUpdateOutcome, DevUpdateResult, RepoDiffStat
from sase.main.update_types import CombinedUpdateResult
from sase.mode_switch.models import ModeSwitchResult
from sase.plugins.operations import (
    InstallManyOutcome,
    InstallOutcome,
    UninstallOutcome,
    UpdateOutcome as PluginUpdateOutcome,
)
from sase.uv_tool.render import UpdateOutcome as ManagedUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from sase.version._utils import normalize_distribution_name

_PRIMARY_DIST_KEY = normalize_distribution_name("sase")


def build_update_receipt(
    payload: object, *, created_at: float | None = None
) -> UpdateToastReceipt | None:
    """Normalize a managed or dev update payload into a toast receipt."""
    timestamp = time.time() if created_at is None else float(created_at)
    if isinstance(payload, UpdateSummary):
        return _build_managed_receipt(payload, created_at=timestamp)
    if isinstance(payload, DevUpdateResult):
        return _build_dev_receipt(payload, created_at=timestamp)
    if isinstance(payload, CombinedUpdateResult):
        return _build_combined_receipt(payload, created_at=timestamp)
    if isinstance(payload, ComprehensiveUpdateResult):
        return _build_comprehensive_receipt(payload, created_at=timestamp)
    if isinstance(payload, ModeSwitchResult):
        return _build_mode_switch_receipt(payload, created_at=timestamp)
    if isinstance(payload, InstallOutcome):
        return _build_plugin_install_receipt(payload, created_at=timestamp)
    if isinstance(payload, InstallManyOutcome):
        return _build_plugin_install_many_receipt(payload, created_at=timestamp)
    if isinstance(payload, PluginUpdateOutcome):
        return _build_plugin_update_receipt(payload, created_at=timestamp)
    if isinstance(payload, UninstallOutcome):
        return _build_plugin_uninstall_receipt(payload, created_at=timestamp)
    return None


def _build_managed_receipt(
    summary: UpdateSummary, *, created_at: float
) -> UpdateToastReceipt | None:
    primary = next(
        (
            _transition_from_update_outcome(outcome)
            for outcome in summary.updated
            if outcome.role == "primary"
        ),
        None,
    )
    plugin_transitions = [
        _transition_from_update_outcome(outcome)
        for outcome in summary.updated
        if outcome.role == "plugin"
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
    dependency_count = len(summary.updated_dependencies)
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_dev_receipt(
    result: DevUpdateResult, *, created_at: float
) -> UpdateToastReceipt | None:
    updated = tuple(
        outcome for outcome in result.outcomes if outcome.status == "updated"
    )
    primary = next(
        (
            _transition_from_dev_outcome(outcome)
            for outcome in updated
            if normalize_distribution_name(outcome.record.name) == _PRIMARY_DIST_KEY
        ),
        None,
    )
    plugin_transitions = [
        _transition_from_dev_outcome(outcome)
        for outcome in updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role == "plugin"
        )
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
    dependency_count = sum(
        1
        for outcome in updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role != "plugin"
        )
    )
    commit_groups, commit_group_overflow = _commit_groups_from_dev_outcomes(updated)
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="dev",
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
        commit_groups=commit_groups,
        commit_group_overflow=commit_group_overflow,
    )


def _build_combined_receipt(
    result: CombinedUpdateResult, *, created_at: float
) -> UpdateToastReceipt | None:
    """Merge editable transitions with managed dependency transitions."""
    dev_updated = (
        tuple(
            outcome
            for outcome in result.dev_result.outcomes
            if outcome.status == "updated"
        )
        if result.dev_result is not None
        else ()
    )
    managed_updated = (
        result.managed_summary.updated if result.managed_summary is not None else ()
    )
    primary = next(
        (
            _transition_from_dev_outcome(outcome)
            for outcome in dev_updated
            if normalize_distribution_name(outcome.record.name) == _PRIMARY_DIST_KEY
        ),
        None,
    ) or next(
        (
            _transition_from_update_outcome(outcome)
            for outcome in managed_updated
            if outcome.role == "primary"
        ),
        None,
    )
    transitions = [
        _transition_from_dev_outcome(outcome)
        for outcome in dev_updated
        if outcome.record.role == "plugin"
    ]
    transitions.extend(
        _transition_from_update_outcome(outcome)
        for outcome in managed_updated
        if outcome.role == "plugin"
    )
    plugins, overflow, overflow_diffstat = _cap_plugin_transitions(transitions)
    dependency_count = sum(
        1
        for outcome in dev_updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role != "plugin"
        )
    ) + sum(1 for outcome in managed_updated if outcome.role == "dependency")
    commit_groups, commit_group_overflow = _commit_groups_from_dev_outcomes(dev_updated)
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind=(
            "dev"
            if result.dev_result is not None and result.dev_result.changed
            else "managed"
        ),
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=overflow,
        plugin_overflow_diffstat=overflow_diffstat,
        dependency_count=dependency_count,
        commit_groups=commit_groups,
        commit_group_overflow=commit_group_overflow,
    )


def _build_comprehensive_receipt(
    result: ComprehensiveUpdateResult,
    *,
    created_at: float,
) -> UpdateToastReceipt | None:
    """Attach bounded provider outcomes to the changed SASE receipt."""
    if not result.code_changed or result.sase.payload is None:
        return None
    base = build_update_receipt(result.sase.payload, created_at=created_at)
    if base is None:
        kind: ReceiptKind = (
            "dev"
            if isinstance(result.sase.payload, (DevUpdateResult, CombinedUpdateResult))
            else "managed"
        )
        base = UpdateToastReceipt(
            kind=kind,
            created_at=created_at,
            primary=None,
        )

    provider_results = [
        _provider_receipt_result(provider) for provider in result.provider_results
    ]
    if result.provider_error:
        provider_results.append(
            ProviderUpdateReceiptResult(
                name="agent-clis",
                display_name="Agent CLIs",
                status="failed",
                reason=result.provider_error,
            )
        )
    capped = tuple(provider_results[:MAX_PROVIDER_LINES])
    return replace(
        base,
        provider_results=capped,
        provider_overflow=max(0, len(provider_results) - len(capped)),
    )


def _provider_receipt_result(
    result: AgentCliUpdateResult,
) -> ProviderUpdateReceiptResult:
    status: ProviderReceiptStatus = result.status.value  # type: ignore[assignment]
    return ProviderUpdateReceiptResult(
        name=result.name,
        display_name=result.display_name,
        status=status,
        old_version=result.old_version,
        new_version=result.new_version,
        reason=result.reason,
        docs_url=result.docs_url,
        command=result.command,
        suggested_command=result.suggested_command,
    )


def _build_mode_switch_receipt(
    result: ModeSwitchResult, *, created_at: float
) -> UpdateToastReceipt | None:
    if not result.changed:
        return None
    primary = next(
        (
            UpdateVersionTransition(
                name=outcome.name,
                old=outcome.old_version,
                new=outcome.new_version,
            )
            for outcome in result.outcomes
            if outcome.role == "host"
        ),
        None,
    )
    plugin_transitions = [
        UpdateVersionTransition(
            name=outcome.name,
            old=outcome.old_version,
            new=outcome.new_version,
        )
        for outcome in result.outcomes
        if outcome.role == "plugin"
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
    dependency_count = sum(1 for outcome in result.outcomes if outcome.role == "core")
    kind: ReceiptKind = (
        "mode_switch_dev" if result.plan.target_mode == "dev" else "mode_switch_pypi"
    )
    return UpdateToastReceipt(
        kind=kind,
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _transition_from_update_outcome(
    outcome: ManagedUpdateOutcome,
) -> UpdateVersionTransition:
    return UpdateVersionTransition(
        name=outcome.name,
        old=outcome.old_version,
        new=outcome.new_version,
    )


def _transition_from_dev_outcome(outcome: DevUpdateOutcome) -> UpdateVersionTransition:
    return UpdateVersionTransition(
        name=outcome.record.name,
        old=outcome.old_version,
        new=outcome.new_version,
        diffstat=outcome.diffstat,
    )


def _commit_groups_from_dev_outcomes(
    updated_outcomes: Iterable[DevUpdateOutcome],
) -> tuple[tuple[RepoCommitGroup, ...], int]:
    representatives: list[DevUpdateOutcome] = []
    seen_roots: set[str] = set()
    for outcome in updated_outcomes:
        commits = outcome.commits
        git_root = outcome.git_root
        if (
            commits is None
            or commits.total <= 0
            or git_root is None
            or git_root in seen_roots
        ):
            continue
        seen_roots.add(git_root)
        representatives.append(outcome)

    representatives.sort(key=_commit_group_sort_key)
    groups = tuple(
        RepoCommitGroup(label=outcome.record.name, commits=outcome.commits)
        for outcome in representatives
        if outcome.commits is not None
    )
    capped = groups[:MAX_COMMIT_GROUPS]
    return capped, max(0, len(groups) - len(capped))


def _commit_group_sort_key(outcome: DevUpdateOutcome) -> int:
    if normalize_distribution_name(outcome.record.name) == _PRIMARY_DIST_KEY:
        return 0
    if outcome.record.role == "core":
        return 1
    if outcome.record.role == "plugin":
        return 2
    return 3


def _build_plugin_install_receipt(
    outcome: InstallOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    spec = outcome.plan.spec
    target_key = spec.normalized_name
    transition = _transition_from_change(
        outcome.change_set.get(spec.requirement.name),
        fallback_name=spec.requirement.name,
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys={target_key},
    )
    if transition is None and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=(transition,) if transition is not None else (),
        dependency_count=dependency_count,
    )


def _build_plugin_install_many_receipt(
    outcome: InstallManyOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_keys = {spec.normalized_name for spec in outcome.plan.specs}
    transitions = [
        transition
        for spec in outcome.plan.specs
        if (
            transition := _transition_from_change(
                outcome.change_set.get(spec.requirement.name),
                fallback_name=spec.requirement.name,
            )
        )
        is not None
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        transitions
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys=target_keys,
    )
    if not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_plugin_update_receipt(
    outcome: PluginUpdateOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_keys = {
        normalize_distribution_name(target) for target in outcome.plan.targets
    }
    transitions = [
        transition
        for target in outcome.plan.targets
        if (
            transition := _transition_from_change(
                outcome.change_set.get(target),
                fallback_name=target,
            )
        )
        is not None
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        transitions
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys=target_keys,
    )
    if not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_plugin_uninstall_receipt(
    outcome: UninstallOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_key = outcome.plan.normalized_name
    transition = _transition_from_change(
        outcome.change_set.get(outcome.plan.dist_name),
        fallback_name=outcome.plan.dist_name,
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys={target_key},
    )
    if transition is None and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=(transition,) if transition is not None else (),
        dependency_count=dependency_count,
    )


def _transition_from_change(
    change: UvPackageChange | None, *, fallback_name: str
) -> UpdateVersionTransition | None:
    if change is None or change.kind is ChangeKind.UNCHANGED:
        return None
    old = change.old_version
    new = change.new_version
    if old is None and new is None:
        return None
    return UpdateVersionTransition(name=change.name or fallback_name, old=old, new=new)


def _dependency_change_count(change_set: UvChangeSet, *, target_keys: set[str]) -> int:
    return sum(
        1
        for change in change_set.changes
        if normalize_distribution_name(change.name) not in target_keys
        and change.kind is not ChangeKind.UNCHANGED
    )


def _cap_plugin_transitions(
    transitions: list[UpdateVersionTransition],
) -> tuple[tuple[UpdateVersionTransition, ...], int, RepoDiffStat | None]:
    capped = tuple(transitions[:MAX_PLUGIN_LINES])
    overflow = transitions[MAX_PLUGIN_LINES:]
    return (
        capped,
        len(overflow),
        _sum_diffstats(transition.diffstat for transition in overflow),
    )


def _sum_diffstats(diffstats: Iterable[RepoDiffStat | None]) -> RepoDiffStat | None:
    files_changed = 0
    insertions = 0
    deletions = 0
    found = False
    for diffstat in diffstats:
        if diffstat is None or diffstat.is_empty:
            continue
        found = True
        files_changed += diffstat.files_changed
        insertions += diffstat.insertions
        deletions += diffstat.deletions
    if not found:
        return None
    return RepoDiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )
