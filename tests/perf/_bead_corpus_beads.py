"""Synthetic bead specs and lifetime-event scheduling for the bead corpus."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from tests.perf._bead_corpus_common import bead_slug, format_timestamp

__all__ = ["BeadSpec", "schedule_bead"]

_REPORTERS = tuple(f"synth.reporter.{idx:02d}" for idx in range(24))
_LINK_RELATIONS = ("cites", "implements", "related")

_NOTE_OPENERS = (
    "Investigated the failure mode and captured the reproduction steps.",
    "Checked the current behavior against the documented contract.",
    "Narrowed the scope after reading the surrounding implementation.",
    "Recorded the decision and the alternatives that were rejected.",
    "Verified the fix against the regression suite and the manual path.",
    "Collected timings before changing anything on the hot path.",
)


class BeadSpec:
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


def _note_text(rng: random.Random, bead_id: str, counter: int) -> str:
    opener = rng.choice(_NOTE_OPENERS)
    return f"{opener} [{bead_id} note {counter}]"


def schedule_bead(
    rng: random.Random,
    spec: BeadSpec,
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
        format_timestamp(spec.created),
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
                {"reference": f"research:202610/synth_{bead_slug(spec.bead_id)}.md"},
            )
        )
    if rng.random() < 0.15:
        spec.events.append(
            (
                advance(3600, 10 * 86400),
                "link_added",
                {
                    "target_ref": (f"artifact:docs/synth_{bead_slug(spec.bead_id)}.md"),
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
                                f"artifact:docs/synth_post_{bead_slug(spec.bead_id)}.md"
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
