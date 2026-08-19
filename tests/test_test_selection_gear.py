"""The middle gear: when it engages, at what width, and when it declines.

The gear is the one place the diff-scoped lane asks the host for anything, so
these tests care most about the two refusals: it must never queue, and it must
never take a grant it did not earn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests._suite_gate_lease import WorkerTokenLease
from tests._test_selection import Selection, SelectionOptions, select_tests
from tests._test_selection_fixtures import (
    _touch,
    build_fixture_repo,
    install_fresh_baseline,
)
from tests._test_selection_gear import (
    DEFAULT_SCOPED_WORKER_CEILING,
    REFUSED_GATE_DISABLED,
    REFUSED_GATE_ERROR,
    REFUSED_GEAR_DISABLED,
    REFUSED_SERIAL_REQUIRED,
    REFUSED_TOKENS_UNAVAILABLE,
    SCOPED_WORKER_CEILING_ENV,
    SCOPED_WORKER_FLOOR,
    ScopedGear,
    engage_scoped_gear,
    manifest_with_gear,
    scoped_worker_ceiling,
)
from tests._test_selection_timings import timings_directory, write_timings


@pytest.fixture(autouse=True)
def _explicit_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the host budget so a grant is the pool's answer, not the machine's."""
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "4")
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv(SCOPED_WORKER_CEILING_ENV, raising=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_SCOPED_WORKER_CEILING),
        ("", DEFAULT_SCOPED_WORKER_CEILING),
        ("8", 8),
        ("1", 1),
        ("0", 0),
        # A knob that only ever makes a run cheaper is not worth failing over.
        ("four", DEFAULT_SCOPED_WORKER_CEILING),
        ("-3", 0),
    ],
)
def test_ceiling_reads_the_environment_without_ever_raising(
    raw: str | None, expected: int
) -> None:
    environ = {} if raw is None else {SCOPED_WORKER_CEILING_ENV: raw}

    assert scoped_worker_ceiling(environ) == expected


def test_a_free_pool_grants_the_ceiling_and_the_caller_holds_the_lease(
    tmp_path: Path,
) -> None:
    gear, lease = engage_scoped_gear(directory=tmp_path / "tokens")

    assert isinstance(lease, WorkerTokenLease)
    try:
        assert gear.granted
        assert gear.worker_count == DEFAULT_SCOPED_WORKER_CEILING
        assert gear.reason is None
        assert lease.granted == DEFAULT_SCOPED_WORKER_CEILING
        # The lease marks its descendants governed, which is what keeps the
        # child pytest from leasing its own workers on top of these.
        assert gear.payload() == {
            "granted": True,
            "worker_count": DEFAULT_SCOPED_WORKER_CEILING,
            "ceiling": DEFAULT_SCOPED_WORKER_CEILING,
            "floor": SCOPED_WORKER_FLOOR,
            "reason": None,
        }
    finally:
        lease.release()


def test_an_exhausted_pool_refuses_immediately_instead_of_queueing(
    tmp_path: Path,
) -> None:
    pool_dir = tmp_path / "tokens"
    holder = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(4, 4, exact=True)
    try:
        # An empty `environ`: the real holder of a full pool is another
        # agent's process, but an in-process one leaves its own
        # `SASE_TEST_GATE_DISABLED` marker behind, which would refuse the gear
        # for the wrong reason.
        gear, lease = engage_scoped_gear(directory=pool_dir, environ={})
    finally:
        holder.release()

    assert lease is None
    assert not gear.granted
    assert gear.reason == REFUSED_TOKENS_UNAVAILABLE


