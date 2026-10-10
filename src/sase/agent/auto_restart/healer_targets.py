"""Healer target resolution: CLI selection and pending sweep enumeration.

Pending enumeration (``run -p`` and the scheduler job) considers only
healer candidates (see :func:`is_healer_candidate`): doorbell rows,
in-flight recovery rows, skew-suspect rows, and recent legacy
skew-shaped rows. Dismissed bundles are never candidates; the
read-only ``scan`` path still reads them.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.auto_restart._healer_common import HealerTarget, read_json
from sase.axe.runner_auto_restart_doorbell import IN_FLIGHT_RECOVERY_STATES

#: Failed rows older than this are never enumerated from history. In-flight
#: and skew-suspect rows stay eligible across the window; legacy rows get
#: the tighter ``max_defer_seconds`` bound inside :func:`is_healer_candidate`.
_HISTORY_LOOKBACK_SECONDS = 7 * 86400


@dataclass(frozen=True)
class _RecentRow:
    """One recent failed row from either enumeration source."""

    artifacts_dir: Path
    project: str
    agent_name: str
    died_at: float | None
    done: dict[str, Any]


def resolve_targets(
    *,
    name: str | None = None,
    artifacts_dir: str | None = None,
    pending: bool = False,
) -> list[HealerTarget]:
    """Resolve CLI target selection into concrete healer targets."""
    if pending:
        return resolve_pending_targets()
    if artifacts_dir is not None:
        return [_target_for_artifacts_dir(Path(artifacts_dir))]
    if name is not None:
        from sase.agent.names._lookup_named import find_named_agent

        agent = find_named_agent(name)
        if agent is None:
            raise LookupError(f"No agent found with name '{name}'.")
        return [_target_for_artifacts_dir(Path(agent.artifacts_dir))]
    raise ValueError("one of NAME, --artifacts-dir, or --pending is required")


def is_healer_candidate(
    *,
    artifacts_dir: Path,
    done: Mapping[str, Any],
    has_doorbell: bool = False,
    now: float | None = None,
) -> bool:
    """Return whether a failed row may be claimed by the healer.

    A row is a candidate only when at least one holds:

    1. it has a doorbell;
    2. its ``done.json`` ``recovery.state`` is in flight (``pending``,
       ``deferred``, or ``launching``);
    3. its ``failure_facts.skew_suspect`` is true;
    4. it is a legacy row (no ``failure_facts`` and no ``recovery``) that
       died within ``max_defer_seconds`` and whose error, traceback, or
       runner-log tail matches the Tier 1-3 skew prefilter.

    Anything else gets no ledger record, no ``done.json`` write, and no
    notification.
    """
    if str(done.get("outcome", "")) != "failed":
        return False
    if has_doorbell:
        return True
    recovery = done.get("recovery")
    if isinstance(recovery, dict):
        if recovery.get("state") in IN_FLIGHT_RECOVERY_STATES:
            return True
    facts = done.get("failure_facts")
    if isinstance(facts, dict):
        return facts.get("skew_suspect") is True
    if isinstance(recovery, dict):
        # Legacy rows carry neither marker; a non-legacy row with recovery
        # but no facts already failed the in-flight check above.
        return False
    at = time.time() if now is None else now
    died_at = _row_died_at(done, artifacts_dir)
    if died_at is None or at - died_at > _max_defer_seconds():
        return False
    return _legacy_text_matches(done, artifacts_dir)


def target_was_silenced(target: HealerTarget, done: Mapping[str, Any]) -> bool:
    """Return whether the runner silenced this failure when it died.

    A row was silenced when its runner dropped a doorbell or wrote
    ``recovery.state = "pending"``; its failure notification went out
    silent. Only silenced rows may be re-surfaced or escalated loudly on
    decline — anything else already notified the user.
    """
    recovery = done.get("recovery")
    if isinstance(recovery, dict) and recovery.get("state") == "pending":
        return True
    try:
        from sase.agent.auto_restart import ledger as ledger_mod

        wanted = str(target.artifacts_dir)
        for doorbell in ledger_mod.list_doorbells():
            if str(doorbell.get("artifacts_dir")) == wanted:
                return True
    except Exception:
        pass
    return False


def resolve_pending_targets(*, now: float | None = None) -> list[HealerTarget]:
    """Enumerate healer candidates: doorbells plus recent skew-shaped rows."""
    from sase.agent.auto_restart.ledger import delete_doorbell, list_doorbells

    at = time.time() if now is None else now
    targets: list[HealerTarget] = []
    seen: set[str] = set()
    doorbell_dirs: set[str] = set()
    for doorbell in list_doorbells():
        raw = doorbell.get("artifacts_dir")
        if not raw:
            continue
        path = Path(str(raw))
        if not (path / "done.json").is_file():
            delete_doorbell(str(doorbell.get("doorbell_path", "")))
            continue
        key = str(path)
        doorbell_dirs.add(key)
        if key in seen:
            continue
        seen.add(key)
        try:
            targets.append(_target_for_artifacts_dir(path))
        except Exception:
            continue
    try:
        rows = _recent_failure_rows(now=at)
    except Exception:
        rows = []
    for row in rows:
        key = str(row.artifacts_dir)
        if key in seen:
            continue
        seen.add(key)
        try:
            candidate = is_healer_candidate(
                artifacts_dir=row.artifacts_dir,
                done=row.done,
                has_doorbell=key in doorbell_dirs,
                now=at,
            )
        except Exception:
            continue
        if not candidate:
            continue
        targets.append(
            HealerTarget(
                artifacts_dir=row.artifacts_dir,
                project=row.project,
                agent_name=row.agent_name,
                died_at=row.died_at,
            )
        )
    return _order_targets(targets)


def _recent_failure_rows(*, now: float) -> list[_RecentRow]:
    """Return recent failed rows, preferring the bounded scan facade."""
    try:
        return _rows_via_scan(now=now)
    except Exception:
        pass
    return _rows_via_history(now=now)


def _rows_via_scan(*, now: float) -> list[_RecentRow]:
    """Enumerate recent failed rows through the artifact scan facade.

    The ``not_before_timestamp`` bound keeps the walk itself inside the
    lookback instead of walking every project's artifacts tree. Raises on
    any problem so the caller falls back to the history walk.
    """
    import datetime

    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.agent_scan_wire_records import AgentArtifactScanOptionsWire
    from sase.core.paths import sase_projects_dir
    from sase.core.time import get_timezone

    stamp = datetime.datetime.fromtimestamp(
        now - _HISTORY_LOOKBACK_SECONDS, tz=get_timezone()
    ).strftime("%Y%m%d%H%M%S")
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        include_workflow_state=False,
        include_waiting=False,
        not_before_timestamp=stamp,
        newest_first=True,
    )
    scan = scan_agent_artifacts(sase_projects_dir(), options)
    rows: list[_RecentRow] = []
    for record in scan.records:
        done_wire = record.done
        if done_wire is None or done_wire.outcome != "failed":
            continue
        artifacts_dir = Path(str(record.artifact_dir))
        done = read_json(artifacts_dir / "done.json") or {}
        if not done and done_wire is not None:
            done = {
                "outcome": done_wire.outcome,
                "error": done_wire.error,
                "traceback": done_wire.traceback,
                "finished_at": done_wire.finished_at,
            }
        name = (record.agent_meta.name if record.agent_meta else None) or (
            done_wire.name or artifacts_dir.name
        )
        finished = done.get("finished_at")
        died_at = (
            float(finished)
            if isinstance(finished, (int, float)) and not isinstance(finished, bool)
            else _row_died_at(done, artifacts_dir)
        )
        rows.append(
            _RecentRow(
                artifacts_dir=artifacts_dir,
                project=record.project_name,
                agent_name=str(name),
                died_at=died_at,
                done=dict(done),
            )
        )
    return rows


def _rows_via_history(*, now: float) -> list[_RecentRow]:
    """Enumerate recent failed rows through the read-only history walk."""
    from sase.agent.auto_restart.history import collect_failed_candidates

    rows: list[_RecentRow] = []
    candidates = collect_failed_candidates(
        since_seconds=_HISTORY_LOOKBACK_SECONDS, now=now
    )
    for candidate in candidates:
        # Dismissed bundles are never healer candidates.
        if candidate.source != "done" or candidate.artifacts_dir is None:
            continue
        done = candidate.done
        rows.append(
            _RecentRow(
                artifacts_dir=candidate.artifacts_dir,
                project=candidate.project,
                agent_name=candidate.name,
                died_at=candidate.died_at,
                done=dict(done) if isinstance(done, Mapping) else {},
            )
        )
    return rows


def _row_died_at(done: Mapping[str, Any], artifacts_dir: Path) -> float | None:
    finished = done.get("finished_at")
    if isinstance(finished, (int, float)) and not isinstance(finished, bool):
        return float(finished)
    try:
        from sase.agent.auto_restart.history import parse_artifact_stamp

        return parse_artifact_stamp(artifacts_dir.name)
    except Exception:
        return None


def _legacy_text_matches(done: Mapping[str, Any], artifacts_dir: Path) -> bool:
    """Return whether a legacy row's texts match the skew prefilter."""
    from sase.axe.runner_failure_facts import facts_look_like_update_skew

    error = done.get("error")
    traceback = done.get("traceback")
    texts = "\n".join(
        text for text in (error, traceback) if isinstance(text, str) and text
    )
    if texts and facts_look_like_update_skew({"error_text": texts}):
        return True
    tail = _runner_log_tail(done, artifacts_dir)
    return bool(tail) and facts_look_like_update_skew({"error_text": tail})


