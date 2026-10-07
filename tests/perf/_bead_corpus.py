"""Deterministic synthetic bead corpus with realistic shape at any scale.

This module backs the ``bench`` phase of the bead-store performance epic
(``sase-1h8.1``): it writes a valid event store (``events/manifest.json``,
``events/streams/*.jsonl``, ``config.json``) that the production reducer
accepts, so benchmarks measure replay cost on history-shaped data instead of
toy stores.

At scale 1x the corpus matches today's production shape: ~7,000 beads
(phase ~71%, task ~16%, plan ~13%), ~2,100 streams, ~48,000 events, and
~91.6% closed. Scale ``k`` multiplies the counts natively. Generation is
seeded and deterministic: the same ``(scale, seed, prefix)`` always yields
byte-identical store files (excluding the ``.git`` directory).

Event IDs are minted exactly as core does (``events/merge.rs``
``mint_bead_event_id``): ``{stream}:{ordinal:06}:{operation}:{issue}:{sha256}``
over the ``[schema_version, timestamp, actor, operation, issue_id, payload]``
tuple serialized as compact JSON. A probe test below pins this against a
core-minted event.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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

# Corpus timeline: creations spread over this many days from _EPOCH.
TIMELINE_DAYS = 400
_EPOCH = datetime(2025, 8, 1, tzinfo=UTC)

_ACTORS = tuple(f"synth.agent.{idx:02d}" for idx in range(16))
_REPORTERS = tuple(f"synth.reporter.{idx:02d}" for idx in range(24))
_TASK_TYPES = ("bug", "feature", "flake", "memory", "ci")
_SIZES = ("small", "medium", "large")
_LINK_RELATIONS = ("cites", "implements", "related")

_NOTE_OPENERS = (
    "Investigated the failure mode and captured the reproduction steps.",
    "Checked the current behavior against the documented contract.",
    "Narrowed the scope after reading the surrounding implementation.",
    "Recorded the decision and the alternatives that were rejected.",
    "Verified the fix against the regression suite and the manual path.",
    "Collected timings before changing anything on the hot path.",
)

_TITLES = (
    "Refresh the pane snapshot path",
    "Remove the redundant store replay",
    "Tighten the freshness check interval",
    "Cover the renamed-prefix routing case",
    "Record the before/after stage timings",
    "Migrate the consumer onto the fingerprint",
)


def _timestamp(offset: timedelta) -> str:
    moment = _EPOCH + offset
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def mint_event_id(
    stream_id: str,
    ordinal: int,
    timestamp: str,
    actor: str,
    operation: str,
    issue_id: str,
    payload: dict[str, Any],
) -> str:
    """Mint an event ID exactly as core's ``mint_bead_event_id`` does."""
    content = json.dumps(
        [1, timestamp, actor, operation, issue_id, payload],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    return f"{stream_id}:{ordinal:06d}:{operation}:{issue_id}:{digest}"


def _dump(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _created_issue(
    bead_id: str,
    kind: str,
    title: str,
    created: str,
    actor: str,
    owner: str,
    parent_id: str | None,
    description: str,
    design: str,
    size: str | None,
    task_type: str | None,
    external_ref: str,
) -> dict[str, Any]:
    """Build an ``issue_created`` issue body in core's serialization order."""
    issue: dict[str, Any] = {
        "id": bead_id,
        "title": title,
        "status": "open",
        "issue_type": kind,
    }
    if kind == "plan":
        issue["tier"] = "epic"
    issue["parent_id"] = parent_id
    issue["owner"] = owner
    issue["assignee"] = ""
    issue["created_at"] = created
    issue["created_by"] = actor
    issue["updated_at"] = created
    issue["closed_at"] = None
    issue["close_reason"] = None
    issue["description"] = description
    issue["design"] = design
    issue["model"] = ""
    if kind in ("phase", "task"):
        issue["size"] = size
    if kind == "task":
        issue["task_type"] = task_type
    issue["is_ready_to_work"] = False
    issue["changespec_name"] = ""
    issue["changespec_bug_id"] = ""
    if external_ref:
        issue["external_ref"] = external_ref
    issue["dependencies"] = []
    return issue


_UPDATE_FIELD_ORDER = (
    "title",
    "status",
    "assignee",
    "description",
    "notes",
    "design",
    "model",
    "size",
    "closed_at",
    "close_reason",
    "changespec_name",
    "changespec_bug_id",
    "external_ref",
    "tier",
    "is_ready_to_work",
)


def _updated_fields(
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build an ``issue_updated`` fields body in core's serialization order."""
    values = {"title": title, "description": description}
    return {name: values.get(name) for name in _UPDATE_FIELD_ORDER}


def _note_text(rng: random.Random, bead_id: str, counter: int) -> str:
    opener = rng.choice(_NOTE_OPENERS)
    return f"{opener} [{bead_id} note {counter}]"


def _title(rng: random.Random, bead_id: str) -> str:
    return f"{rng.choice(_TITLES)} [{bead_id}]"


class _BeadSpec:
    """One synthetic bead and its scheduled (unsorted) stream events."""

    __slots__ = ("bead_id", "kind", "parent_id", "created", "actor", "events")

    def __init__(
        self,
        bead_id: str,
        kind: str,
        parent_id: str | None,
        created: timedelta,
        actor: str,
    ) -> None:
        self.bead_id = bead_id
        self.kind = kind
        self.parent_id = parent_id
        self.created = created
        self.actor = actor
        # (timestamp, kind-tag, payload-builder-args) in schedule order.
        self.events: list[tuple[timedelta, str, dict[str, Any]]] = []


def _slug(bead_id: str) -> str:
    return bead_id.replace(".", "_")


def _schedule_bead(
    rng: random.Random,
    spec: _BeadSpec,
    *,
    dep_pool: list[str],
    will_close: bool,
    title: str,
    description: str,
    design: str,
    size: str | None,
    task_type: str | None,
    external_ref: str,
    owner: str,
    note_counter: list[int],
    ext_counter: list[int],
) -> bool:
    """Schedule a bead's creation plus its lifetime events.

    Returns whether the bead ends up closed. ``note_counter``/``ext_counter``
    are single-item lists used as mutable counters shared across beads.
    """
    clock = [spec.created]

    def advance(lo_s: int, hi_s: int) -> timedelta:
        clock[0] += timedelta(seconds=rng.randint(lo_s, hi_s))
        return clock[0]

    created_issue = _created_issue(
        spec.bead_id,
        spec.kind,
        title,
        _timestamp(spec.created),
        spec.actor,
        owner,
        spec.parent_id,
        description,
        design,
        size,
        task_type,
        external_ref,
    )
    spec.events.append((spec.created, "issue_created", {"issue": created_issue}))

    note_nos: list[int] = []
    dep_targets = [cand for cand in dep_pool if cand != spec.bead_id]
    for _ in range(rng.choices((0, 1, 2, 3, 4), weights=(6, 14, 26, 28, 26))[0]):
        note_counter[0] += 1
        note_nos.append(note_counter[0])
        spec.events.append(
            (
                advance(3600, 5 * 86400),
                "note_appended",
                {
                    "entry": _note_text(rng, spec.bead_id, note_counter[0]),
                    "note_no": note_counter[0],
                },
            )
        )
    if rng.random() < 0.40:
        if rng.random() < 0.5:
            spec.events.append(
                (
                    advance(7200, 10 * 86400),
                    "issue_updated",
                    {"title": f"{title} (rev 2)", "description": None},
                )
            )
        else:
            spec.events.append(
                (
                    advance(7200, 10 * 86400),
                    "issue_updated",
                    {
                        "title": None,
                        "description": (
                            f"Follow-up scope for {spec.bead_id}: "
                            f"{rng.choice(_NOTE_OPENERS)}"
                        ),
                    },
                )
            )
    if dep_targets and rng.random() < (0.30 if spec.kind == "phase" else 0.25):
        for depends_on in rng.sample(
            dep_targets, k=min(len(dep_targets), rng.choice((1, 1, 2, 2, 3)))
        ):
            spec.events.append(
                (
                    advance(3600, 10 * 86400),
                    "dependency_added",
                    {"depends_on_id": depends_on},
                )
            )
    if rng.random() < 0.20:
        spec.events.append(
            (
                advance(3600, 10 * 86400),
                "reference_added",
                {"reference": f"research:202610/synth_{_slug(spec.bead_id)}.md"},
            )
        )
    if rng.random() < 0.15:
        spec.events.append(
            (
                advance(3600, 10 * 86400),
                "link_added",
                {
                    "target_ref": (f"artifact:docs/synth_{_slug(spec.bead_id)}.md"),
                    "relation": rng.choice(_LINK_RELATIONS),
                    "description": f"Synthetic benchmark link for {spec.bead_id}.",
                },
            )
        )
    if spec.kind == "task" and rng.random() < 0.20:
        # Reporters must be distinct: core rejects duplicate +1 reporters.
        for reporter in rng.sample(_REPORTERS, k=rng.choice((1, 2, 2, 3))):
            spec.events.append(
                (
                    advance(3600, 10 * 86400),
                    "task_plus_one_recorded",
                    {
                        "reporter": reporter,
                        "note": (
                            f"Independent corroboration for {spec.bead_id} "
                            f"by {reporter}."
                        ),
                    },
                )
            )
    if note_nos and rng.random() < 0.12:
        spec.events.append(
            (
                advance(86400, 5 * 86400),
                "note_edited",
                {
                    "note_no": note_nos[-1],
                    "text": (_note_text(rng, spec.bead_id, note_nos[-1]) + " (edited)"),
                },
            )
        )
    if note_nos and rng.random() < 0.06:
        spec.events.append(
            (advance(86400, 5 * 86400), "note_removed", {"note_no": note_nos[-1]})
        )

    closed = False
    close_at = spec.created
    if will_close:
        floor = max(clock[0] + timedelta(days=1), spec.created + timedelta(days=31))
        close_at = floor + timedelta(days=rng.randint(0, 29))
        clock[0] = close_at
        spec.events.append((close_at, "issue_closed", {}))
        closed = True
        if rng.random() < 0.60:
            # Post-close activity: the research counted 2,899 events landing
            # 7+ days after close; the corpus carries the same phenomenon.
            post_at = close_at + timedelta(days=rng.randint(7, 60))
            pick = rng.random()
            if pick < 0.4:
                spec.events.append(
                    (
                        post_at,
                        "link_added",
                        {
                            "target_ref": (
                                f"artifact:docs/synth_post_{_slug(spec.bead_id)}.md"
                            ),
                            "relation": rng.choice(_LINK_RELATIONS),
                            "description": (
                                f"Late-arriving benchmark link for {spec.bead_id}."
                            ),
                        },
                    )
                )
            elif pick < 0.7:
                spec.events.append(
                    (
                        post_at,
                        "issue_updated",
                        {"title": f"{title} (post-close rev)", "description": None},
                    )
                )
            else:
                note_counter[0] += 1
                spec.events.append(
                    (
                        post_at,
                        "note_appended",
                        {
                            "entry": (
                                "Post-close follow-up note "
                                f"[{spec.bead_id} note {note_counter[0]}]."
                            ),
                            "note_no": note_counter[0],
                        },
                    )
                )
    return closed


def _materialize_payload(
    operation: str,
    args: dict[str, Any],
    timestamp: str,
    actor: str,
    issue_id: str,
    note_ids: dict[tuple[str, int], str],
) -> dict[str, Any]:
    """Build an event payload in core's serialization order."""
    if operation == "issue_created":
        return {"kind": "issue_created", "issue": args["issue"]}
    if operation == "note_appended":
        return {"kind": "note_appended", "entry": args["entry"]}
    if operation == "issue_updated":
        return {
            "kind": "issue_updated",
            "fields": _updated_fields(
                title=args.get("title"), description=args.get("description")
            ),
        }
    if operation == "dependency_added":
        return {
            "kind": "dependency_added",
            "dependency": {
                "issue_id": issue_id,
                "depends_on_id": args["depends_on_id"],
                "created_at": timestamp,
                "created_by": actor,
            },
        }
    if operation == "reference_added":
        return {"kind": "reference_added", "reference": args["reference"]}
    if operation == "link_added":
        return {
            "kind": "link_added",
            "target_ref": args["target_ref"],
            "relation": args["relation"],
            "description": args["description"],
            "origin": "manual",
            "direction": "out",
            "uses": 1,
        }
    if operation == "task_plus_one_recorded":
        return {
            "kind": "task_plus_one_recorded",
            "evidence": {
                "timestamp": timestamp,
                "reporter": args["reporter"],
                "note": args["note"],
            },
        }
    if operation == "note_edited":
        return {
            "kind": "note_edited",
            "note_id": note_ids[(issue_id, args["note_no"])],
            "text": args["text"],
        }
    if operation == "note_removed":
        return {
            "kind": "note_removed",
            "note_id": note_ids[(issue_id, args["note_no"])],
        }
    if operation == "issue_closed":
        return {
            "kind": "issue_closed",
            "close_reason": None,
            "resolution": "done",
            "closed_by": actor,
        }
    if operation == "issue_removed":
        return {"kind": "issue_removed", "cascade_removed_issue_ids": []}
    raise ValueError(f"unknown synthetic operation: {operation}")


def _mint_stream_lines(
    stream_id: str,
    items: list[tuple[Any, int, str, str, str, dict[str, Any]]],
    note_ids: dict[tuple[str, int], str],
) -> list[str]:
    """Sort one stream chronologically, mint every event ID, render lines."""
    ordered = sorted(items, key=lambda item: (item[0], item[1]))
    lines = []
    for ordinal, (when, _seq, issue_id, actor, operation, args) in enumerate(
        ordered, start=1
    ):
        timestamp = _timestamp(when)
        payload = _materialize_payload(
            operation, args, timestamp, actor, issue_id, note_ids
        )
        event_id = mint_event_id(
            stream_id, ordinal, timestamp, actor, operation, issue_id, payload
        )
        if operation == "note_appended":
            note_ids[(issue_id, args["note_no"])] = event_id
        lines.append(
            _dump(
                {
                    "schema_version": 1,
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "actor": actor,
                    "operation": operation,
                    "issue_id": issue_id,
                    "payload": payload,
                }
            )
        )
    return lines


def _git_commit(directory: Path, message: str) -> None:
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


def _export_projection(beads_dir: Path) -> None:
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

    specs: list[_BeadSpec] = []
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
            design = f"plan:202610/synth_{_slug(bead_id)}.md"
        size = rng.choice(_SIZES) if kind in ("phase", "task") else None
        task_type = rng.choice(_TASK_TYPES) if kind == "task" else None
        external_ref = ""
        if kind == "task" and rng.random() < 0.10:
            ext_counter[0] += 1
            external_ref = f"bench-ext-{ext_counter[0]:05d}"
        spec = _BeadSpec(bead_id, kind, parent_id, created, actor)
        _schedule_bead(
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
        lines = _mint_stream_lines(stream_id, stream_items[stream_id], note_ids)
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
    _export_projection(dest)
    _git_commit(dest, f"Synthetic bead corpus scale={scale} seed={seed}")
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
