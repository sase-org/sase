from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from tests._suite_gate import (
    WorkerTokenLease,
    _calculate_default_token_budget,
    _read_mem_available_kib,
    automatic_worker_range,
    configure_suite_gate,
    configured_token_budget,
    descendant_exemption,
    unconfigure_suite_gate,
)


pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[1]
_GIB_KIB = 1024 * 1024


def _config(
    numprocesses: object,
    *,
    tx: list[str] | None = None,
    auto_workers: int = 4,
    maxprocesses: int | None = None,
) -> pytest.Config:
    hook = SimpleNamespace(pytest_xdist_auto_num_workers=lambda **_kwargs: auto_workers)
    return cast(
        pytest.Config,
        SimpleNamespace(
            hook=hook,
            option=SimpleNamespace(
                maxprocesses=maxprocesses,
                numprocesses=numprocesses,
                tx=[] if tx is None else tx,
            ),
        ),
    )


def _lease(
    directory: Path,
    *,
    budget: int = 1,
    timeout: float = 1,
    status_interval: float = 30,
) -> WorkerTokenLease:
    return WorkerTokenLease(
        directory,
        budget,
        timeout,
        capacity_is_explicit=True,
        poll_interval=0.01,
        status_interval=status_interval,
    )


@pytest.mark.parametrize(
    ("cpu_count", "mem_available_gib", "expected"),
    [
        (64, 64, 32),
        (8, 64, 7),
        (64, 10, 2),
        (2, 64, 1),
        (None, 64, 1),
        (64, None, 4),
        # A 4-vCPU CI runner must get real parallelism; a flat CPU reserve used to
        # collapse this shape to a single worker and serialize the whole CI matrix.
        (4, 14, 3),
    ],
)
def test_default_budget_arithmetic(
    cpu_count: int | None, mem_available_gib: int | None, expected: int
) -> None:
    mem_available_kib = (
        None if mem_available_gib is None else mem_available_gib * _GIB_KIB
    )

    assert (
        _calculate_default_token_budget(
            cpu_count=cpu_count, mem_available_kib=mem_available_kib
        )
        == expected
    )


@pytest.mark.parametrize(
    "contents",
    [
        "MemTotal: 123 kB\n",
        "MemAvailable:\n",
        "MemAvailable: nope kB\n",
        "MemAvailable: 100 MB\n",
        "MemAvailable: -1 kB\n",
    ],
)
def test_meminfo_missing_or_malformed_is_unavailable(
    tmp_path: Path, contents: str
) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(contents, encoding="utf-8")

    assert _read_mem_available_kib(meminfo) is None


def test_meminfo_reads_available_kib(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 999 kB\nMemAvailable: 123456 kB\n", encoding="utf-8")

    assert _read_mem_available_kib(meminfo) == 123456


def test_explicit_budget_override_and_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "7")

    assert configured_token_budget() == (7, True)

    for invalid in ("", "0", "-1", "many"):
        monkeypatch.setenv("SASE_TEST_GATE_SLOTS", invalid)
        with pytest.raises(pytest.UsageError, match="SASE_TEST_GATE_SLOTS"):
            configured_token_budget()


def test_automatic_range_clamps_defaults_and_validates_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_PYTEST_WORKER_FLOOR", raising=False)
    monkeypatch.delenv("SASE_PYTEST_WORKER_CEILING", raising=False)
    assert automatic_worker_range(2) == (2, 2)
    assert automatic_worker_range(28) == (4, 24)
    assert automatic_worker_range(32) == (4, 28)

    monkeypatch.setenv("SASE_PYTEST_WORKER_FLOOR", "3")
    monkeypatch.setenv("SASE_PYTEST_WORKER_CEILING", "2")
    with pytest.raises(pytest.UsageError, match="FLOOR.*CEILING"):
        automatic_worker_range(8)

    monkeypatch.setenv("SASE_PYTEST_WORKER_FLOOR", "9")
    monkeypatch.setenv("SASE_PYTEST_WORKER_CEILING", "9")
    with pytest.raises(pytest.UsageError, match="FLOOR=9.*8-token"):
        automatic_worker_range(8)


