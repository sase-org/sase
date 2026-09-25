"""Operational workspace lease remote preparation (sase-mq.2)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from sase.workspace_provider.lease import (
    _OperationalLeaseError as OperationalLeaseError,
)


class TestPrepareFromRemote:
    def test_missing_git_dir_is_a_preparation_error(self, tmp_path: Path) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        checkout = tmp_path / "empty"
        checkout.mkdir()
        with pytest.raises(OperationalLeaseError, match="preparation"):
            _prepare_from_primary_remote(checkout)

    def _fake_git(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        fetch_stderr: str = "",
        checkout_stderr: str = "",
        fetch_script: Sequence[str | None] | None = None,
        lock_aware_checkout: bool = False,
    ) -> dict[str, Any]:
        import subprocess

        fetch_calls: list[dict[str, Any]] = []
        checkout_calls: list[dict[str, Any]] = []
        sleep_calls: list[float] = []
        script = list(fetch_script) if fetch_script is not None else None

        def fake_run_git(
            args: list[str], checkout: Path, timeout: float | None = None
        ) -> subprocess.CompletedProcess[str]:
            if args[0] == "fetch":
                fetch_calls.append({"timeout": timeout})
                if script is not None:
                    item = script.pop(0) if script else None
                    if item is None:
                        return subprocess.CompletedProcess(
                            args, 0, stdout="", stderr=""
                        )
                    if item == "timeout":
                        raise subprocess.TimeoutExpired(
                            ["git", *args], timeout if timeout is not None else 0.0
                        )
                    return subprocess.CompletedProcess(
                        args, 128, stdout="", stderr=item + "\n"
                    )
                if fetch_stderr:
                    return subprocess.CompletedProcess(
                        args, 128, stdout="", stderr=fetch_stderr + "\n"
                    )
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[0] == "checkout":
                checkout_calls.append({"timeout": timeout})
                if lock_aware_checkout:
                    lock = checkout / ".git" / "index.lock"
                    if lock.exists():
                        return subprocess.CompletedProcess(
                            args,
                            128,
                            stdout="",
                            stderr=(
                                f"fatal: Unable to create '{lock}': File exists.\n"
                            ),
                        )
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                if checkout_stderr:
                    return subprocess.CompletedProcess(
                        args, 128, stdout="", stderr=checkout_stderr + "\n"
                    )
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[0] == "remote":
                return subprocess.CompletedProcess(
                    args, 0, stdout="origin\n", stderr=""
                )
            if args[0] == "rev-parse":
                return subprocess.CompletedProcess(
                    args, 0, stdout="origin/main\n", stderr=""
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        monkeypatch.setattr("sase.workspace_provider._lease_git._run_git", fake_run_git)
        monkeypatch.setattr("sase.workspace_provider._lease_git._sleep", fake_sleep)
        return {
            "fetch_calls": fetch_calls,
            "checkout_calls": checkout_calls,
            "sleep_calls": sleep_calls,
        }

    _PUBLICKEY_DENIAL = (
        "git@ssh.github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository."
    )

    _CONNECTION_RESET = "kex_exchange_identification: read: Connection reset by peer"

    def test_fetch_publickey_denial_gains_ssh_agent_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(monkeypatch, fetch_stderr=self._PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

        message = str(exc_info.value)
        assert self._PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message
        assert "sase service init" in message

    def test_checkout_publickey_denial_gains_ssh_agent_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(monkeypatch, checkout_stderr=self._PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

        message = str(exc_info.value)
        assert self._PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message

    def test_unrelated_fetch_failure_gains_no_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(monkeypatch, fetch_stderr="fatal: couldn't find remote ref main")

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

        message = str(exc_info.value)
        assert "couldn't find remote ref main" in message
        assert "SSH_AUTH_SOCK" not in message
        assert "sase service init" not in message

    def test_publickey_denial_message_shape_is_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(monkeypatch, fetch_stderr=self._PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path)

        assert str(exc_info.value) == (
            "operational workspace lease failed during preparation: "
            f"{self._PUBLICKEY_DENIAL}\n"
            "This is usually a missing or empty SSH agent in the calling process "
            "(check SSH_AUTH_SOCK); when the caller is the service host, give it an "
            "unattended credential (see docs/init.md). Re-running `sase service "
            "init` from a login shell only lasts until that shell's agent dies.; "
            "the user-owned primary checkout was left untouched"
        )

    @pytest.mark.parametrize("failing_step", ["fetch", "checkout"])
    def test_publickey_denial_is_marked_as_a_credential_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_step: str
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(
            monkeypatch, **{f"{failing_step}_stderr": self._PUBLICKEY_DENIAL}
        )

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path)

        error = exc_info.value
        assert error.is_credential_failure is True
        assert error.retryability is not None
        assert error.retryability.retryable is False

    @pytest.mark.parametrize(
        "stderr",
        [
            "ssh: connect to host ssh.github.com port 443: Connection timed out",
            "fatal: couldn't find remote ref main",
        ],
    )
    def test_non_credential_git_failure_is_not_marked_credential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        self._fake_git(monkeypatch, fetch_stderr=stderr)

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path)

        error = exc_info.value
        assert error.is_credential_failure is False
        assert error.retryability is not None
        assert "SSH_AUTH_SOCK" not in str(error)

    def test_lease_error_without_a_verdict_is_not_a_credential_failure(self) -> None:
        error = OperationalLeaseError("allocation", "all axe workspaces are claimed")

        assert error.retryability is None
        assert error.is_credential_failure is False

    def test_fetch_publickey_denial_then_success_retries_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(monkeypatch, fetch_script=[self._PUBLICKEY_DENIAL, None])

        with caplog.at_level(
            logging.WARNING, logger="sase.workspace_provider._lease_git"
        ):
            _prepare_from_primary_remote(tmp_path)

        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [10.0]
        warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "sase.workspace_provider._lease_git" in r.name
        ]
        assert len(warnings) == 1
        assert "cleared on retry" in warnings[0].getMessage()
        assert self._PUBLICKEY_DENIAL in warnings[0].getMessage()

    def test_persistent_fetch_publickey_denial_raises_after_confirmation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(
            monkeypatch,
            fetch_script=[self._PUBLICKEY_DENIAL, self._PUBLICKEY_DENIAL],
        )

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path)

        assert str(exc_info.value) == (
            "operational workspace lease failed during preparation: "
            f"{self._PUBLICKEY_DENIAL}\n"
            "This is usually a missing or empty SSH agent in the calling process "
            "(check SSH_AUTH_SOCK); when the caller is the service host, give it an "
            "unattended credential (see docs/init.md). Re-running `sase service "
            "init` from a login shell only lasts until that shell's agent dies.; "
            "the user-owned primary checkout was left untouched"
        )
        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [10.0]
        error = exc_info.value
        assert error.is_credential_failure is True

    def test_retryable_transport_failure_then_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(monkeypatch, fetch_script=[self._CONNECTION_RESET, None])

        _prepare_from_primary_remote(tmp_path)

        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [1.0]

    def test_persistent_retryable_transport_failure_raises_after_three_attempts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(
            monkeypatch,
            fetch_script=[
                self._CONNECTION_RESET,
                self._CONNECTION_RESET,
                self._CONNECTION_RESET,
            ],
        )

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

        assert len(calls["fetch_calls"]) == 3
        assert calls["sleep_calls"] == [1.0, 5.0]
        error = exc_info.value
        assert error.is_credential_failure is False

    def test_non_retryable_fetch_failure_raises_after_one_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(
            monkeypatch,
            fetch_script=["fatal: couldn't find remote ref main"],
        )

        with pytest.raises(OperationalLeaseError, match="preparation"):
            _prepare_from_primary_remote(tmp_path)

        assert len(calls["fetch_calls"]) == 1
        assert calls["sleep_calls"] == []

    def test_fetch_timeout_retries_then_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.sdd._git import network_git_timeout
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = self._fake_git(
            monkeypatch, fetch_script=["timeout", "timeout", "timeout"]
        )

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

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
        calls = self._fake_git(monkeypatch, checkout_stderr=self._PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path)

        assert len(calls["checkout_calls"]) == 1
        assert calls["sleep_calls"] == []
        message = str(exc_info.value)
        assert self._PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message

    def test_prepare_fast_forwards_to_origin_head(self, tmp_path: Path) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True)
        seed = tmp_path / "seed"
        seed.mkdir()
        _init_git(seed)
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

        _prepare_from_primary_remote(checkout)
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
        remote, checkout = _prepared_lease_checkout(tmp_path)
        lock = _plant_index_lock(checkout, age_seconds=3600)

        _prepare_from_primary_remote(checkout)

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
        _remote, checkout = _prepared_lease_checkout(tmp_path)
        lock = _plant_index_lock(checkout, age_seconds=0)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(checkout)

        assert "index.lock" in str(exc_info.value)
        assert lock.exists()

    def test_prepare_lock_recovery_does_not_use_fetch_sleep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        (tmp_path / ".git").mkdir()
        lock = _plant_index_lock(tmp_path, age_seconds=3600)
        calls = self._fake_git(monkeypatch, lock_aware_checkout=True)

        _prepare_from_primary_remote(tmp_path)

        assert len(calls["checkout_calls"]) > 1
        assert calls["sleep_calls"] == []
        assert not lock.exists()


def _prepared_lease_checkout(tmp_path: Path) -> tuple[Path, Path]:
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    _init_git(seed)
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
    return remote, checkout


def _plant_index_lock(repo: Path, *, age_seconds: float) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale\n", encoding="utf-8")
    stamped = time.time() - age_seconds
    os.utime(lock, (stamped, stamped))
    return lock


def _init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
