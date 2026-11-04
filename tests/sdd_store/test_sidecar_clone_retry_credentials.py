"""Credential-confirmation retries for the SDD store remote clone.

Uses an SSH-shim fake GitHub remote: ``GIT_SSH_COMMAND`` points at a temp
script that denies the first N invocations with a publickey rejection and
then serves a real bare repo via ``git upload-pack``.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import time
from typing import Any

import pytest

from sase.git_credential_retry import (
    LAUNCH_CREDENTIAL_RETRY_BUDGET,
    CredentialRetry,
    CredentialRetryBudget,
)
from sase.sdd._store_clone_remote import clone_sdd_store_to_path
from sase.sdd._store_types import (
    SddMaterializationError,
    SddTransientMaterializationError,
)

from ._clone_retry_helpers import seed_remote

_REMOTE_URL = "git@github.com:org/repo.git"
_DENIAL = "git@github.com: Permission denied (publickey)."
_DEPLOY_KEY_REFUSAL = (
    "ERROR: Permission to org/repo.git denied to deploy key.\n"
    "fatal: Could not read from remote repository."
)


def _write_shim(tmp_path: Path) -> Path:
    shim = tmp_path / "fake-ssh.sh"
    shim.write_text(
        "#!/bin/sh\n"
        # git probes `ssh -G` once per clone to learn connection options; that
        # local probe is not a GitHub authentication, so answer it without
        # touching the denial counter.
        'if [ "$1" = "-G" ]; then\n'
        "  exit 0\n"
        "fi\n"
        'count=$(cat "$SSHDENY_COUNT_FILE")\n'
        "count=$((count + 1))\n"
        'echo "$count" > "$SSHDENY_COUNT_FILE"\n'
        'if [ "$count" -le "$SSHDENY_DENIALS" ]; then\n'
        "  printf '%s\\n' \"$SSHDENY_MESSAGE\" >&2\n"
        "  exit 255\n"
        "fi\n"
        'exec git upload-pack "$SSHDENY_BARE_REPO"\n',
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return shim


@pytest.fixture
def shim_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Serve a seeded bare repo behind a denying SSH shim; return count file."""
    bare = seed_remote(tmp_path, "github-remote.git")
    count_file = tmp_path / "shim-count"
    count_file.write_text("0", encoding="utf-8")
    shim = _write_shim(tmp_path)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(shim))
    monkeypatch.setenv("SSHDENY_COUNT_FILE", str(count_file))
    monkeypatch.setenv("SSHDENY_BARE_REPO", str(bare))
    monkeypatch.setenv("SSHDENY_DENIALS", "0")
    monkeypatch.setenv("SSHDENY_MESSAGE", _DENIAL)
    return count_file


def _invocations(count_file: Path) -> int:
    return int(count_file.read_text(encoding="utf-8").strip())


@pytest.fixture
def clone_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "workspace" / "plans"
    dest.parent.mkdir(parents=True)
    return dest


def _patch_credential_retry(
    monkeypatch: pytest.MonkeyPatch, *, probe_state: str = "present"
) -> list[float]:
    """Run the clone's credential tracker with recording no-op sleeps."""
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    sleeps: list[float] = []

    def factory(
        budget: CredentialRetryBudget,
        *,
        deadline: float | None,
        env: dict[str, str],
        **kwargs: Any,
    ) -> CredentialRetry:
        return CredentialRetry(
            budget,
            deadline=deadline,
            env=env,
            sleep=sleeps.append,
            credential_probe=lambda _env, _host: probe_state,
            **kwargs,
        )

    monkeypatch.setattr("sase.sdd._store_clone_remote.CredentialRetry", factory)
    return sleeps


def test_shim_denies_then_clone_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "2")
    sleeps = _patch_credential_retry(monkeypatch)

    assert clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True) is True
    assert (clone_dir / ".git").is_dir()
    assert _invocations(shim_remote) == 3
    assert sleeps == [5, 10]


