"""Find named agents and the most recently created agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.names._common import (
    NamedAgent,
    is_dismissed_prefixed,
    is_process_alive,
)
from sase.agent.names._lookup_artifacts import (
    iter_ace_run_artifact_dirs,
    projects_root,
)

if TYPE_CHECKING:
    from sase.core.agent_artifact_lookup_wire import AgentArtifactLookupHitWire

_BUNDLE_FALLBACK_BUDGET = 200


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
    matching artifact directories are revalidated on disk; unrelated archive
    records are never hydrated.

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
    """Find exact-first durable spellings from indexed lookups."""
    from sase.core.agent_artifact_lookup import lookup_agent_artifacts
    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactLookupQueryWire,
        AgentArtifactLookupTargetWire,
    )
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    projects_dir = projects_root()
    if not projects_dir.exists():
        for name in names:
            if (bundle := _find_named_dismissed_bundle(name)) is not None:
                return bundle
        return None

    query = AgentArtifactLookupQueryWire(
        target=AgentArtifactLookupTargetWire(kind="names", names=names),
        include_hidden=True,
    )
    result = lookup_agent_artifacts(
        default_agent_artifact_index_path(), projects_dir, query
    )
    best_by_name = _rank_indexed_hits(
        result.hits, names, only_done=only_done, include_dead=include_dead
    )

    for name in names:
        best = best_by_name.get(name)
        if best is not None:
            return best
        # After dismissal the artifact directory may be partially or fully
        # gone, but the bundle still carries the durable identity.
        if (bundle := _find_named_dismissed_bundle(name)) is not None:
            return bundle
    return None


def _rank_indexed_hits(
    hits: tuple[AgentArtifactLookupHitWire, ...],
    names: tuple[str, ...],
    *,
    only_done: bool,
    include_dead: bool,
) -> dict[str, NamedAgent]:
    """Rank indexed hits per spelling, preserving legacy ordering.

    Outer spelling order wins; within a spelling, live/nonterminal priority
    beats exact/workflow priority, which beats timestamp. Only matching
    artifact directories are touched on disk for liveness and outcome.
    """
    candidate_rank = {name: rank for rank, name in enumerate(names)}
    best_by_name: dict[str, tuple[tuple[int, int, str], NamedAgent]] = {}
    for hit in hits:
        if hit.workflow_dir_name != "ace-run":
            continue
        exact_name = hit.agent_name if hit.agent_name in candidate_rank else None
        workflow_name = (
            hit.workflow_name if hit.workflow_name in candidate_rank else None
        )
        matched_name: str | None
        exact: bool
        if exact_name is not None and (
            workflow_name is None
            or candidate_rank[exact_name] <= candidate_rank[workflow_name]
        ):
            matched_name = exact_name
            exact = True
        else:
            matched_name = workflow_name
            exact = False
        if matched_name is None:
            continue

        artifact_dir = Path(hit.artifact_dir)
        is_done = False
        outcome: str | None = None
        if hit.has_done_marker:
            is_done = True
            outcome = _read_done_outcome(artifact_dir)
        elif is_dismissed_prefixed(matched_name):
            # Dismissal removes done.json but preserves the prefixed
            # agent_meta.json. Treat such artifacts as historical so
            # `%w:260428.foo` and `#fork:260428.foo` still resolve.
            is_done = True
            outcome = "dismissed"

        agent = NamedAgent(
            name=matched_name,
            artifacts_dir=str(artifact_dir),
            is_done=is_done,
            outcome=outcome,
        )

        # Running agents take priority, but only if the process is actually
        # alive. Parent-phase artifacts (e.g. .plan) share the agent name yet
        # never write done.json; without a liveness check we'd return
        # them as "running" and block wait resolution forever.
        # For workflow matches, only return the root agent
        # (no parent_timestamp) to avoid matching intermediate steps.
        if not is_done:
            if only_done:
                continue
            if not exact and hit.parent_timestamp:
                continue
            is_alive = is_process_alive(
                _read_meta_for_liveness(artifact_dir), artifact_dir
            )
            if not is_alive and not include_dead:
                continue
            # Restart lookup orders the current running record first, then
            # the newest crash-killed record, then historical completions.
            # Ordinary lookup retains its previous live-over-done ordering.
            priority = (
                3 if include_dead and is_alive else 2,
                1 if exact else 0,
                hit.timestamp,
            )
        else:
            priority = (1, 1 if exact else 0, hit.timestamp)

        current = best_by_name.get(matched_name)
        if current is None or priority > current[0]:
            best_by_name[matched_name] = (priority, agent)

    return {name: agent for name, (_, agent) in best_by_name.items()}


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
    including workflow children), hydrating only the winning bundle file for
    its ``artifacts_dir``. Used as a fallback when artifact directories no
    longer carry the metadata (e.g. dismissed agents whose artifact dir was
    cleaned up). An unusable index takes a bounded newest-first bundle scan,
    never the old recursive walk.
    """
    try:
        from sase.ace import dismissed_agents
        from sase.ace.dismissed_bundle_index import query_summaries
    except Exception:
        return None

    bundles_dir = dismissed_agents.dismissed_bundles_dir()
    if not bundles_dir.is_dir():
        return None

    try:
        summaries = query_summaries(
            bundles_dir,
            agent_names={name},
            visibility=None,
        )
    except Exception:
        summaries = None
    if summaries is not None:
        return _bundle_winner_from_summaries(summaries, name, bundles_dir)
    return _find_named_dismissed_bundle_bounded(name, bundles_dir)


