"""Worker-token acquisition in `tools/run_pytest`.

The runner never picks its own xdist width: it leases tokens from the
host-global suite gate and runs with exactly what it was granted. These tests
pin the automatic range, the exact-capacity override, and the disabled gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._run_pytest_fixtures import (
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)


pytestmark = pytest.mark.contract


def test_parallel_grant_uses_actual_lease_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    events: list[object] = []

    class FakeLease:
        def __init__(self, **kwargs: object) -> None:
            events.append(("init", kwargs))

        def acquire(self, floor: int, ceiling: int, *, exact: bool) -> int:
            events.append(("acquire", floor, ceiling, exact))
            return 7

        def make_inheritable(self) -> None:
            events.append("inheritable")

    monkeypatch.setattr(runner, "WorkerTokenLease", FakeLease)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (12, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 9))
    monkeypatch.setattr(runner, "gate_directory", lambda: tmp_path)
    monkeypatch.setattr(runner, "gate_timeout", lambda: 3.0)

    granted, lease = runner._parallel_worker_grant()

    assert granted == 7
    assert lease is not None
    assert events == [
        (
            "init",
            {
                "directory": tmp_path,
                "budget": 12,
                "timeout": 3.0,
                "capacity_is_explicit": False,
            },
        ),
        ("acquire", 2, 9, False),
        "inheritable",
    ]


def test_exact_worker_override_requests_exact_governed_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "6")
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    acquisition: list[tuple[int, int, bool]] = []

    class FakeLease:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def acquire(self, floor: int, ceiling: int, *, exact: bool) -> int:
            acquisition.append((floor, ceiling, exact))
            return 6

        def make_inheritable(self) -> None:
            pass

    monkeypatch.setattr(runner, "WorkerTokenLease", FakeLease)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, True))
    monkeypatch.setattr(runner, "gate_directory", lambda: tmp_path)
    monkeypatch.setattr(runner, "gate_timeout", lambda: 1.0)

    granted, lease = runner._parallel_worker_grant()

    assert granted == 6
    assert lease is not None
    assert acquisition == [(6, 6, True)]


@pytest.mark.parametrize("invalid", ["", "0", "-1", "many"])
def test_worker_override_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", invalid)

    with pytest.raises(pytest.UsageError, match="SASE_PYTEST_WORKERS"):
        runner._parallel_worker_grant()


def test_disabled_gate_skips_acquisition(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, True))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 5))

    assert runner._parallel_worker_grant() == (5, None)
    error = capsys.readouterr().err
    assert "suite gate bypassed: running 5 ungoverned workers" in error
    assert "8-token host pool" in error


def test_uncorroborated_bypass_cannot_outgrow_the_host_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The incident, as a regression test.

    A `-n 64` controller against a 32-token pool held zero tokens and took 64
    workers' worth of memory, and the host swapped itself to a load average of
    97.6. The exemption it claimed was never corroborated by a lease, so it now
    fails at the point of asking.
    """
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "64")
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (32, False))

    with pytest.raises(pytest.UsageError) as error:
        runner._parallel_worker_grant()

    message = str(error.value)
    assert "Requested 64 pytest worker tokens" in message
    assert "SASE_TEST_GATE_SLOTS" in message


def test_automatic_bypass_clamps_to_the_host_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (4, 20))

    assert runner._parallel_worker_grant() == (8, None)
    assert "running 8 ungoverned workers" in capsys.readouterr().err


def test_explicit_slots_are_the_supported_route_for_a_wide_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raising the pool is pool-visible, which is what makes it supported."""
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "64")
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "64")

    assert runner._parallel_worker_grant() == (64, None)
    assert "running 64 ungoverned workers against a 64-token host pool" in (
        capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "corroboration", ["SASE_TEST_GATE_GOVERNED", "PYTEST_XDIST_WORKER"]
)
def test_corroborated_exemption_grants_the_full_width_untouched(
    monkeypatch: pytest.MonkeyPatch, corroboration: str
) -> None:
    """An ancestor's lease already paid for this width; do not charge twice."""
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "64")
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.setenv(
        corroboration, "1" if corroboration.startswith("SASE") else "gw0"
    )
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (32, False))

    def _unexpected(**_kwargs: object) -> None:
        raise AssertionError("a corroborated exemption acquired tokens")

    monkeypatch.setattr(runner, "WorkerTokenLease", _unexpected)

    assert runner._parallel_worker_grant() == (64, None)


