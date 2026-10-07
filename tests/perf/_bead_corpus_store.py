"""Deterministic synthetic bead store generation for benchmarks."""

from __future__ import annotations

import json
import os
import random
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

from tests.perf._bead_corpus_beads import BeadSpec, schedule_bead
from tests.perf._bead_corpus_common import bead_slug
from tests.perf._bead_corpus_events import mint_stream_lines

__all__ = [
    "BASE_PLANS",
    "BASE_TASKS",
    "CLOSED_PHASE_FRACTION",
    "CLOSED_PLAN_FRACTION",
    "CLOSED_TASK_FRACTION",
    "LIVE_EPIC_COUNT",
    "MAX_PHASES_PER_EPIC",
    "MIN_PHASES_PER_EPIC",
    "TIMELINE_DAYS",
    "export_projection",
    "generate_corpus",
    "git_commit",
    "summarize_corpus",
]

# Base counts at scale 1x, matching the production store shape the research
# report measured: ~7,000 beads, ~2,100 streams, ~48,000 events.
BASE_PLANS = 900
BASE_TASKS = 1100
MIN_PHASES_PER_EPIC = 4
MAX_PHASES_PER_EPIC = 7

# Share of each bead kind that ends up closed (~91.6% overall at 1x).
CLOSED_PLAN_FRACTION = 1.0  # minus the protected live epics below
CLOSED_PHASE_FRACTION = 0.94
CLOSED_TASK_FRACTION = 0.80

# Live epics that stay open while carrying closed phases.
LIVE_EPIC_COUNT = 60

# Corpus timeline: creations spread over this many days from the common epoch.
TIMELINE_DAYS = 400

_ACTORS = tuple(f"synth.agent.{idx:02d}" for idx in range(16))
_TASK_TYPES = ("bug", "feature", "flake", "memory", "ci")
_SIZES = ("small", "medium", "large")

_TITLES = (
    "Refresh the pane snapshot path",
    "Remove the redundant store replay",
    "Tighten the freshness check interval",
    "Cover the renamed-prefix routing case",
    "Record the before/after stage timings",
    "Migrate the consumer onto the fingerprint",
)


def _title(rng: random.Random, bead_id: str) -> str:
    return f"{rng.choice(_TITLES)} [{bead_id}]"


