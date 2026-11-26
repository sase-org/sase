"""Find named agents and the most recently created agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.names._common import (
    NamedAgent,
    is_dismissed_prefixed,
    is_process_alive,
)
from sase.agent.names._lookup_artifacts import (
    iter_ace_run_artifact_dirs,
    projects_root,
)
from sase.core.index_lookup_errors import IndexLookupUnavailable


class AgentNamedLookupUnavailable(IndexLookupUnavailable):
    """A bounded named lookup could not prove a winner or a miss."""

    def __init__(
        self,
        *,
        availability: str,
        source: str,
        diagnostic: str | None,
        truncated: bool = False,
    ) -> None:
        detail = [f"availability={availability}", f"source={source}"]
        if diagnostic:
            detail.append(diagnostic)
        super().__init__(
            "agent name lookup is incomplete (" + "; ".join(detail) + ")",
            availability=availability,
            source=source,
            diagnostic=diagnostic,
            truncated=truncated,
        )


def find_named_agent(
    name: str,
    *,
    only_done: bool = False,
    include_dead: bool = False,
) -> NamedAgent | None:
    """Find a named agent via indexed exact name/workflow queries.

    Delegates candidate discovery to the Rust-backed targeted artifact lookup
    (:func:`sase.core.agent_artifact_lookup.lookup_agent_artifacts`) instead
    of scanning every project artifact, and falls back to the dismissed-bundle
    archive index instead of recursively walking bundle JSON files. Only
    matching artifact directories and the newest usable bundle candidate are
    revalidated on disk; unrelated archive records are never hydrated.

    Prefers running (non-done) agents over completed ones. Exact ``name``
    matches take priority over ``workflow_name`` matches. Among workflow
    matches, the most recent (by timestamp) is preferred.

    Args:
        name: The agent name to search for.
        only_done: When True, ignore running candidates and return only
            historical/done matches.
        include_dead: When True, include non-done records whose recorded
            process is no longer alive. Restart uses this for crashed agents;
            wait resolution keeps the default liveness filter.

    Returns:
        A NamedAgent if found, or None.

    Raises:
        AgentNamedLookupUnavailable: If bounded recovery cannot prove a winner
            or a miss.
    """
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    return _find_named_agent_candidates(
        current_owner_agent_name_lookup_candidates(name),
        only_done=only_done,
        include_dead=include_dead,
    )


def _find_named_agent_candidates(
    names: tuple[str, ...],
    *,
    only_done: bool = False,
    include_dead: bool = False,
) -> NamedAgent | None:
    """Find a complete exact-first answer from artifact and bundle indexes."""
    from sase.core.agent_artifact_lookup import lookup_agent_artifacts
    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactLookupQueryWire,
        AgentArtifactLookupTargetWire,
        NamedAgentObservationWire,
    )
    from sase.core.agent_scan_facade import default_agent_artifact_index_path
    from sase.core.agent_named_selection import select_named_agent

    projects_dir = projects_root()
    query = AgentArtifactLookupQueryWire(
        target=AgentArtifactLookupTargetWire(kind="names", names=names),
        include_hidden=True,
    )
    try:
        result = lookup_agent_artifacts(
            default_agent_artifact_index_path(), projects_dir, query
        )
    except Exception as exc:
        raise AgentNamedLookupUnavailable(
            availability="corrupt",
            source="artifact_index",
            diagnostic=str(exc),
        ) from exc
    if not result.complete:
        raise AgentNamedLookupUnavailable(
            availability=result.availability,
            source=result.source,
            diagnostic=result.diagnostic,
            truncated=result.truncated,
        )

    observations = tuple(
        NamedAgentObservationWire(
            artifact_dir=hit.artifact_dir,
            process_alive=(
                is_process_alive(
                    _read_meta_for_liveness(Path(hit.artifact_dir)),
                    Path(hit.artifact_dir),
                )
                if not hit.has_done_marker
                else False
            ),
            done_outcome=(
                _read_done_outcome(Path(hit.artifact_dir))
                if hit.has_done_marker
                else None
            ),
        )
        for hit in result.hits
    )

    try:
        selections = select_named_agent(
            names,
            result.hits,
            observations,
            only_done=only_done,
            include_dead=include_dead,
        ).selections
    except Exception as exc:
        raise AgentNamedLookupUnavailable(
            availability="corrupt",
            source="named_selection",
            diagnostic=str(exc),
        ) from exc
    if len(selections) != len(names):
        raise AgentNamedLookupUnavailable(
            availability="corrupt",
            source="named_selection",
            diagnostic="Rust selector returned the wrong number of spellings",
        )

    for name, selected in zip(names, selections, strict=True):
        if selected is not None:
            return NamedAgent(
                name=selected.requested_name,
                artifacts_dir=selected.hit.artifact_dir,
                is_done=selected.is_done,
                outcome=selected.outcome,
            )

        bundle = _find_named_dismissed_bundle(name)
        if bundle is not None:
            return bundle
    return None


def _read_done_outcome(artifact_dir: Path) -> str | None:
    """Return the ``outcome`` from ``done.json``, or None when absent."""
    try:
        with open(artifact_dir / "done.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    outcome = data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _read_meta_for_liveness(artifact_dir: Path) -> dict[str, Any]:
    """Read ``agent_meta.json`` liveness fields for one matching directory."""
    try:
        with open(artifact_dir / "agent_meta.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    pid = data.get("pid")
    if isinstance(pid, int):
        out["pid"] = pid
    stopped_at = data.get("stopped_at")
    if stopped_at is not None:
        out["stopped_at"] = stopped_at
    process_identity = data.get("process_identity")
    if process_identity is not None:
        out["process_identity"] = process_identity
    return out


def _find_named_dismissed_bundle(name: str) -> NamedAgent | None:
    """Return a dismissed-bundle match for *name*, or ``None``.

    Queries the dismissed-bundle archive index for a bundle whose source
    ``agent_name`` or ``workflow_name`` equals *name* (all visibilities,
    including workflow children), hydrating matching candidates in legacy
    order until a usable bundle is found. Used when artifact directories no
    longer carry the metadata (e.g. dismissed agents whose artifact dir was
    cleaned up). An unusable index uses bounded Rust recovery.
    """
    from sase.core.dismissed_agents_facade import dismissed_bundles_dir
    from sase.core.dismissed_bundle_lookup import lookup_named_dismissed_bundle

    try:
        lookup = lookup_named_dismissed_bundle(dismissed_bundles_dir(), name)
    except Exception as exc:
        raise AgentNamedLookupUnavailable(
            availability="corrupt",
            source="dismissed_bundle_index",
            diagnostic=str(exc),
        ) from exc
    if not lookup.complete:
        raise AgentNamedLookupUnavailable(
            availability=lookup.availability,
            source=lookup.source,
            diagnostic=lookup.diagnostic,
            truncated=lookup.truncated,
        )
    if lookup.winner is None:
        return None
    return NamedAgent(
        name=name,
        artifacts_dir=lookup.winner.artifacts_dir,
        is_done=True,
        outcome="dismissed",
    )


def get_most_recent_agent_name(
    *, exclude_artifacts_dir: str | Path | None = None
) -> str | None:
    """Return the name of the most recently created named agent.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for agents with a name, ordered by artifact directory timestamp
    (directory names are timestamps).

    Args:
        exclude_artifacts_dir: Optional artifact directory to ignore. Used by
            bare ``#fork`` resolution so a workflow does not select its own
            just-written metadata as the most recent agent.

    Returns the name of the most recently created one, or ``None`` if no named
    agents exist.
    """
    projects_dir = projects_root()
    if not projects_dir.exists():
        return None

    excluded: Path | None = None
    if exclude_artifacts_dir:
        excluded = Path(exclude_artifacts_dir).expanduser().resolve(strict=False)

    candidates: list[tuple[str, str]] = []  # (dir_name, agent_name)
    for artifact_dir in iter_ace_run_artifact_dirs():
        if excluded is not None:
            candidate_dir = artifact_dir.expanduser().resolve(strict=False)
            if candidate_dir == excluded:
                continue

        meta_path = artifact_dir / "agent_meta.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        name = data.get("name")
        if not name:
            continue

        # Bare ``%wait`` should never resolve to a dismissed historical
        # agent. Dismissal-prefixed names (``YYmmdd.foo``) are reserved
        # for explicit references (``%w:260428.foo``); skip them so the
        # bare-wait path stays anchored on visible/active agents.
        if isinstance(name, str) and is_dismissed_prefixed(name):
            continue

        candidates.append((artifact_dir.name, name))

    if not candidates:
        return None

    # Sort by directory name descending — most recent first
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