def test_floor_acquisition_grows_greedily_and_records_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    lease = _lease(tmp_path, budget=6)

    assert lease.acquire(2, 4) == 4
    assert lease.granted == 4
    assert os.environ["SASE_TEST_GATE_DISABLED"] == "1"
    assert os.environ["SASE_TEST_GATE_GOVERNED"] == "1"
    assert all(not os.get_inheritable(fd) for fd in lease.file_descriptors)

    metadata = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
    assert metadata["pid"] == os.getpid()
    assert metadata["budget"] == 6
    assert metadata["requested_floor"] == 2
    assert metadata["requested_ceiling"] == 4
    assert metadata["granted"] == 4

    lease.make_inheritable()
    assert all(os.get_inheritable(fd) for fd in lease.file_descriptors)
    lease.release()
    assert "SASE_TEST_GATE_DISABLED" not in os.environ
    assert "SASE_TEST_GATE_GOVERNED" not in os.environ


def test_release_restores_inherited_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "parent-disabled")
    monkeypatch.setenv("SASE_TEST_GATE_GOVERNED", "parent-governed")
    lease = _lease(tmp_path)

    lease.acquire(1, 1, exact=True)
    lease.release()

    assert os.environ["SASE_TEST_GATE_DISABLED"] == "parent-disabled"
    assert os.environ["SASE_TEST_GATE_GOVERNED"] == "parent-governed"


def test_scaled_leases_share_capacity_without_exceeding_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first = _lease(tmp_path, budget=6)
    second = _lease(tmp_path, budget=6)

    assert first.acquire(2, 4) == 4
    assert second.acquire(2, 4) == 2
    assert first.granted + second.granted == 6

    first.release()
    second.release()


def test_simultaneous_leases_never_exceed_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    start = threading.Barrier(6)
    state_lock = threading.Lock()
    active_tokens = 0
    maximum_active_tokens = 0

    def _hold_tokens() -> None:
        nonlocal active_tokens, maximum_active_tokens
        lease = _lease(tmp_path, budget=4, timeout=2)
        start.wait()
        grant = lease.acquire(1, 2)
        with state_lock:
            active_tokens += grant
            maximum_active_tokens = max(maximum_active_tokens, active_tokens)
        time.sleep(0.03)
        with state_lock:
            active_tokens -= grant
        lease.release()

    threads = [threading.Thread(target=_hold_tokens) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum_active_tokens == 4
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)


def test_conflicting_explicit_capacity_fails_while_pool_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = _lease(tmp_path, budget=4)
    holder.acquire(1, 1, exact=True)

    try:
        with pytest.raises(
            pytest.UsageError, match="SASE_TEST_GATE_SLOTS.*active pool"
        ):
            _lease(tmp_path, budget=5).acquire(1, 1, exact=True)
    finally:
        holder.release()


def test_partial_attempt_rolls_back_instead_of_hoarding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = _lease(tmp_path, budget=5)
    contender = _lease(tmp_path, budget=5, timeout=0)
    replacement = _lease(tmp_path, budget=5)
    holder.acquire(4, 4, exact=True)

    with pytest.raises(pytest.UsageError):
        contender.acquire(2, 2, exact=True)

    assert replacement.acquire(1, 1, exact=True) == 1
    holder.release()
    replacement.release()


def test_exact_request_larger_than_pool_fails_actionably(tmp_path: Path) -> None:
    with pytest.raises(pytest.UsageError) as error:
        _lease(tmp_path, budget=3).acquire(4, 4, exact=True)

    message = str(error.value)
    assert "Requested 4 pytest worker tokens" in message
    assert "SASE_TEST_GATE_SLOTS" in message
    assert "SASE_PYTEST_WORKERS/-n" in message


def test_wait_and_timeout_deduplicate_holder_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = _lease(tmp_path, budget=4)
    holder.acquire(4, 4, exact=True)

    try:
        with pytest.raises(pytest.UsageError) as error:
            _lease(tmp_path, budget=4, timeout=0.02, status_interval=0).acquire(
                2, 2, exact=True
            )
    finally:
        holder.release()

    status = capsys.readouterr().err
    message = str(error.value)
    assert "2 worker tokens" in message
    assert "4 tokens: pid" in message
    assert f"pid {os.getpid()}" in status
    assert "SASE_TEST_GATE_TIMEOUT" in message
    assert "SASE_TEST_GATE_DISABLED=1" in message