def _runner_log_tail(done: Mapping[str, Any], artifacts_dir: Path) -> str:
    """Read a legacy row's runner-log tail (empty when unavailable)."""
    try:
        from sase.agent.auto_restart.history import FailedCandidate, candidate_log_tail
        from sase.agent.auto_restart.inputs import find_runner_log
        from sase.core.paths import sase_subdir

        output_path = done.get("output_path")
        log_path = find_runner_log(
            artifacts_dir.name,
            output_path if isinstance(output_path, str) else None,
            sase_subdir("workflows"),
        )
        candidate = FailedCandidate(
            source="done",
            name=artifacts_dir.name,
            project="",
            died_at=None,
            artifacts_dir=artifacts_dir,
            done=dict(done),
            meta={},
            bundle=None,
            log_path=log_path,
        )
        return candidate_log_tail(candidate)
    except Exception:
        return ""


def _max_defer_seconds() -> float:
    try:
        from sase.config._settings_system import (
            get_agent_auto_restart_max_defer_seconds,
        )

        return float(get_agent_auto_restart_max_defer_seconds())
    except Exception:
        return 1800.0


def _target_for_artifacts_dir(artifacts_dir: Path) -> HealerTarget:
    from sase.agent.auto_restart.history import project_for_done

    done = read_json(artifacts_dir / "done.json") or {}
    meta = read_json(artifacts_dir / "agent_meta.json") or {}
    project = project_for_done(done, artifacts_dir)
    name = str(meta.get("name") or meta.get("workflow_name") or artifacts_dir.name)
    return HealerTarget(artifacts_dir=artifacts_dir, project=project, agent_name=name)


