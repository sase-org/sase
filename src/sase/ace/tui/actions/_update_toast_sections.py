"""Repository-section assembly for the automatic ACE update toast."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sase.updates import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    OutdatedComponent,
    UpdateStatus,
    allocate_commit_budget,
    component_commit_spec,
)

from ._update_toast_config import UpdateToastConfig

log = logging.getLogger(__name__)

_STARTUP_TOAST_DEADLINE_SECONDS = 8.0

FetchIncomingCommitsFn = Callable[..., IncomingCommits]


@dataclass(frozen=True)
class ToastRepoSection:
    """One repository section in the automatic update toast."""

    label: str
    installed_version: str
    latest_version: str
    commits: tuple[CommitSummary, ...] = ()
    total: int = 0


def build_startup_toast_sections(
    status: UpdateStatus,
    config: UpdateToastConfig,
    *,
    fetch_fn: FetchIncomingCommitsFn,
) -> tuple[ToastRepoSection, ...]:
    if not config.incoming_commits_enabled or config.startup_toast_max_commits <= 0:
        return header_only_sections(status.components)
    return build_toast_commit_sections(
        status.components,
        fetch_fn=fetch_fn,
        max_total=config.startup_toast_max_commits,
        offline=False,
        deadline=time.monotonic() + _STARTUP_TOAST_DEADLINE_SECONDS,
    )


def build_toast_commit_sections(
    components: Sequence[OutdatedComponent],
    *,
    fetch_fn: FetchIncomingCommitsFn,
    max_total: int,
    offline: bool,
    deadline: float,
) -> tuple[ToastRepoSection, ...]:
    """Fetch, fairly truncate, and align incoming commits to update components."""
    if max_total <= 0:
        return header_only_sections(components)
    incoming_by_index: dict[int, IncomingCommits] = {}
    targets: list[tuple[int, CommitSourceSpec]] = []
    for index, component in enumerate(components):
        spec = component_commit_spec(component)
        if spec is not None:
            targets.append((index, spec))
    targets.sort(key=lambda item: (1 if item[1].source == "github" else 0, item[0]))
    for index, spec in targets:
        if time.monotonic() >= deadline:
            break
        try:
            incoming_by_index[index] = fetch_fn(
                spec,
                limit=max_total,
                offline=offline,
            )
        except Exception:  # noqa: BLE001 - update hints must never break ACE.
            log.debug(
                "Failed to fetch incoming commits for automatic update toast",
                exc_info=True,
            )
    totals = [
        _fetchable_total(incoming_by_index.get(index))
        for index, _component in enumerate(components)
    ]
    allocations = allocate_commit_budget(totals, max_total)
    sections: list[ToastRepoSection] = []
    for index, component in enumerate(components):
        incoming = incoming_by_index.get(index)
        total = totals[index]
        allocated = allocations[index]
        commits = incoming.commits[:allocated] if incoming is not None else ()
        sections.append(
            ToastRepoSection(
                label=component.display_name,
                installed_version=component.installed_version or "unknown",
                latest_version=component.latest_version or "unknown",
                commits=tuple(commits),
                total=total,
            )
        )
    return tuple(sections)


def _fetchable_total(incoming: IncomingCommits | None) -> int:
    if incoming is None or incoming.source == "unavailable":
        return 0
    return max(0, incoming.total)


def header_only_sections(
    components: Sequence[OutdatedComponent],
) -> tuple[ToastRepoSection, ...]:
    return tuple(
        ToastRepoSection(
            label=component.display_name,
            installed_version=component.installed_version or "unknown",
            latest_version=component.latest_version or "unknown",
        )
        for component in components
    )
