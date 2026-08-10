"""Real-store regression coverage for the plus-one post-close reopen race.

Every test here drives a genuine bead store on disk, because the race only
shows up against real store state: an assigned worker holds a task
``in_progress`` while a wave of independent reporters files ``+1`` evidence
against the still-open defect, then the worker closes the bead. The instant
the bead becomes ``closed``, the store used to treat the very next +1 in that
same wave exactly like a fresh reproduction and reopen the bead it had just
watched get fixed, dragging its assignee back into ``ready`` with it.

The fix gives each +1 an observation-window start (``observed_since``) and
only reopens a closed task when that window opens strictly after the close.
These tests reproduce the original failure end to end: a wave absorbed while
``in_progress``, a stale post-wave reporter whose window predates the close
(withheld — the bead stays closed), and a genuinely fresh reporter whose
window postdates the close (reopens, with the stale assignee cleared).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.model import Issue, IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.core import bead_read_facade
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution

CREATOR = "creator-agent"
WORKER = "worker-agent"

# The wave: reporters already running before the worker even preclaimed the
# task, hitting the still-open defect while it was `in_progress`. Their +1s
# must be absorbed as evidence with no status change, exactly as before.
WAVE_REPORTERS = ("wave-a", "wave-b", "wave-c")
WAVE_OBSERVED_SINCE = "2026-08-10T13:00:00Z"

# A reporter whose run started long before the close — stale corroboration
# that happens to land after it. The reopen must be withheld.
STALE_REPORTER = "stale-reporter"
STALE_OBSERVED_SINCE = "2026-01-01T00:00:00Z"

# A reporter whose run started long after the close — a genuine
# reproduction on a tree that already contains the fix. This one reopens.
FRESH_REPORTER = "fresh-reporter"
FRESH_OBSERVED_SINCE = "2099-01-01T00:00:00Z"


@pytest.fixture
def race_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SimpleNamespace]:
    """A real bead store, kept clear of any project mock."""
    checkout = tmp_path / "checkout"
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout)
    with BeadProject(checkout) as project:
        beads_dir = project.beads_dir
    yield SimpleNamespace(checkout=checkout, beads_dir=beads_dir)


def _closed_task_with_absorbed_wave(store: SimpleNamespace) -> tuple[str, str]:
    """Preclaim a task, absorb a pre-preclaim +1 wave, then close it.

    Returns the task id and the ``closed_at`` the close actually produced,
    so later assertions compare against what the real store recorded rather
    than a value the test invented.
    """
    with BeadProject(store.checkout) as project:
        task = project.create(
            "Race-prone task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by=CREATOR,
        )
        project.update(task.id, status=Status.IN_PROGRESS.value, assignee=WORKER)

        for reporter in WAVE_REPORTERS:
            _, changed = project.plus_one(
                task.id,
                f"{reporter} hit the still-open defect",
                reporter=reporter,
                observed_since=WAVE_OBSERVED_SINCE,
            )
            assert changed

        in_progress = project.show(task.id)
        assert in_progress.status is Status.IN_PROGRESS
        assert in_progress.assignee == WORKER
        assert in_progress.plus_one_count == len(WAVE_REPORTERS)

        project.close(
            [task.id],
            reason="fixed",
            resolution=Resolution.DONE,
            author=WORKER,
        )
        closed = project.show(task.id)

    assert closed.status is Status.CLOSED
    assert closed.assignee == WORKER
    assert closed.closed_at is not None
    return task.id, closed.closed_at


def _reload(store: SimpleNamespace) -> Issue:
    """Read the bead back through the binding, bypassing every Python cache."""
    issues = bead_read_facade.list_issues(store.beads_dir)
    assert len(issues) == 1
    return issues[0]


def test_plus_one_stale_post_close_reporter_leaves_a_just_closed_task_closed(
    race_store: SimpleNamespace,
) -> None:
    """The race's failure mode: evidence lands, the close survives."""
    task_id, closed_at = _closed_task_with_absorbed_wave(race_store)

    with BeadProject(race_store.checkout) as project:
        issue, changed = project.plus_one(
            task_id,
            "already running before the close landed",
            reporter=STALE_REPORTER,
            observed_since=STALE_OBSERVED_SINCE,
        )
        outcome = project.last_mutation_outcome

    assert changed
    assert issue.status is Status.CLOSED
    assert issue.assignee == WORKER
    assert outcome["reopen_withheld"] is True
    assert outcome["reopen_withheld_closed_at"] == closed_at

    reloaded = _reload(race_store)
    assert reloaded.status is Status.CLOSED
    assert reloaded.assignee == WORKER
    assert reloaded.plus_one_count == len(WAVE_REPORTERS) + 1


def test_plus_one_fresh_post_close_reporter_reopens_and_clears_the_stale_assignee(
    race_store: SimpleNamespace,
) -> None:
    """The fix's other half: a genuinely fresh reproduction still reopens."""
    task_id, _ = _closed_task_with_absorbed_wave(race_store)

    with BeadProject(race_store.checkout) as project:
        issue, changed = project.plus_one(
            task_id,
            "reproduced on a tree that already contains the fix",
            reporter=FRESH_REPORTER,
            observed_since=FRESH_OBSERVED_SINCE,
        )
        outcome = project.last_mutation_outcome

    assert changed
    assert issue.status is Status.READY
    assert issue.assignee == ""
    assert outcome["reopen_withheld"] is False

    reloaded = _reload(race_store)
    assert reloaded.status is Status.READY
    assert reloaded.assignee == ""
    assert reloaded.plus_one_count == len(WAVE_REPORTERS) + 1