def _order_targets(targets: list[HealerTarget]) -> list[HealerTarget]:
    """Dependencies before dependents, then least progress first.

    Correctness never depends on this order (waiters stay parked on a
    failed dependency); it only makes the sweep read sensibly.
    """
    import heapq

    names: dict[str, int] = {}
    for index, target in enumerate(targets):
        names.setdefault(target.agent_name, index)

    dependencies: list[set[int]] = []
    dependents: list[set[int]] = [set() for _ in targets]
    for index, target in enumerate(targets):
        waiting = read_json(target.artifacts_dir / "waiting.json") or {}
        raw_waits = waiting.get("waiting_for")
        if not isinstance(raw_waits, list):
            meta = read_json(target.artifacts_dir / "agent_meta.json") or {}
            raw_waits = meta.get("waiting_for") or meta.get("wait_for") or []
        waits = (
            {
                names[name]
                for name in raw_waits
                if isinstance(name, str) and name in names
            }
            if isinstance(raw_waits, (list, tuple))
            else set()
        )
        waits.discard(index)
        dependencies.append(waits)
        for dependency in waits:
            dependents[dependency].add(index)

    def progress(target: HealerTarget) -> float:
        try:
            return target.artifacts_dir.stat().st_mtime
        except OSError:
            return 0.0

    ready = [
        (progress(target), index)
        for index, target in enumerate(targets)
        if not dependencies[index]
    ]
    heapq.heapify(ready)
    ordered: list[HealerTarget] = []
    emitted: set[int] = set()
    while ready:
        _, index = heapq.heappop(ready)
        if index in emitted:
            continue
        emitted.add(index)
        ordered.append(targets[index])
        for dependent in dependents[index]:
            dependencies[dependent].discard(index)
            if not dependencies[dependent]:
                heapq.heappush(ready, (progress(targets[dependent]), dependent))

    # A malformed or cyclic wait graph must not hide healer targets.
    ordered.extend(
        target
        for _, _, target in sorted(
            (progress(target), index, target)
            for index, target in enumerate(targets)
            if index not in emitted
        )
    )
    return ordered


__all__ = [
    "is_healer_candidate",
    "resolve_pending_targets",
    "resolve_targets",
    "target_was_silenced",
]
