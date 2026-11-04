"""Transport, timeout, and lock-recovery preparation tests (sase-mq.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider.lease import (
    _OperationalLeaseError as OperationalLeaseError,
)
from tests.workspace_provider._workspace_lease_prepare_helpers import (
    CONNECTION_RESET,
    PUBLICKEY_DENIAL,
    init_git,
    make_fake_git,
    plant_index_lock,
    prepared_lease_checkout,
)

__all__ = ["TestPrepareFromRemoteTransport"]


class TestPrepareFromRemoteTransport:
    def test_retryable_transport_failure_then_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(monkeypatch, fetch_script=[CONNECTION_RESET, None])

        _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [1.0]

    def test_persistent_retryable_transport_failure_raises_after_three_attempts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(
            monkeypatch,
            fetch_script=[
                CONNECTION_RESET,
                CONNECTION_RESET,
                CONNECTION_RESET,
            ],
        )

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 3
        assert calls["sleep_calls"] == [1.0, 5.0]
        error = exc_info.value
        assert error.is_credential_failure is False

    def test_non_retryable_fetch_failure_raises_after_one_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(
            monkeypatch,
            fetch_script=["fatal: couldn't find remote ref main"],
        )

        with pytest.raises(OperationalLeaseError, match="preparation"):
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 1
        assert calls["sleep_calls"] == []

    def test_fetch_timeout_retries_then_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.sdd._git import network_git_timeout
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(
            monkeypatch, fetch_script=["timeout", "timeout", "timeout"]
        )

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 3
        assert calls["sleep_calls"] == [1.0, 5.0]
        message = str(exc_info.value)
        assert "timed out after" in message
        assert f"{network_git_timeout():g}s" in message
        error = exc_info.value
        assert error.retryability is None
        assert error.is_credential_failure is False
        assert all(
            call["timeout"] == network_git_timeout() for call in calls["fetch_calls"]
        )

    def test_checkout_publickey_denial_is_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(monkeypatch, checkout_stderr=PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["checkout_calls"]) == 1
        assert calls["sleep_calls"] == []
        message = str(exc_info.value)
        assert PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message

    def test_prepare_fast_forwards_to_origin_head(self, tmp_path: Path) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True)
        seed = tmp_path / "seed"
        seed.mkdir()
        init_git(seed)
        (seed / "README").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-qm", "one"], cwd=seed, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote)], cwd=seed, check=True
        )
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True)

        checkout = tmp_path / "lease"
        subprocess.run(["git", "clone", str(remote), str(checkout)], check=True)
        (seed / "README").write_text("two\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-qm", "two"], cwd=seed, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True)

        _prepare_from_primary_remote(checkout, workspace_num=7)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        remote_head = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=remote,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head == remote_head
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"

    def test_prepare_recovers_from_stale_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        remote, checkout = prepared_lease_checkout(tmp_path)
        lock = plant_index_lock(checkout, age_seconds=3600)

        _prepare_from_primary_remote(checkout, workspace_num=7)

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        remote_head = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=remote,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head == remote_head
        assert not lock.exists()

    def test_prepare_does_not_remove_a_fresh_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        _remote, checkout = prepared_lease_checkout(tmp_path)
        lock = plant_index_lock(checkout, age_seconds=0)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(checkout, workspace_num=7)

        assert "index.lock" in str(exc_info.value)
        assert lock.exists()

    def test_prepare_lock_recovery_does_not_use_fetch_sleep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        (tmp_path / ".git").mkdir()
        lock = plant_index_lock(tmp_path, age_seconds=3600)
        calls = make_fake_git(monkeypatch, lock_aware_checkout=True)

        _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["checkout_calls"]) > 1
        assert calls["sleep_calls"] == []
        assert not lock.exists()
