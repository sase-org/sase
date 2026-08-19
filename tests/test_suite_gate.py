from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from tests._suite_gate import (
    configure_suite_gate,
    descendant_exemption,
    unconfigure_suite_gate,
)


pytestmark = pytest.mark.contract


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
        "SASE_TEST_GATE_LEASE_ID",
        "SASE_TEST_GATE_LEASE_PID",
        "SASE_TEST_GATE_FDS",
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
    monkeypatch.delenv("SASE_TEST_GATE_LEASE_ID", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_LEASE_PID", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_FDS", raising=False)
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
