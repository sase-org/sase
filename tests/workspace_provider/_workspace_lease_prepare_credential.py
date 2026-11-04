"""Credential-remediation preparation tests (sase-mq.2)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sase.workspace_provider.lease import (
    _OperationalLeaseError as OperationalLeaseError,
)
from tests.workspace_provider._workspace_lease_prepare_helpers import (
    PUBLICKEY_DENIAL,
    make_fake_git,
)

__all__ = ["TestPrepareFromRemote"]


class TestPrepareFromRemote:
    def test_missing_git_dir_is_a_preparation_error(self, tmp_path: Path) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        checkout = tmp_path / "empty"
        checkout.mkdir()
        with pytest.raises(OperationalLeaseError, match="preparation"):
            _prepare_from_primary_remote(checkout, workspace_num=7)

    def test_fetch_publickey_denial_gains_ssh_agent_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        make_fake_git(monkeypatch, fetch_stderr=PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        message = str(exc_info.value)
        assert PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message
        assert "sase service init" in message

    def test_checkout_publickey_denial_gains_ssh_agent_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        make_fake_git(monkeypatch, checkout_stderr=PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        message = str(exc_info.value)
        assert PUBLICKEY_DENIAL in message
        assert "SSH_AUTH_SOCK" in message

    def test_unrelated_fetch_failure_gains_no_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        make_fake_git(monkeypatch, fetch_stderr="fatal: couldn't find remote ref main")

        with pytest.raises(OperationalLeaseError, match="preparation") as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        message = str(exc_info.value)
        assert "couldn't find remote ref main" in message
        assert "SSH_AUTH_SOCK" not in message
        assert "sase service init" not in message

    def test_persistent_publickey_denial_keeps_stderr_then_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        make_fake_git(monkeypatch, fetch_stderr=PUBLICKEY_DENIAL)

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert str(exc_info.value) == (
            "operational workspace lease failed during preparation: "
            f"{PUBLICKEY_DENIAL}\n"
            "GitHub refused SSH publickey authentication on 2 attempts over 10s; "
            "credential retry budget exhausted; "
            "see docs/reference/agents/service-host.md\n"
            "This is usually a missing or empty SSH agent in the calling process "
            "(check SSH_AUTH_SOCK); when the caller is the service host, give it an "
            "unattended credential (see docs/reference/agents/service-host.md). Re-running `sase service "
            "init` from a login shell only lasts until that shell's agent dies.; "
            "the user-owned primary checkout was left untouched"
        )

    @pytest.mark.parametrize("failing_step", ["fetch", "checkout"])
    def test_publickey_denial_is_marked_as_a_credential_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_step: str
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        make_fake_git(monkeypatch, **{f"{failing_step}_stderr": PUBLICKEY_DENIAL})

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

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
        make_fake_git(monkeypatch, fetch_stderr=stderr)

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

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
        calls = make_fake_git(monkeypatch, fetch_script=[PUBLICKEY_DENIAL, None])

        with caplog.at_level(logging.WARNING, logger="sase.git_credential_retry"):
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [10.0]
        warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "sase.git_credential_retry" in r.name
        ]
        assert any(
            "cleared after 1 retries" in record.getMessage() for record in warnings
        )
        assert any(PUBLICKEY_DENIAL in record.getMessage() for record in warnings)

    def test_persistent_fetch_publickey_denial_raises_after_confirmation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(
            monkeypatch,
            fetch_script=[PUBLICKEY_DENIAL, PUBLICKEY_DENIAL],
        )

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert str(exc_info.value) == (
            "operational workspace lease failed during preparation: "
            f"{PUBLICKEY_DENIAL}\n"
            "GitHub refused SSH publickey authentication on 2 attempts over 10s; "
            "credential retry budget exhausted; "
            "see docs/reference/agents/service-host.md\n"
            "This is usually a missing or empty SSH agent in the calling process "
            "(check SSH_AUTH_SOCK); when the caller is the service host, give it an "
            "unattended credential (see docs/reference/agents/service-host.md). Re-running `sase service "
            "init` from a login shell only lasts until that shell's agent dies.; "
            "the user-owned primary checkout was left untouched"
        )
        assert len(calls["fetch_calls"]) == 2
        assert calls["sleep_calls"] == [10.0]
        error = exc_info.value
        assert error.is_credential_failure is True

    def test_absent_local_credential_fails_without_confirmation_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(monkeypatch, fetch_stderr=PUBLICKEY_DENIAL)
        monkeypatch.setattr(
            "sase.git_credential_retry.local_ssh_credential_state",
            lambda *_args: "absent",
        )

        with pytest.raises(OperationalLeaseError) as exc_info:
            _prepare_from_primary_remote(tmp_path, workspace_num=7)

        assert len(calls["fetch_calls"]) == 1
        assert calls["sleep_calls"] == []
        assert "no local SSH credential" in str(exc_info.value)
        assert PUBLICKEY_DENIAL in str(exc_info.value)

    def test_launch_budget_allows_multiple_credential_confirmations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.git_credential_retry import LAUNCH_CREDENTIAL_RETRY_BUDGET
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        (tmp_path / ".git").mkdir()
        calls = make_fake_git(
            monkeypatch,
            fetch_script=[PUBLICKEY_DENIAL, PUBLICKEY_DENIAL, None],
        )

        _prepare_from_primary_remote(
            tmp_path,
            workspace_num=7,
            credential_budget=LAUNCH_CREDENTIAL_RETRY_BUDGET,
        )

        assert len(calls["fetch_calls"]) == 3
        assert calls["sleep_calls"] == [5.0, 10.0]