def test_a_single_spare_token_is_declined_rather_than_run_one_wide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One worker is a serial run wearing xdist's overhead; take neither."""
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "2")
    pool_dir = tmp_path / "tokens"
    holder = WorkerTokenLease(
        directory=pool_dir, budget=2, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    try:
        gear, lease = engage_scoped_gear(directory=pool_dir, environ={})
        # The declined token went back to the pool rather than being held.
        spare = WorkerTokenLease(
            directory=pool_dir, budget=2, timeout=0.0, capacity_is_explicit=True
        )
        assert spare.try_acquire(1, 1) == 1
        spare.release()
    finally:
        holder.release()

    assert lease is None
    assert gear.reason == REFUSED_TOKENS_UNAVAILABLE


def test_a_governed_parent_run_turns_the_gear_off(tmp_path: Path) -> None:
    gear, lease = engage_scoped_gear(
        directory=tmp_path / "tokens", environ={"SASE_TEST_GATE_DISABLED": "1"}
    )

    assert lease is None
    assert gear.attempted
    assert gear.reason == REFUSED_GATE_DISABLED


def test_a_ceiling_below_the_floor_turns_the_gear_off(tmp_path: Path) -> None:
    gear, lease = engage_scoped_gear(
        directory=tmp_path / "tokens", environ={SCOPED_WORKER_CEILING_ENV: "1"}
    )

    assert lease is None
    assert gear.ceiling == 1
    assert gear.reason == REFUSED_GEAR_DISABLED


def test_a_run_that_must_be_serial_never_reaches_the_pool(tmp_path: Path) -> None:
    pool_dir = tmp_path / "tokens"

    gear, lease = engage_scoped_gear(serial_required=True, directory=pool_dir)

    assert lease is None
    assert gear.reason == REFUSED_SERIAL_REQUIRED
    assert not pool_dir.exists()


def test_a_pool_that_objects_escalates_instead_of_failing_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate the scoped lane was only *asking* must not fail its run."""
    pool_dir = tmp_path / "tokens"
    holder = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    # An explicit request that disagrees with the running pool's capacity is
    # the usage error `_synchronize_capacity` raises.
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "8")
    try:
        gear, lease = engage_scoped_gear(directory=pool_dir, environ={})
    finally:
        holder.release()

    assert lease is None
    assert gear.reason == REFUSED_GATE_ERROR


# --------------------------------------------------------------------------
# What the selector hands the gear
# --------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = build_fixture_repo(tmp_path)
    install_fresh_baseline(root)
    return root


def _select(
    repo: Path,
    *,
    store: Path | None = None,
    max_ratio: float = 1.0,
    max_serial_seconds: float = 1.0e9,
) -> Selection:
    """Select as `tests/_test_selection_engine_helpers.py` does: a resolvable
    base, a fresh baseline, and an empty timing table unless the caller priced
    one."""
    return select_tests(
        repo,
        SelectionOptions(
            base_ref="HEAD",
            max_ratio=max_ratio,
            max_serial_seconds=max_serial_seconds,
        ),
        contexts_store=repo.parent / "selection-store" / "project",
        timings_store=(
            repo.parent / "selection-store" / "no-timings" if store is None else store
        ),
    )


def _priced_store(repo: Path, seconds_per_file: float) -> Path:
    """A duration table covering everything a change to ``src/pkg/a.py`` selects."""
    store = repo.parent / "selection-store" / "timings"
    baseline = _select(repo, store=store)
    write_timings(
        timings_directory(store, {}),
        dict.fromkeys(baseline.selected, seconds_per_file),
        mode="fast",
        pid=1001,
        now=datetime(2026, 8, 6, 12, 1, 0, tzinfo=UTC),
    )
    return store


def test_a_budget_escalation_keeps_the_selection_it_rejected(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")
    store = _priced_store(repo, 100.0)
    baseline = _select(repo, max_serial_seconds=1.0e6, store=store)

    selection = _select(repo, max_serial_seconds=50.0, store=store)

    assert baseline.selected, "the fixture must select something to reject"
    assert selection.escalated
    assert selection.selected == ()
    # The gear gets exactly what the budget threw away, not a re-derivation.
    assert selection.gear_candidate == baseline.selected


def test_a_ratio_escalation_has_no_candidate_to_bound_a_gear_with(repo: Path) -> None:
    """No timing table means no cost model, and a gear needs one to be bounded."""
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, max_ratio=0.05)

    assert selection.escalated
    assert selection.gear_candidate == ()


def test_a_change_set_escalation_has_no_candidate(repo: Path) -> None:
    _touch(repo, "Justfile")
    store = _priced_store(repo, 0.1)

    selection = _select(repo, store=store)

    assert selection.escalated
    assert selection.gear_candidate == ()


def test_a_selection_within_budget_has_no_candidate(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")
    store = _priced_store(repo, 0.1)

    selection = _select(repo, max_serial_seconds=1.0e6, store=store)

    assert not selection.escalated
    assert selection.gear_candidate == ()


def test_a_granted_gear_withdraws_the_escalation_it_answered() -> None:
    manifest = {
        "escalated": True,
        "selected": [],
        "selected_count": 0,
        "rules_fired": ["serial-budget-exceeded"],
    }

    updated = manifest_with_gear(
        manifest,
        ScopedGear(attempted=True, worker_count=3),
        selected=("tests/test_a.py", "tests/test_b.py"),
    )

    assert updated["escalated"] is False
    assert updated["selected"] == ["tests/test_a.py", "tests/test_b.py"]
    assert updated["selected_count"] == 2
    # The rule stays: it is why the gear engaged, and erasing it would make
    # the third gear invisible to `just selection-health`.
    assert updated["rules_fired"] == ["serial-budget-exceeded"]
    assert updated["gear"]["worker_count"] == 3
    assert manifest["escalated"] is True


def test_a_refused_gear_leaves_the_escalation_standing() -> None:
    manifest = {"escalated": True, "selected": [], "selected_count": 0}

    updated = manifest_with_gear(
        manifest, ScopedGear(attempted=True, reason=REFUSED_TOKENS_UNAVAILABLE)
    )

    assert updated["escalated"] is True
    assert updated["selected"] == []
    assert updated["gear"]["granted"] is False
    assert updated["gear"]["reason"] == REFUSED_TOKENS_UNAVAILABLE