def test_corroborated_automatic_exemption_takes_the_range_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_GOVERNED", "1")
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (12, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 9))

    assert runner._parallel_worker_grant() == (9, None)


def _demand_channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    return demand_path


def _sole_grant(demand_path: Path) -> dict:
    lines = demand_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["schema_version"] == 1
    assert record["kind"] == "worker_grant"
    assert record["run_id"] == "run-1"
    return record["grant"]


def _leased_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, granted: int
) -> ModuleType:
    runner = load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)

    class FakeLease:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def acquire(self, floor: int, ceiling: int, *, exact: bool) -> int:
            return granted

        def make_inheritable(self) -> None:
            pass

    monkeypatch.setattr(runner, "WorkerTokenLease", FakeLease)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (12, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 9))
    monkeypatch.setattr(runner, "gate_directory", lambda: tmp_path)
    monkeypatch.setattr(runner, "gate_timeout", lambda: 3.0)
    return runner


def test_lease_grant_is_recorded_to_the_demand_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demand_path = _demand_channel(monkeypatch, tmp_path)
    runner = _leased_runner(monkeypatch, tmp_path, 7)
    runner._GRANT_LANE = "fast"
    runner._GRANT_ESCALATED_FROM = "scoped"

    assert runner._parallel_worker_grant()[0] == 7

    grant = _sole_grant(demand_path)
    assert grant["source"] == "pytest"
    assert grant["lane"] == "fast"
    assert grant["path"] == "lease"
    assert grant["requested_floor"] == 2
    assert grant["requested_ceiling"] == 9
    assert grant["granted"] == 7
    assert grant["budget"] == 12
    assert grant["wait_ms"] >= 0
    assert grant["escalated_from"] == "scoped"


def test_acquire_timeout_records_a_refusal_and_reraises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demand_path = _demand_channel(monkeypatch, tmp_path)
    runner = _leased_runner(monkeypatch, tmp_path, 7)

    def _timeout(self: object, floor: int, ceiling: int, *, exact: bool) -> int:
        raise runner.WorkerTokenTimeout("timed out waiting for tokens")

    monkeypatch.setattr(runner.WorkerTokenLease, "acquire", _timeout)
    runner._GRANT_LANE = "fast"

    with pytest.raises(runner.WorkerTokenTimeout):
        runner._parallel_worker_grant()

    grant = _sole_grant(demand_path)
    assert grant["path"] == "lease"
    assert grant["granted"] == 0
    assert grant["wait_ms"] >= 0
    assert grant["lane"] == "fast"


def test_acquire_capacity_mismatch_records_no_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demand_path = _demand_channel(monkeypatch, tmp_path)
    runner = _leased_runner(monkeypatch, tmp_path, 7)

    def _mismatch(self: object, floor: int, ceiling: int, *, exact: bool) -> int:
        raise pytest.UsageError(
            "SASE_TEST_GATE_SLOTS requests 12 worker tokens, but the active"
            " pool was started with 8."
        )

    monkeypatch.setattr(runner.WorkerTokenLease, "acquire", _mismatch)

    with pytest.raises(pytest.UsageError, match="SASE_TEST_GATE_SLOTS"):
        runner._parallel_worker_grant()

    assert not demand_path.exists()


def test_bypass_grant_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demand_path = _demand_channel(monkeypatch, tmp_path)
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (4, 20))

    assert runner._parallel_worker_grant() == (8, None)

    grant = _sole_grant(demand_path)
    assert grant["path"] == "bypass"
    assert grant["requested_floor"] == 4
    assert grant["requested_ceiling"] == 20
    assert grant["granted"] == 8
    assert grant["budget"] == 8
    assert grant["wait_ms"] == 0


def test_descendant_exemption_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demand_path = _demand_channel(monkeypatch, tmp_path)
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "6")
    monkeypatch.setenv("SASE_TEST_GATE_GOVERNED", "1")
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (32, False))

    assert runner._parallel_worker_grant() == (6, None)
    assert not demand_path.exists()


def test_sanitize_pops_the_demand_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", "/tmp/demand.jsonl")
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")

    runner._sanitize_pytest_environment()

    assert "SASE_TOOL_RUN_DEMAND" not in runner.os.environ
    assert runner.os.environ["SASE_TOOL_RUN_ID"] == "run-1"
