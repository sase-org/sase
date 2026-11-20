"""Bounded terminal sweep for quarantined, unrecoverable prompt-archive rows.

Automatic publication passes only list active rows, so a deferred prompt row
that quarantined before the terminal state existed -- or that quarantined
while its source could still reappear -- never reached the classifier again.
Each scheduler pass now re-checks a few of those rows per project through the
same Rust ``classify_deferred_prompt_obligation`` path and probes the
commit-time drain uses. A row the classifier calls unrecoverable retires in
one step: it turns terminal with the deterministic
``prompt_archive_unrecoverable`` reason, gets its audit record, and stops
protecting its staging-pool files.

The sweep never publishes, acknowledges, charges, unquarantines, or reports a
row as a job error. A row whose source still exists stays quarantined until
``--retry-quarantined`` revives it, and a small ledger defers its next re-check
so the per-pass cap walks the whole backlog instead of re-reading the same rows.
"""

from __future__ import annotations

from dataclasses import replace
import json
import logging
from pathlib import Path
import time
from typing import Any

from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.deferred import (
    DEFERRED_PROMPT_RESTORE_ERROR_PREFIX,
    classify_quarantined_prompt_archives,
)
from sase.agents_sync.prompt_archive.terminal import record_terminal_prompt_transition
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync.publication_outbox_store import mutate_publication_outbox
from sase.agents_sync.publication_timing import (
    INVENTORY_BUILD_BUDGET_SECONDS,
    InventoryBuildDeadlineExceeded,
    inventory_build_deadline,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot

log = logging.getLogger(__name__)

# Rows re-checked per project per pass; the backlog drains over a few ticks.
QUARANTINED_PROMPT_SWEEP_LIMIT = 25
# A row that stayed quarantined is not re-checked again for this long.
QUARANTINED_PROMPT_RECHECK_SECONDS = 3600.0
_SWEEP_LEDGER_FILENAME = "prompt_terminal_sweep.json"
_SWEEP_LEDGER_SCHEMA_VERSION = 1
# The sweep starts only with at least this much of the pass budget left.
_MIN_SWEEP_SLICE_SECONDS = 5.0
_SWEEP_LOCK_TIMEOUT_SECONDS = 5.0


def sweep_quarantined_prompt_archives(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
    deadline: float,
    now: float | None = None,
) -> int:
    """Retire due quarantined prompt rows the classifier proves unrecoverable.

    Returns how many rows turned terminal. Skips the pass, without error,
    when too little of *deadline* (a ``time.monotonic()`` value) is left,
    when the agents lock is busy, or when the scoped inventory build runs out
    of its slice; the rows stay due for the next pass.
    """

    observed = time.time() if now is None else now
    if deadline - time.monotonic() < _MIN_SWEEP_SLICE_SECONDS:
        return 0
    project_key = target.project_key
    candidates = tuple(
        item
        for item in list_agent_publications(project_key)
        if _is_quarantined_prompt_row(item)
    )
    ledger = _read_ledger()
    checked = _project_entries(ledger, project_key)
    due = tuple(
        sorted(
            (item for item in candidates if _is_due(checked, item, observed)),
            key=lambda item: (
                _checked_at(checked, item),
                item.created_at,
                item.logical_key,
            ),
        )
    )[:QUARANTINED_PROMPT_SWEEP_LIMIT]
    if not due:
        _save_ledger(ledger, project_key, candidates, changed=False)
        return 0
    if not target.sidecar_path.is_dir():
        return 0

    from sase.agents_sync import _commit_publication_support as publication_support
    from sase.agents_sync import git_sync

    identity = AgentIdentitySnapshot(publication_support.require_agent_owner_identity())
    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(
        lock_path,
        min(_SWEEP_LOCK_TIMEOUT_SECONDS, max(deadline - time.monotonic(), 0.0)),
        operation="prompt-terminal-sweep",
    ) as acquired:
        if not acquired:
            return 0
        slice_seconds = min(INVENTORY_BUILD_BUDGET_SECONDS, deadline - time.monotonic())
        if slice_seconds <= 0:
            return 0

        def load_inventory() -> ProjectHoodInventory:
            with inventory_build_deadline(None, seconds=slice_seconds):
                return build_project_hood_inventory(
                    target,
                    identity,
                    git_runner=git_runner,
                    requested_hoods=frozenset(item.local_hood for item in due),
                )

        try:
            messages = classify_quarantined_prompt_archives(
                target,
                due,
                identity=identity,
                load_inventory=load_inventory,
                now=observed,
            )
        except InventoryBuildDeadlineExceeded:
            log.info(
                "quarantined prompt sweep for %s deferred: inventory build ran "
                "out of its slice",
                project_key,
            )
            return 0
        retired = _retire_unrecoverable(project_key, due, messages, now=observed)
    for before, after in retired:
        record_terminal_prompt_transition(
            project_key=project_key,
            before=before,
            after=after,
        )
    if retired:
        log.info(
            "retired %d unrecoverable quarantined prompt archive(s) for %s",
            len(retired),
            project_key,
        )
    retired_keys = {before.logical_key for before, _after in retired}
    for item in due:
        if item.logical_key in retired_keys:
            checked.pop(_ledger_key(item), None)
            continue
        checked[_ledger_key(item)] = {
            "checked_at": observed,
            "quarantined_at": item.quarantined_at,
        }
    _save_ledger(ledger, project_key, candidates, changed=True)
    return len(retired)


def _is_quarantined_prompt_row(item: AgentPublicationOutboxItem) -> bool:
    return (
        item.quarantined
        and not item.terminal
        and isinstance(item.last_error, str)
        and item.last_error.startswith(DEFERRED_PROMPT_RESTORE_ERROR_PREFIX)
    )


def _retire_unrecoverable(
    project_key: str,
    swept: tuple[AgentPublicationOutboxItem, ...],
    messages: dict[tuple[str, str], str],
    *,
    now: float,
) -> list[tuple[AgentPublicationOutboxItem, AgentPublicationOutboxItem]]:
    """Retire each classified row in one locked write, if it is unchanged.

    A row revived, re-charged, or retired since it was read keeps its current
    state. Attempts are untouched: the sweep never charges a row.
    """

    if not messages:
        return []
    seen = {item.logical_key: item for item in swept if item.logical_key in messages}
    retired: list[tuple[AgentPublicationOutboxItem, AgentPublicationOutboxItem]] = []

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        updated: list[AgentPublicationOutboxItem] = []
        for item in items:
            before = seen.get(item.logical_key)
            if before is None or not _unchanged_since_sweep(item, before):
                updated.append(item)
                continue
            message = messages[item.logical_key]
            after = replace(
                item,
                last_error=message,
                quarantined=False,
                quarantined_at=None,
                terminal=True,
                terminal_reason=message,
                updated_at=now,
            )
            retired.append((item, after))
            updated.append(after)
        return tuple(updated)

    mutate_publication_outbox(project_key, update)
    return retired


def _unchanged_since_sweep(
    current: AgentPublicationOutboxItem,
    swept: AgentPublicationOutboxItem,
) -> bool:
    return (
        _is_quarantined_prompt_row(current)
        and current.attempts == swept.attempts
        and current.last_error == swept.last_error
        and current.quarantined_at == swept.quarantined_at
    )


def _ledger_path() -> Path:
    from sase.core.paths import sase_home

    return sase_home() / "agent_publication" / _SWEEP_LEDGER_FILENAME


def _ledger_key(item: AgentPublicationOutboxItem) -> str:
    return f"{item.global_agent}@{item.primary_revision}"


def _read_ledger() -> dict[str, Any]:
    """Read the re-check ledger; anything unreadable starts empty (fail-open)."""

    try:
        raw = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable quarantined prompt sweep ledger: %s", exc)
        raw = None
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != _SWEEP_LEDGER_SCHEMA_VERSION
        or not isinstance(raw.get("projects"), dict)
    ):
        return {"schema_version": _SWEEP_LEDGER_SCHEMA_VERSION, "projects": {}}
    return raw


