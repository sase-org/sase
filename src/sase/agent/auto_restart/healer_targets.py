"""Healer target resolution: CLI selection and pending sweep enumeration."""

from __future__ import annotations

from pathlib import Path

from sase.agent.auto_restart._healer_common import HealerTarget, read_json


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


def resolve_pending_targets() -> list[HealerTarget]:
    """Enumerate doorbells plus recent failed rows (shared with the job)."""
    from sase.agent.auto_restart.history import collect_failed_candidates
    from sase.agent.auto_restart.ledger import delete_doorbell, list_doorbells

    targets: list[HealerTarget] = []
    seen: set[str] = set()
    for doorbell in list_doorbells():
        raw = doorbell.get("artifacts_dir")
        if not raw:
            continue
        path = Path(str(raw))
        if not (path / "done.json").is_file():
            delete_doorbell(str(doorbell.get("doorbell_path", "")))
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            targets.append(_target_for_artifacts_dir(path))
        except Exception:
            continue
    try:
        candidates = collect_failed_candidates(since_seconds=7 * 86400)
    except Exception:
        candidates = []
    for candidate in candidates:
        if candidate.artifacts_dir is None:
            continue
        key = str(candidate.artifacts_dir)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            HealerTarget(
                artifacts_dir=candidate.artifacts_dir,
                project=candidate.project,
                agent_name=candidate.name,
                died_at=candidate.died_at,
            )
        )
    return _order_targets(targets)


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

    def depth(target: HealerTarget) -> int:
        meta = read_json(target.artifacts_dir / "agent_meta.json") or {}
        waits = meta.get("wait_for") or meta.get("depends_on") or []
        if isinstance(waits, (list, tuple)):
            return len(waits)
        return 0

    def progress(target: HealerTarget) -> float:
        try:
            return target.artifacts_dir.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(targets, key=lambda t: (depth(t), progress(t)))


__all__ = [
    "resolve_pending_targets",
    "resolve_targets",
]
