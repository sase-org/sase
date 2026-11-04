"""Shared builders for workspace lease preparation tests."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

__all__ = [
    "CONNECTION_RESET",
    "PUBLICKEY_DENIAL",
    "init_git",
    "make_fake_git",
    "plant_index_lock",
    "prepared_lease_checkout",
]

PUBLICKEY_DENIAL = (
    "git@ssh.github.com: Permission denied (publickey).\n"
    "fatal: Could not read from remote repository."
)

CONNECTION_RESET = "kex_exchange_identification: read: Connection reset by peer"


def make_fake_git(
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
        args: list[str],
        checkout: Path,
        timeout: float | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "fetch":
            fetch_calls.append({"timeout": timeout, "env": env})
            if script is not None:
                item = script.pop(0) if script else None
                if item is None:
                    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
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
                        stderr=(f"fatal: Unable to create '{lock}': File exists.\n"),
                    )
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if checkout_stderr:
                return subprocess.CompletedProcess(
                    args, 128, stdout="", stderr=checkout_stderr + "\n"
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "remote":
            return subprocess.CompletedProcess(args, 0, stdout="origin\n", stderr="")
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(
                args, 0, stdout="origin/main\n", stderr=""
            )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    monkeypatch.setattr("sase.workspace_provider._lease_git._run_git", fake_run_git)
    monkeypatch.setattr("sase.workspace_provider._lease_git._sleep", fake_sleep)
    return {
        "fetch_calls": fetch_calls,
        "checkout_calls": checkout_calls,
        "sleep_calls": sleep_calls,
    }


def prepared_lease_checkout(tmp_path: Path) -> tuple[Path, Path]:
    import subprocess

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
    return remote, checkout


def plant_index_lock(repo: Path, *, age_seconds: float) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale\n", encoding="utf-8")
    stamped = time.time() - age_seconds
    os.utime(lock, (stamped, stamped))
    return lock


def init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
