"""Update-overlap reproducer: scheduler jobs that run through a code swap.

Every test drives the real chop runner (``run_configured_chop_once``) and a
real job subprocess while the real code-swap writer lock is held on a sandbox
lock file (see ``_swap_harness``). The swap_chop_guards phase flipped every
mode here from a strict xfail to a passing test: no job starts under a live
writer, a script missing within the post-swap grace is a retry, and a run that
overlapped a swap and died of SIGBUS or a swap-skew import error is a retry.
The controls pin the other side: with no swap on record the same failures stay
loud. Harness breakage raises ``HarnessError``, never ``AssertionError``.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.runner_failure_facts import capture_failure_facts
from sase.axe.state import chop_run_log_path
from sase.dev_update.code_swap_lock import (
    CodeSwapWait,
    code_swap_readers_active,
    code_swap_writer_lock,
    wait_for_code_swap_readers,
)
from tests.dev_update._swap_harness import (
    LUMBERJACK,
    ChopRun,
    HarnessError,
    SwapSandbox,
    make_sandbox,
    mapped_payload,
)

_MISSING_BINDING = "No module named 'sase_core_rs'"


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwapSandbox:
    return make_sandbox(tmp_path, monkeypatch)


def _run_log(outcome: ChopRunOutcome) -> str:
    if outcome.run_id is None:
        raise HarnessError(f"chop recorded no run: {outcome}")
    path = chop_run_log_path(LUMBERJACK, outcome.chop_name, outcome.run_id)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _require_signal(sandbox: SwapSandbox, name: str) -> None:
    """Fail the harness (not the assertion) if the job never reached *name*."""
    if not (sandbox.signals / name).exists():
        raise HarnessError(f"job never reached {name!r}; the mode did not reproduce")


def _assert_inhibited(outcome: ChopRunOutcome) -> None:
    assert outcome.status == "skipped", (outcome.status, outcome.error)
    assert outcome.skip_reason == "inhibited"
    assert outcome.advances_cadence is False


def _mapped_file(sandbox: SwapSandbox) -> Path:
    path = sandbox.root / "native" / "sase_core_rs.abi3.so"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mapped_payload("v1"))
    return path


# -- (a) a script vanishes while the writer is live -----------------------


def test_script_vanishing_while_writer_is_live_is_an_inhibited_retry(
    sandbox: SwapSandbox,
) -> None:
    """Covered since ea7916d7a7: the real writer probe sees the live swap."""
    name = "sase_job_swaprepro_vanish"
    sandbox.write_job_script(name, "noop")
    with sandbox.writer():
        sandbox.remove_job_script(name)
        outcome = ChopRun(sandbox, name).run_now()

    _assert_inhibited(outcome)
    assert outcome.reason is not None
    assert name in outcome.reason
    assert "code swap" in outcome.reason


def test_job_does_not_start_while_writer_is_live(sandbox: SwapSandbox) -> None:
    name = "sase_job_swaprepro_start"
    sandbox.write_job_script(name, "noop")
    with sandbox.writer():
        outcome = ChopRun(sandbox, name).run_now()

    _assert_inhibited(outcome)
    assert "did not start because a code swap is in progress" in (outcome.reason or "")
    assert not (sandbox.signals / "started").exists()


# -- (b) a script is still missing just after the writer releases ---------


def test_script_missing_just_after_writer_releases_is_an_inhibited_retry(
    sandbox: SwapSandbox,
) -> None:
    name = "sase_job_swaprepro_late"
    sandbox.write_job_script(name, "noop")
    with sandbox.writer():
        sandbox.remove_job_script(name)
    outcome = ChopRun(sandbox, name).run_now()

    _assert_inhibited(outcome)
    assert "unavailable while a code swap settles" in (outcome.reason or "")


def test_script_missing_with_no_swap_is_a_loud_missing_script(
    sandbox: SwapSandbox,
) -> None:
    """Control: with no swap on record the missing script stays an error."""
    outcome = ChopRun(sandbox, "sase_job_swaprepro_never_installed").run_now()

    assert outcome.status == "missing_script"
    assert outcome.advances_cadence is True


# -- (c) a running job loses its binding mid-run ---------------------------


@pytest.mark.parametrize(
    "writer_live_at_exit",
    [True, False],
    ids=["writer-live-at-exit", "swap-completed-before-exit"],
)
def test_job_losing_binding_mid_run_is_an_inhibited_retry(
    sandbox: SwapSandbox, writer_live_at_exit: bool
) -> None:
    name = "sase_job_swaprepro_binding"
    sandbox.install_binding()
    sandbox.write_job_script(name, "binding")
    run = ChopRun(sandbox, name)
    outcome: ChopRunOutcome | None = None
    with run.started():
        with sandbox.writer():
            sandbox.remove_binding()
            if writer_live_at_exit:
                outcome = run.finish()
        if outcome is None:
            outcome = run.finish()

    _require_signal(sandbox, "importing")
    _assert_inhibited(outcome)
    assert "swap" in (outcome.reason or "")


def test_job_missing_binding_without_a_swap_stays_a_failure(
    sandbox: SwapSandbox,
) -> None:
    """Control: the text alone is skew-suspect, so overlap must decide.

    The existing failure-fact helper already labels this output as update
    skew, yet no swap happened. A guard keyed on text alone would hide a real
    broken install; the classification must also require swap overlap.
    """
    name = "sase_job_swaprepro_unbound"
    sandbox.write_job_script(name, "binding")
    outcome = ChopRun(sandbox, name).run_now()

    assert outcome.status == "failure"
    assert outcome.exit_code == 1
    log = _run_log(outcome)
    assert _MISSING_BINDING in log
    facts = capture_failure_facts(None, phase="chop", error_text=log)
    assert facts["skew_suspect"] is True


# -- SIGBUS: a mapped native file rewritten in place under a running job ----


def test_job_sigbus_from_in_place_rewrite_during_swap_is_an_inhibited_retry(
    sandbox: SwapSandbox,
) -> None:
    mapped = _mapped_file(sandbox)
    name = "sase_job_swaprepro_sigbus"
    sandbox.write_job_script(name, "mmap", mapped_path=mapped)
    run = ChopRun(sandbox, name)
    with run.started():
        with sandbox.writer():
            # The first syscall of ``cp new.so live.so``: O_TRUNC on the inode.
            os.truncate(mapped, 0)
            outcome = run.finish()

    _require_signal(sandbox, "touching")
    if "mapped v1" in _run_log(outcome):
        raise HarnessError("the job survived the truncation; SIGBUS did not reproduce")
    _assert_inhibited(outcome)
    assert outcome.exit_code == -signal.SIGBUS
    assert "SIGBUS" in (outcome.reason or "")


def test_job_sigbus_without_a_swap_stays_a_failure(sandbox: SwapSandbox) -> None:
    """Control: SIGBUS reproduces deterministically and, alone, is a failure."""
    mapped = _mapped_file(sandbox)
    name = "sase_job_swaprepro_sigbus_alone"
    sandbox.write_job_script(name, "mmap", mapped_path=mapped)
    run = ChopRun(sandbox, name)
    with run.started():
        os.truncate(mapped, 0)
        outcome = run.finish()

    assert outcome.status == "failure"
    assert outcome.exit_code == -signal.SIGBUS


# -- (f) a dev-update writer and a job that holds no reader lock -------------


def test_writer_does_not_wait_for_mid_run_job_and_surviving_job_stays_success(
    sandbox: SwapSandbox,
) -> None:
    """Jobs never register as readers, so a dev update never waits for them.

    ``sase dev update`` waits on blocking readers, then takes the writer with
    a bounded wait. A mid-run job is invisible to both, so its protection has
    to come from classifying it after exit; a job that survives the overlap
    must stay a plain success.
    """
    name = "sase_job_swaprepro_overlap"
    sandbox.write_job_script(name, "noop")
    run = ChopRun(sandbox, name)
    with run.started():
        assert code_swap_readers_active() is None
        readers = wait_for_code_swap_readers(CodeSwapWait(timeout_seconds=0.0))
        assert readers.cleared is True
        sandbox.assert_isolated()
        wait = CodeSwapWait(timeout_seconds=5.0, poll_seconds=0.01)
        with code_swap_writer_lock(wait=wait) as lock:
            assert lock.acquired is True
            assert lock.waited is False
            outcome = run.finish()

    assert outcome.status == "success"
    assert "job ok" in _run_log(outcome)
