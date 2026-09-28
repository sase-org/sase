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
from sase.core import prompt_stash_facade
from sase.core.state_write_guard import (
    assert_bead_store_write_sandboxed,
    pytest_path_is_sandboxed,
    require_pytest_sandbox_root,
)
from sase.history import prompt_store
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


def _prompt_stash_calls(real_path: Path) -> list[tuple[str, tuple, dict]]:
    """Return one call per public facade function aimed at *real_path*."""
    return [
        ("read_prompt_stash_snapshot", (real_path,), {}),
        ("append_prompt_stash", (real_path, {"id": "x"}), {}),
        ("pop_prompt_stash", (real_path, []), {}),
        ("set_prompt_stash_pinned", (real_path, [], True), {}),
        ("rewrite_prompt_stash", (real_path, []), {}),
        ("read_prompt_stash_lifecycle", (real_path,), {}),
        ("trash_prompt_stash", (real_path, [], 0, "260101_000000"), {}),
        ("restore_prompt_stash", (real_path, []), {}),
        ("purge_prompt_stash", (real_path, []), {}),
        ("reconcile_prompt_stash_trash", (real_path, 0), {}),
    ]


def test_pytest_prompt_stash_facade_refuses_real_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    real_path = account_home / ".sase" / "prompt_stash.jsonl"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "prompt stash isolation")

    with (
        patch(
            "sase.core.state_write_guard._account_home",
            return_value=account_home,
        ),
        patch.object(
            prompt_stash_facade,
            "_call_binding",
            side_effect=AssertionError("binding must not be reached"),
        ) as call_binding,
    ):
        for name, args, kwargs in _prompt_stash_calls(real_path):
            with pytest.raises(RuntimeError, match="prompt stash"):
                getattr(prompt_stash_facade, name)(*args, **kwargs)

    call_binding.assert_not_called()
    assert not (account_home / ".sase").exists()


def test_pytest_prompt_stash_facade_allows_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    sandbox_path = tmp_path / "sandbox" / "prompt_stash.jsonl"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "prompt stash isolation")

    with (
        patch(
            "sase.core.state_write_guard._account_home",
            return_value=account_home,
        ),
        patch.object(
            prompt_stash_facade,
            "_call_binding",
            return_value={"schema_version": 1},
        ) as call_binding,
    ):
        snapshot = prompt_stash_facade.read_prompt_stash_snapshot(sandbox_path)
        assert snapshot.entries == []
        prompt_stash_facade.append_prompt_stash(sandbox_path, {"id": "x"})

    assert call_binding.call_count == 2


def test_pytest_prompt_history_writes_refuse_real_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    real_file = account_home / ".sase" / "prompt_history.json"
    real_shard = account_home / ".sase" / "prompt_history" / "260101.json"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "prompt history isolation")
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", real_file)
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_DIR", None)
    monkeypatch.setattr(prompt_store, "_LEGACY_PROMPT_HISTORY_FILE", None)

    with patch(
        "sase.core.state_write_guard._account_home",
        return_value=account_home,
    ):
        with pytest.raises(RuntimeError, match="prompt history"):
            prompt_store.save_shard(real_shard, [])
        with pytest.raises(RuntimeError, match="prompt history"):
            prompt_store.save_prompt_history([])
        with pytest.raises(RuntimeError, match="prompt history"):
            with prompt_store.locked_prompt_history():
                pass

    assert not (account_home / ".sase").exists()


def test_pytest_prompt_history_writes_allow_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account"
    sandbox_file = tmp_path / "sandbox" / ".sase" / "prompt_history.json"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "prompt history isolation")
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", sandbox_file)
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_DIR", None)
    monkeypatch.setattr(prompt_store, "_LEGACY_PROMPT_HISTORY_FILE", None)

    with patch(
        "sase.core.state_write_guard._account_home",
        return_value=account_home,
    ):
        shard = prompt_store.shard_path(
            prompt_store.shard_key_for_timestamp("260101_120000")
        )
        assert prompt_store.save_shard(shard, []) is True
        assert shard.exists()
        assert prompt_store.save_prompt_history([]) is True
        with prompt_store.locked_prompt_history():
            pass

    assert not (account_home / ".sase").exists()
