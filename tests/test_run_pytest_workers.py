"""Worker-token acquisition in `tools/run_pytest`.

The runner never picks its own xdist width: it leases tokens from the
host-global suite gate and runs with exactly what it was granted. These tests
pin the automatic range, the exact-capacity override, and the disabled gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._run_pytest_fixtures import load_run_pytest


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
                "governed": True,
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


def test_disabled_gate_skips_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, True))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 5))

    assert runner._parallel_worker_grant() == (5, None)