def _project_entries(ledger: dict[str, Any], project_key: str) -> dict[str, Any]:
    projects = ledger["projects"]
    entries = projects.get(project_key)
    if not isinstance(entries, dict):
        entries = {}
        projects[project_key] = entries
    return entries


def _checked_at(checked: dict[str, Any], item: AgentPublicationOutboxItem) -> float:
    entry = checked.get(_ledger_key(item))
    value = entry.get("checked_at") if isinstance(entry, dict) else None
    return float(value) if isinstance(value, int | float) else 0.0


def _is_due(
    checked: dict[str, Any],
    item: AgentPublicationOutboxItem,
    now: float,
) -> bool:
    """A row is due when never checked, re-quarantined, or its re-check came up."""

    entry = checked.get(_ledger_key(item))
    if not isinstance(entry, dict):
        return True
    if entry.get("quarantined_at") != item.quarantined_at:
        return True
    return now - _checked_at(checked, item) >= QUARANTINED_PROMPT_RECHECK_SECONDS


def _save_ledger(
    ledger: dict[str, Any],
    project_key: str,
    candidates: tuple[AgentPublicationOutboxItem, ...],
    *,
    changed: bool,
) -> None:
    """Drop entries for rows no longer waiting in quarantine, then persist."""

    entries = _project_entries(ledger, project_key)
    live = {_ledger_key(item) for item in candidates}
    stale = [key for key in entries if key not in live]
    for key in stale:
        del entries[key]
    if not entries:
        del ledger["projects"][project_key]
    if changed or stale:
        _write_ledger(ledger)


def _write_ledger(ledger: dict[str, Any]) -> None:
    try:
        atomic_write_json(_ledger_path(), ledger)
    except OSError as exc:
        # The ledger only paces re-checks; losing it re-checks rows sooner.
        log.warning("could not write quarantined prompt sweep ledger: %s", exc)


__all__ = [
    "QUARANTINED_PROMPT_RECHECK_SECONDS",
    "QUARANTINED_PROMPT_SWEEP_LIMIT",
    "sweep_quarantined_prompt_archives",
]
