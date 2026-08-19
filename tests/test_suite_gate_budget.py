from __future__ import annotations

from pathlib import Path

import pytest

from tests._suite_gate_budget import (
    _calculate_default_token_budget,
    _read_mem_available_kib,
    automatic_worker_range,
    configured_token_budget,
)


pytestmark = pytest.mark.contract

_GIB_KIB = 1024 * 1024


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
    assert automatic_worker_range(28) == (4, 14)
    assert automatic_worker_range(32) == (4, 14)

    monkeypatch.setenv("SASE_PYTEST_WORKER_FLOOR", "3")
    monkeypatch.setenv("SASE_PYTEST_WORKER_CEILING", "2")
    with pytest.raises(pytest.UsageError, match="FLOOR.*CEILING"):
        automatic_worker_range(8)

    monkeypatch.setenv("SASE_PYTEST_WORKER_FLOOR", "9")
    monkeypatch.setenv("SASE_PYTEST_WORKER_CEILING", "9")
    with pytest.raises(pytest.UsageError, match="FLOOR=9.*8-token"):
        automatic_worker_range(8)