def test_persistent_denial_fails_non_transient_with_suffix(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "100")
    _patch_credential_retry(monkeypatch)

    with pytest.raises(SddMaterializationError) as excinfo:
        clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True)

    assert not isinstance(excinfo.value, SddTransientMaterializationError)
    message = str(excinfo.value)
    assert _DENIAL in message
    assert "GitHub refused SSH publickey authentication" in message
    assert "see docs/reference/agents/service-host.md" in message
    # One initial attempt plus the five launch-budget confirmation retries.
    assert _invocations(shim_remote) == 6
    assert not clone_dir.exists()


def test_deploy_key_refusal_fails_after_one_invocation(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "100")
    monkeypatch.setenv("SSHDENY_MESSAGE", _DEPLOY_KEY_REFUSAL)
    sleeps = _patch_credential_retry(monkeypatch)

    with pytest.raises(SddMaterializationError) as excinfo:
        clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True)

    assert "denied to deploy key" in str(excinfo.value)
    assert _invocations(shim_remote) == 1
    assert sleeps == []


def test_absent_local_credential_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "100")
    _patch_credential_retry(monkeypatch, probe_state="absent")

    with pytest.raises(SddMaterializationError) as excinfo:
        clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True)

    assert "no local SSH credential" in str(excinfo.value)
    assert _invocations(shim_remote) == 1


def test_short_deadline_stops_before_next_delay(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "100")
    _patch_credential_retry(monkeypatch)

    with pytest.raises(SddMaterializationError) as excinfo:
        clone_sdd_store_to_path(
            _REMOTE_URL,
            clone_dir,
            strict=True,
            deadline=time.monotonic() + 1.0,
        )

    assert "operation deadline" in str(excinfo.value)
    assert _invocations(shim_remote) == 1


def test_credential_sleeps_never_hold_the_clone_permit(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    import sase.sdd._store_clone_remote as clone_remote

    monkeypatch.setenv("SSHDENY_DENIALS", "2")
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    events: list[str] = []
    sleeps: list[float] = []
    real_admission = clone_remote.remote_clone_admission

    @contextlib.contextmanager
    def recording_admission(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        events.append("admission-enter")
        try:
            with real_admission(*args, **kwargs):
                yield
        finally:
            events.append("admission-exit")

    def event_sleep(delay: float) -> None:
        events.append("sleep")
        sleeps.append(delay)

    def factory(
        budget: CredentialRetryBudget,
        *,
        deadline: float | None,
        env: dict[str, str],
        **kwargs: Any,
    ) -> CredentialRetry:
        return CredentialRetry(
            budget,
            deadline=deadline,
            env=env,
            sleep=event_sleep,
            credential_probe=lambda _env, _host: "present",
            **kwargs,
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote.remote_clone_admission",
        recording_admission,
    )
    monkeypatch.setattr("sase.sdd._store_clone_remote.CredentialRetry", factory)

    assert clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True) is True

    assert sleeps == [5, 10]
    depth = 0
    for event in events:
        if event == "admission-enter":
            depth += 1
        elif event == "admission-exit":
            depth -= 1
        elif event == "sleep":
            assert depth == 0


def test_attempt_telemetry_carries_credential_fields(
    monkeypatch: pytest.MonkeyPatch,
    shim_remote: Path,
    clone_dir: Path,
) -> None:
    monkeypatch.setenv("SSHDENY_DENIALS", "2")
    _patch_credential_retry(monkeypatch)
    records: list[dict[str, Any]] = []
    monkeypatch.setattr("sase.logs.log_tui_git_operation", records.append)

    assert clone_sdd_store_to_path(_REMOTE_URL, clone_dir, strict=True) is True

    clone_records = [r for r in records if r.get("operation") == "sdd.clone.remote"]
    # Denials always log; a fast success may stay below the slow-git threshold.
    assert len(clone_records) >= 2
    assert [r["credential_retry_attempt"] for r in clone_records[:2]] == [0, 1]
    assert [r["retry_attempt_index"] for r in clone_records[:2]] == [0, 0]
    for record in clone_records:
        assert record["credential_retry_budget"] == len(
            LAUNCH_CREDENTIAL_RETRY_BUDGET.delays
        )