def _bundle_winner_from_summaries(
    summaries: Any, name: str, bundles_dir: Path
) -> NamedAgent | None:
    """Pick the newest indexed bundle match, preserving legacy ordering."""
    best: tuple[str, str] | None = None
    best_path: str | None = None
    for summary in summaries:
        if summary.agent_name != name and summary.workflow_name != name:
            continue
        raw_suffix = summary.raw_suffix or ""
        key = (raw_suffix, summary.filename or "")
        if best is not None and key <= best:
            continue
        best = key
        best_path = summary.bundle_path
    if best_path is None:
        return None
    return _named_agent_from_bundle_file(name, Path(best_path))


def _find_named_dismissed_bundle_bounded(
    name: str, bundles_dir: Path, budget: int = _BUNDLE_FALLBACK_BUDGET
) -> NamedAgent | None:
    """Bounded newest-first bundle scan for an unusable bundle index."""
    try:
        shards = sorted(
            (p for p in bundles_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return None
    try:
        top_files = sorted(
            (p for p in bundles_dir.iterdir() if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        top_files = []

    best: NamedAgent | None = None
    best_ts = ""
    visited = 0

    def _consider(path: Path) -> bool:
        nonlocal best, best_ts, visited
        if not path.is_file() or path.suffix != ".json":
            return False
        visited += 1
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return True
        if not isinstance(data, dict):
            return True
        if data.get("agent_name") != name and data.get("workflow_name") != name:
            return True
        raw_suffix = data.get("raw_suffix")
        ts = raw_suffix if isinstance(raw_suffix, str) else path.stem
        if ts <= best_ts:
            return True
        artifacts_dir = data.get("artifacts_dir")
        best = NamedAgent(
            name=name,
            artifacts_dir=str(artifacts_dir) if artifacts_dir else str(path.parent),
            is_done=True,
            outcome="dismissed",
        )
        best_ts = ts
        return True

    for path in top_files:
        if visited >= budget:
            break
        _consider(path)
    if visited < budget:
        for shard in shards:
            if visited >= budget:
                break
            try:
                files = sorted(
                    (p for p in shard.iterdir() if p.is_file()),
                    key=lambda p: p.name,
                    reverse=True,
                )
            except OSError:
                continue
            for path in files:
                if visited >= budget:
                    break
                _consider(path)
    return best


def _named_agent_from_bundle_file(name: str, path: Path) -> NamedAgent | None:
    """Hydrate the winning indexed bundle file for its ``artifacts_dir``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return NamedAgent(
            name=name,
            artifacts_dir=str(path.parent),
            is_done=True,
            outcome="dismissed",
        )
    if not isinstance(data, dict):
        return NamedAgent(
            name=name,
            artifacts_dir=str(path.parent),
            is_done=True,
            outcome="dismissed",
        )
    artifacts_dir = data.get("artifacts_dir")
    return NamedAgent(
        name=name,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else str(path.parent),
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
