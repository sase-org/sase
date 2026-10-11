"""Identity keys and row selection for scoped wait-dependency views."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_session_base,
    agent_session_phase_name,
    agent_session_parallel_value,
    agent_session_value,
    canonical_plan_chain_suffix,
)

from ._artifact_state import agent_session_base_from_meta, artifact_dir_key

ArtifactRow = tuple[Path, dict[str, Any], str]


@dataclass(frozen=True)
class _RowIdentity:
    """The keys one artifact row contributes to a dependency index."""

    name: str | None
    workflow_name: str | None
    agent_session_name: str | None
    indexed_agent_session_name: str | None
    clan_name: str | None
    planner_row_name: str | None


def artifact_row_identity(meta: Mapping[str, Any]) -> _RowIdentity:
    name_value = meta.get("name")
    name = name_value if isinstance(name_value, str) else None

    workflow_value = meta.get("workflow_name")
    workflow_name = workflow_value if isinstance(workflow_value, str) else None

    agent_session_name = agent_session_base_from_meta(dict(meta))
    # _add_prepared only files a session key from inside the workflow-name
    # branch. Keep that exact indexing condition here so the scope key set
    # matches the index's queryable keys.
    indexed_agent_session_name = (
        agent_session_name if workflow_name is not None else None
    )

    clan_value = meta.get("agent_clan")
    clan_name = clan_value if isinstance(clan_value, str) and clan_value else None
    if clan_name is None:
        # Legacy agent-family metadata used the parallel session as its clan.
        session_name = agent_session_value(meta)
        if (
            agent_session_parallel_value(meta) is True
            and isinstance(session_name, str)
            and session_name
        ):
            clan_name = session_name

    planner_row_name: str | None = None
    if (
        canonical_plan_chain_suffix(meta.get("role_suffix")) == PLAN_CHAIN_PLAN_SUFFIX
        and name
    ):
        base_name = agent_session_base(name) or name
        try:
            planner_row_name = agent_session_phase_name(
                base_name,
                PLAN_CHAIN_PLAN_SUFFIX,
            )
        except ValueError:
            planner_row_name = None

    return _RowIdentity(
        name=name,
        workflow_name=workflow_name,
        agent_session_name=agent_session_name,
        indexed_agent_session_name=indexed_agent_session_name,
        clan_name=clan_name,
        planner_row_name=planner_row_name,
    )


def artifact_scope_keys(meta: Mapping[str, Any]) -> frozenset[str]:
    """Return all index identity keys for *meta*, plus planner-row aliases.

    The planner key is deliberately a superset: it is included based on meta
    alone, even when the row is not currently submitted or has no plan path.
    That can select extra rows, but cannot omit a row that the index might
    expose as a submitted planner.
    """
    identity = artifact_row_identity(meta)
    keys = {
        value
        for value in (
            identity.name,
            identity.workflow_name,
            identity.indexed_agent_session_name,
            identity.clan_name,
            identity.planner_row_name,
        )
        if value is not None
    }
    return frozenset(keys)


def marker_scope_keys(marker: Mapping[str, Any]) -> frozenset[str] | None:
    """Return the named identity keys needed by a marker, or ``None``.

    ``None`` marks shapes that query a global or otherwise non-name-keyed
    index structure and therefore need the full view.
    """
    for field_name in (
        "wait_for_artifacts",
        "wait_for_fork_sources",
        "wait_for_hoods",
        "wait_for_epics_of",
        "wait_epic_follows",
    ):
        if marker.get(field_name):
            return None

    raw_waiting_for = marker.get("waiting_for")
    waiting_for = raw_waiting_for if isinstance(raw_waiting_for, list) else ()
    keys: set[str] = set()
    for name in waiting_for:
        if not isinstance(name, str) or name.startswith("@"):
            return None
        keys.add(name)
        alias = _planner_row_alias(name)
        if alias is not None and alias != name:
            keys.add(alias)
    return frozenset(keys)


def select_scope_rows(
    rows: Iterable[ArtifactRow],
    keys: Iterable[str],
    *,
    include_dirs: Iterable[str | Path],
) -> list[ArtifactRow]:
    """Select rows intersecting *keys* and always retain *include_dirs*."""
    selected_keys = frozenset(keys)
    included_dirs = {artifact_dir_key(str(path)) for path in include_dirs}
    selected: list[ArtifactRow] = []
    for row in rows:
        artifact_dir, meta, _project_name = row
        if artifact_dir_key(
            str(artifact_dir)
        ) in included_dirs or not selected_keys.isdisjoint(artifact_scope_keys(meta)):
            selected.append(row)
    return selected


def _planner_row_alias(name: str) -> str | None:
    """Return the canonical planner key for a legacy planner wait name."""
    from sase.plan_chain import planner_row_name

    return planner_row_name(name, include_legacy_dash=True)