def test_waiter_is_admitted_promptly_after_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first = _lease(tmp_path, budget=2)
    second = _lease(tmp_path, budget=2)
    acquired = threading.Event()
    first.acquire(2, 2, exact=True)

    def _acquire_second() -> None:
        second.acquire(2, 2, exact=True)
        acquired.set()

    thread = threading.Thread(target=_acquire_second)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.05)
        first.release()
        assert acquired.wait(timeout=1)
    finally:
        first.release()
        second.release()
        thread.join(timeout=1)


def test_tokens_are_reacquirable_after_exec_holder_is_sigkilled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "from tests._suite_gate import WorkerTokenLease",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 3, 5, "
            "capacity_is_explicit=True)",
            "lease.acquire(3, 3, exact=True)",
            "lease.make_inheritable()",
            "code = \"import time; print('ready', flush=True); time.sleep(60)\"",
            "os.execv(sys.executable, [sys.executable, '-c', code])",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        process.send_signal(signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL

        replacement = _lease(tmp_path, budget=3)
        assert replacement.acquire(3, 3, exact=True) == 3
        replacement.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_configure_acquires_exact_numeric_controller_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "4")
    monkeypatch.setenv("SASE_TEST_GATE_TIMEOUT", "0")
    config = _config(3)

    configure_suite_gate(config)

    metadata = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
    assert metadata["granted"] == 3
    # Both markers, not just the disable flag. The in-pytest gate's descendants
    # would otherwise be indistinguishable from a top-level bypass, and would
    # queue for tokens this process is already holding on their behalf.
    assert os.environ["SASE_TEST_GATE_DISABLED"] == "1"
    assert os.environ["SASE_TEST_GATE_GOVERNED"] == "1"
    assert descendant_exemption()
    unconfigure_suite_gate(config)
    assert "SASE_TEST_GATE_DISABLED" not in os.environ
    assert "SASE_TEST_GATE_GOVERNED" not in os.environ


@pytest.mark.parametrize("automatic_form", ["auto", "logical"])
def test_configure_resolves_automatic_xdist_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    automatic_form: str,
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "4")
    config = _config(automatic_form, auto_workers=3)

    configure_suite_gate(config)

    metadata = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
    assert metadata["granted"] == 3
    unconfigure_suite_gate(config)


@pytest.mark.parametrize(
    ("environment", "numprocesses"),
    [
        ({"SASE_TEST_GATE_DISABLED": "1"}, 2),
        ({"SASE_TEST_GATE_GOVERNED": "1"}, 2),
        ({"PYTEST_XDIST_WORKER": "gw0"}, 2),
        ({}, None),
        ({}, 0),
        ({}, 1),
        ({}, "0"),
        ({}, "1"),
    ],
)
def test_configure_exemptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: dict[str, str],
    numprocesses: object,
) -> None:
    for name in (
        "SASE_TEST_GATE_DISABLED",
        "SASE_TEST_GATE_GOVERNED",
        "PYTEST_XDIST_WORKER",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))

    configure_suite_gate(_config(numprocesses))

    assert not (tmp_path / "pool.lock").exists()


@pytest.mark.parametrize(
    ("environment", "corroborated"),
    [
        # The whole point of the split: a bare disable flag is a *claim* of
        # exemption that anyone can export, so it does not corroborate one.
        ({"SASE_TEST_GATE_DISABLED": "1"}, False),
        ({"SASE_TEST_GATE_GOVERNED": "1"}, True),
        ({"PYTEST_XDIST_WORKER": "gw0"}, True),
        ({"SASE_TEST_GATE_DISABLED": "1", "SASE_TEST_GATE_GOVERNED": "1"}, True),
        ({}, False),
    ],
)
def test_descendant_exemption_requires_a_real_ancestor_lease(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    corroborated: bool,
) -> None:
    for name in (
        "SASE_TEST_GATE_DISABLED",
        "SASE_TEST_GATE_GOVERNED",
        "PYTEST_XDIST_WORKER",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert descendant_exemption() is corroborated


def test_configure_uses_effective_tx_count_and_maxprocesses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "3")

    tx_config = _config(None, tx=["popen", "popen", "popen"])
    configure_suite_gate(tx_config)
    assert (
        json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))["granted"]
        == 3
    )
    unconfigure_suite_gate(tx_config)

    capped_config = _config(8, maxprocesses=2)
    configure_suite_gate(capped_config)
    assert (
        json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))["granted"]
        == 2
    )
    unconfigure_suite_gate(capped_config)
