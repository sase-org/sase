"""Catalog fetchers for gates, tool runs, and task types.

Gate shells and tool runs are read from cached runtime indexes, task types
from the in-process registry; see :mod:`sase.completion.candidates.catalog`
for the import contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate


def gate_source_path(_project: str | None) -> Path | None:
    """Return the agent artifact index whose mtime invalidates gate shells."""
    from sase.core.paths import sase_home

    return sase_home() / "agent_artifact_index.sqlite"


def gate_candidates(project: str | None) -> list[Candidate]:
    """Return known gate-shell ids and member agent names, with their state."""
    from sase.gate_turn.store import list_gate_turns

    try:
        shells = list_gate_turns(project=project)
    except Exception:
        return []
    candidates: list[Candidate] = []
    for shell in shells:
        gate_id = str(getattr(shell, "gate_id", "") or "")
        if not gate_id:
            continue
        state = str(getattr(shell, "gate_state", "") or "")
        kind = str(getattr(shell, "kind", "") or "")
        label = str(getattr(shell, "label", "") or "")
        description = " ".join(part for part in (kind, state, label) if part)
        candidates.append(Candidate(gate_id, description))
        member = str(getattr(shell, "member_agent_name", "") or "")
        if member:
            candidates.append(Candidate(member, f"gate {gate_id}"))
    return dedupe(candidates)


def tool_run_source_path(_project: str | None) -> Path | None:
    """Return the ToolRun ledger whose mtime invalidates run ids."""
    from sase.core.tool_run import tool_run_store_path

    try:
        return tool_run_store_path()
    except Exception:
        return None


def tool_run_candidates(project: str | None) -> list[Candidate]:
    """Return recent ToolRun ids, described by tool and state."""
    from sase.core.tool_run import tool_run_list

    payload: dict[str, object] = {"schema_version": 1, "limit": 200}
    if project is not None:
        payload["project"] = project
    try:
        envelope = tool_run_list(payload)
    except Exception:
        return []
    if not isinstance(envelope, dict):
        return []
    raw_runs = envelope.get("runs")
    if raw_runs is None:
        raw_runs = envelope.get("tool_runs")
    if not isinstance(raw_runs, list):
        return []
    candidates: list[Candidate] = []
    for item in raw_runs:
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("run_id") or item.get("id") or "")
        if not run_id:
            continue
        tool = str(item.get("tool") or item.get("tool_name") or "")
        state = str(item.get("state") or item.get("status") or "")
        candidates.append(
            Candidate(run_id, " ".join(part for part in (tool, state) if part))
        )
    return dedupe(candidates)


def task_type_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: task types are compiled in."""
    return None


def task_type_candidates(_project: str | None) -> list[Candidate]:
    """Return every task-type slug in the effective registry, with summaries."""
    from sase.task_types.registry import get_task_type_registry

    try:
        registry = get_task_type_registry()
    except Exception:
        return []
    records = getattr(registry, "records", ())
    candidates: list[Candidate] = []
    for record in records:
        slug = str(getattr(record, "task_type", "") or "")
        if not slug:
            continue
        spec = getattr(record, "spec", None)
        summary = ""
        label = ""
        if isinstance(spec, Mapping):
            try:
                summary = str(spec.get("summary") or "")
                label = str(spec.get("label") or "")
            except Exception:
                summary = ""
        description = f"{label}: {summary}" if label and summary else (label or summary)
        candidates.append(Candidate(slug, description))
    return dedupe(candidates)


__all__ = [
    "gate_candidates",
    "gate_source_path",
    "task_type_candidates",
    "task_type_source_path",
    "tool_run_candidates",
    "tool_run_source_path",
]
