"""Regression coverage for the pytest-to-production write boundary."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig
from sase.axe.orchestrator import Orchestrator
from sase.axe.state import append_bounded_log
from sase.core.state_write_guard import (
    assert_bead_store_write_sandboxed,
    pytest_path_is_sandboxed,
    require_pytest_sandbox_root,
)
from sase.telemetry import flush_metrics, metrics as telemetry_metrics
from sase.telemetry._config import _TelemetryConfig
from sase.telemetry._registry import _reset_for_tests, init_telemetry


@pytest.fixture(autouse=True)
def _reset_guard_warnings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _reset_for_tests()
    monkeypatch.setattr("sase.core.state_write_guard._warned_refusals", set())
    yield
    _reset_for_tests()


def test_pytest_path_is_sandboxed_uses_published_boundary(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    inside = sandbox / "beads"
    outside = tmp_path / "production" / "beads"
    environ = {
        "PYTEST_CURRENT_TEST": "sandbox containment",
        "SASE_PYTEST_SANDBOX_DIR": str(sandbox),
    }

    assert pytest_path_is_sandboxed(inside, environ=environ)
    assert not pytest_path_is_sandboxed(outside, environ=environ)
    assert not pytest_path_is_sandboxed(
        inside,
        environ={"PYTEST_CURRENT_TEST": "missing sandbox"},
    )
    assert pytest_path_is_sandboxed(outside, environ={})


def test_bead_store_write_allows_non_pytest_process(tmp_path: Path) -> None:
    assert_bead_store_write_sandboxed(
        tmp_path / "production" / "beads",
        operation="create",
        environ={},
    )


def test_bead_store_write_allows_target_inside_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"

    assert_bead_store_write_sandboxed(
        sandbox / "project" / "beads",
        operation="create",
        environ={
            "PYTEST_CURRENT_TEST": "sandboxed bead write",
            "SASE_PYTEST_SANDBOX_DIR": str(sandbox),
        },
    )


def test_bead_store_write_refuses_target_outside_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    beads_dir = tmp_path / "production" / "beads"

    with pytest.raises(RuntimeError) as exc:
        assert_bead_store_write_sandboxed(
            beads_dir,
            operation="remove_many",
            environ={
                "PYTEST_CURRENT_TEST": "unsandboxed bead write",
                "SASE_PYTEST_SANDBOX_DIR": str(sandbox),
            },
        )

    message = str(exc.value)
    assert str(beads_dir) in message
    assert "remove_many" in message
    assert str(sandbox) in message


def test_bead_store_write_refuses_missing_sandbox(tmp_path: Path) -> None:
    beads_dir = tmp_path / "beads"

    with pytest.raises(RuntimeError) as exc:
        assert_bead_store_write_sandboxed(
            beads_dir,
            operation="update",
            environ={"PYTEST_CURRENT_TEST": "missing sandbox"},
        )

    message = str(exc.value)
    assert str(beads_dir) in message
    assert "update" in message
    assert "SASE_PYTEST_SANDBOX_DIR" in message


def test_bead_store_write_allows_explicit_override(tmp_path: Path) -> None:
    assert_bead_store_write_sandboxed(
        tmp_path / "production" / "beads",
        operation="close",
        environ={
            "PYTEST_CURRENT_TEST": "deliberate unsandboxed bead write",
            "SASE_ALLOW_UNSANDBOXED_BEAD_WRITES": "1",
        },
    )


def test_require_sandbox_root_returns_none_outside_pytest() -> None:
    assert require_pytest_sandbox_root(purpose="managed temp dir", environ={}) is None


def test_require_sandbox_root_resolves_the_published_root(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    resolved = require_pytest_sandbox_root(
        purpose="managed temp dir",
        environ={
            "PYTEST_CURRENT_TEST": "published sandbox",
            "SASE_PYTEST_SANDBOX_DIR": str(sandbox),
        },
    )

    assert resolved == sandbox.resolve()


@pytest.mark.parametrize("published", ["", "   "])
def test_require_sandbox_root_fails_closed_without_a_sandbox(published: str) -> None:
    with pytest.raises(RuntimeError) as exc:
        require_pytest_sandbox_root(
            purpose="managed temp dir",
            environ={
                "PYTEST_CURRENT_TEST": "unpublished sandbox",
                "SASE_PYTEST_SANDBOX_DIR": published,
            },
        )

    message = str(exc.value)
    assert "managed temp dir" in message
    assert "SASE_PYTEST_SANDBOX_DIR" in message


def test_unisolated_pytest_telemetry_refuses_before_drain_or_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    real_store = account_home / ".sase" / "telemetry" / "metrics.sqlite"
    isolated_store = tmp_path / "isolated" / "metrics.sqlite"
    real_config = _TelemetryConfig(enabled=True, store_path=real_store)
    isolated_config = _TelemetryConfig(enabled=True, store_path=isolated_store)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "state isolation")

    with (
        patch(
            "sase.core.state_write_guard._account_home",
            return_value=account_home,
        ),
        patch(
            "sase.telemetry._registry.get_telemetry_config",
            return_value=real_config,
        ) as get_config,
        patch("sase_core_rs.telemetry_record_batch") as record_batch,
    ):
        init_telemetry()
        telemetry_metrics.AXE_CYCLES.labels(cycle_type="tick").inc()

        with pytest.raises(RuntimeError, match="Set SASE_HOME") as exc:
            flush_metrics("axe")

        assert str(real_store) in str(exc.value)
        record_batch.assert_not_called()

        get_config.return_value = isolated_config
        record_batch.return_value = {"samples_recorded": 1}
        assert flush_metrics("axe") == 1
        record_batch.assert_called_once()

    assert not (account_home / ".sase").exists()


def test_axe_log_refusal_warns_once_without_touching_real_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account_home = tmp_path / "account"
    log_path = account_home / ".sase" / "axe" / "logs" / "output.log"
    monkeypatch.setenv("PYTEST_VERSION", "test")

    with (
        patch(
            "sase.core.state_write_guard._account_home",
            return_value=account_home,
        ),
        caplog.at_level(logging.WARNING),
    ):
        append_bounded_log(log_path, "first\n")
        append_bounded_log(log_path, "second\n")

    assert not (account_home / ".sase").exists()
    refusals = [
        record
        for record in caplog.records
        if "Refusing pytest axe-log write" in record.getMessage()
    ]
    assert len(refusals) == 1
    assert str(log_path) in refusals[0].getMessage()


def test_crash_loop_refusal_precedes_error_and_notification_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    real_axe = account_home / ".sase" / "axe"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "crash loop isolation")
    orchestrator = Orchestrator(AxeConfig())

    with (
        patch(
            "sase.core.state_write_guard._account_home",
            return_value=account_home,
        ),
        patch("sase.axe.state.axe_state_dir", return_value=real_axe),
        patch("sase.axe.orchestrator.append_error") as append_error,
        patch(
            "sase.notifications.senders.notify_workflow_complete"
        ) as notify_workflow_complete,
    ):
        orchestrator._surface_crash_loop(
            "hooks",
            exit_code=17,
            failure_count=3,
            spawn_error=None,
        )

    append_error.assert_not_called()
    notify_workflow_complete.assert_not_called()
    assert not (account_home / ".sase").exists()