def git_commit(directory: Path, message: str) -> None:
    """Create a git repo in *directory* with one commit on fixed dates."""
    env = {
        "GIT_AUTHOR_DATE": "2026-10-06T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-10-06T00:00:00Z",
    }
    base = [
        "git",
        "-c",
        "user.name=SASE Benchmark",
        "-c",
        "user.email=bench@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run(
        [*base, "init"],
        cwd=directory,
        check=True,
        capture_output=True,
        env={**dict(os.environ), **env},
    )
    subprocess.run(
        ["git", "config", "user.name", "SASE Benchmark"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "bench@example.invalid"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    subprocess.run([*base, "add", "-A"], cwd=directory, check=True, capture_output=True)
    subprocess.run(
        [*base, "commit", "-m", message],
        cwd=directory,
        check=True,
        capture_output=True,
        env={**dict(os.environ), **env},
    )


def export_projection(beads_dir: Path) -> None:
    import sase_core_rs

    sase_core_rs.bead_export_jsonl(str(beads_dir))


def generate_corpus(
    dest: str | Path,
    *,
    scale: float = 1.0,
    seed: int = 20261006,
    prefix: str = "bench",
    owner: str = "bench-owner@example.invalid",
) -> dict[str, Any]:
    """Write a deterministic synthetic bead store at *dest* and return it.

    *dest* is the beads directory itself (it holds ``config.json`` and
    ``events/``); it must not exist yet. The result is the measured
    :func:`summarize_corpus` shape plus the generation parameters.
    """
    dest = Path(dest)
    if dest.exists():
        raise ValueError(f"refusing to generate into existing {dest}")
    rng = random.Random(seed)
    n_plans = max(1, round(BASE_PLANS * scale))
    n_tasks = max(0, round(BASE_TASKS * scale))

    plan_ids = [f"{prefix}-{num}" for num in range(1, n_plans + 1)]
    task_ids = [f"{prefix}-{n_plans + num}" for num in range(1, n_tasks + 1)]
    phases_by_epic: dict[str, list[str]] = {}
    for epic in plan_ids:
        count = rng.randint(MIN_PHASES_PER_EPIC, MAX_PHASES_PER_EPIC)
        phases_by_epic[epic] = [f"{epic}.{num}" for num in range(1, count + 1)]

    live_count = min(LIVE_EPIC_COUNT, max(1, n_plans // 3))
    live_epics = set(plan_ids[-live_count:])

    close_plan = {epic: (epic not in live_epics) for epic in plan_ids}
    close_phase = {
        phase: rng.random() < CLOSED_PHASE_FRACTION
        for phases in phases_by_epic.values()
        for phase in phases
    }
    close_task = {task: rng.random() < CLOSED_TASK_FRACTION for task in task_ids}
    closed_tasks = [task for task, shut in close_task.items() if shut]
    removed: set[str] = set(
        rng.sample(closed_tasks, k=max(1, round(0.003 * len(closed_tasks))))
        if closed_tasks
        else []
    )

    # Creation slots in iteration order keep every parent older than its
    # children and every dependency target older than its dependent.
    step = (TIMELINE_DAYS * 86400) / max(
        1, n_plans + n_tasks + sum(len(ph) for ph in phases_by_epic.values())
    )
    slot = [0]
    note_counter = [0]
    ext_counter = [0]

    def claim_slot() -> timedelta:
        slot[0] += 1
        jitter = rng.randint(0, 3600)
        return timedelta(seconds=slot[0] * step + jitter)

    specs: list[BeadSpec] = []
    stream_items: dict[str, list[Any]] = {}
    seq = [0]

    def schedule(
        bead_id: str,
        kind: str,
        parent_id: str | None,
        created: timedelta,
        will_close: bool,
        dep_pool: list[str],
    ) -> None:
        actor = rng.choice(_ACTORS)
        title = _title(rng, bead_id)
        description = (
            f"Synthetic {kind} {bead_id} for scaled-corpus benchmarks."
            if rng.random() < 0.7
            else ""
        )
        design = ""
        if kind == "plan" and rng.random() < 0.3:
            design = f"plan:202610/synth_{bead_slug(bead_id)}.md"
        size = rng.choice(_SIZES) if kind in ("phase", "task") else None
        task_type = rng.choice(_TASK_TYPES) if kind == "task" else None
        external_ref = ""
        if kind == "task" and rng.random() < 0.10:
            ext_counter[0] += 1
            external_ref = f"bench-ext-{ext_counter[0]:05d}"
        spec = BeadSpec(bead_id, kind, parent_id, created, actor)
        schedule_bead(
            rng,
            spec,
            dep_pool=dep_pool,
            will_close=will_close,
            title=title,
            description=description,
            design=design,
            size=size,
            task_type=task_type,
            external_ref=external_ref,
            owner=owner,
            note_counter=note_counter,
            ext_counter=ext_counter,
        )
        if bead_id in removed:
            last = max(when for when, _op, _args in spec.events)
            spec.events.append((last + timedelta(days=1), "issue_removed", {}))
        if kind == "phase":
            assert parent_id is not None
            stream_id = parent_id
        else:
            stream_id = bead_id
        bucket = stream_items.setdefault(stream_id, [])
        for when, operation, args in spec.events:
            seq[0] += 1
            bucket.append((when, seq[0], bead_id, actor, operation, args))
        specs.append(spec)

    dep_pool: list[str] = []
    for epic in plan_ids:
        created = claim_slot()
        schedule(epic, "plan", None, created, close_plan[epic], list(dep_pool))
        dep_pool.append(epic)
        for phase in phases_by_epic[epic]:
            schedule(
                phase,
                "phase",
                epic,
                created + timedelta(hours=1) + timedelta(seconds=rng.randint(0, 5400)),
                close_phase[phase],
                list(dep_pool),
            )
            dep_pool.append(phase)
    for task in task_ids:
        schedule(task, "task", None, claim_slot(), close_task[task], list(dep_pool))
        dep_pool.append(task)

    streams_dir = dest / "events" / "streams"
    streams_dir.mkdir(parents=True)
    note_ids: dict[tuple[str, int], str] = {}
    for stream_id in sorted(stream_items):
        lines = mint_stream_lines(stream_id, stream_items[stream_id], note_ids)
        (streams_dir / f"{stream_id}.jsonl").write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8"
        )
    manifest = {
        "schema_version": 1,
        "stream_count": len(stream_items),
        "generated_from": "issues.jsonl",
        "migration_tool": "sase-core bead events",
    }
    (dest / "events" / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "config.json").write_text(
        json.dumps(
            {
                "issue_prefix": prefix,
                "next_counter": n_plans + n_tasks + 1,
                "owner": owner,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (dest / "beads.db").write_bytes(b"")
    export_projection(dest)
    git_commit(dest, f"Synthetic bead corpus scale={scale} seed={seed}")
    shape = summarize_corpus(dest)
    shape.update(
        {
            "scale": scale,
            "seed": seed,
            "prefix": prefix,
            "live_epics": len(live_epics),
            "removed": len(removed),
        }
    )
    return shape


def summarize_corpus(beads_dir: str | Path) -> dict[str, Any]:
    """Measure a bead store's shape: bead/type/closed counts plus I/O size."""
    import sase_core_rs

    beads_dir = Path(beads_dir)
    issues = sase_core_rs.bead_read_store(str(beads_dir))
    by_type: dict[str, int] = {}
    closed = 0
    for issue in issues:
        by_type[issue["issue_type"]] = by_type.get(issue["issue_type"], 0) + 1
        if issue["status"] == "closed":
            closed += 1
    streams_dir = beads_dir / "events" / "streams"
    stream_files = sorted(streams_dir.glob("*.jsonl"))
    events = 0
    size_bytes = 0
    for path in stream_files:
        size_bytes += path.stat().st_size
        with open(path, encoding="utf-8") as handle:
            for _ in handle:
                events += 1
    config = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    total = len(issues)
    return {
        "beads": total,
        "plans": by_type.get("plan", 0),
        "phases": by_type.get("phase", 0),
        "tasks": by_type.get("task", 0),
        "closed": closed,
        "closed_fraction": (closed / total) if total else 0.0,
        "streams": len(stream_files),
        "events": events,
        "events_per_bead": (events / total) if total else 0.0,
        "stream_bytes": size_bytes,
        "prefix": config.get("issue_prefix", ""),
    }
