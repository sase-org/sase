"""Operational workspace lease remote preparation (sase-mq.2)."""

from __future__ import annotations

from pathlib import Path

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
    ) -> None:
        import subprocess

        def fake_run_git(
            args: list[str], checkout: Path
        ) -> subprocess.CompletedProcess[str]:
            del checkout
            failing = {"fetch": fetch_stderr, "checkout": checkout_stderr}
            if args[0] in failing and failing[args[0]]:
                return subprocess.CompletedProcess(
                    args, 128, stdout="", stderr=failing[args[0]] + "\n"
                )
            if args[0] == "remote":
                return subprocess.CompletedProcess(
                    args, 0, stdout="origin\n", stderr=""
                )
            if args[0] == "rev-parse":
                return subprocess.CompletedProcess(
                    args, 0, stdout="origin/main\n", stderr=""
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr("sase.workspace_provider._lease_git._run_git", fake_run_git)

    _PUBLICKEY_DENIAL = (
        "git@ssh.github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository."
    )

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


def _init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
