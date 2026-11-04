"""Tests for bounded SSH credential-confirmation retries."""

from __future__ import annotations

import logging

from sase.core.retryability_wire import RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED
from sase.git_credential_retry import (
    BACKGROUND_CREDENTIAL_RETRY_BUDGET,
    CredentialRetry,
    CredentialRetryBudget,
    LAUNCH_CREDENTIAL_RETRY_BUDGET,
)

_DENIAL = "git@github.com: Permission denied (publickey).\nfatal: denied"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def _retry(
    clock: _Clock,
    budget: CredentialRetryBudget = LAUNCH_CREDENTIAL_RETRY_BUDGET,
    *,
    deadline: float | None = None,
    env: dict[str, str] | None = None,
    probe_state: str = "present",
) -> CredentialRetry:
    return CredentialRetry(
        budget,
        deadline=deadline,
        env=env or {},
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        credential_probe=lambda _env, _host: probe_state,
    )


def test_retries_up_to_the_launch_budget_then_stops(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock)

    for _ in range(5):
        assert retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)

    assert retry.attempts == 5
    assert clock.sleeps == [5, 10, 20, 30, 45]
    assert clock.now == 110
    assert "on 6 attempts over 110s" in retry.failure_suffix()


def test_respects_deadline_before_sleeping(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock, deadline=8)

    assert retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)

    assert clock.sleeps == [5]
    assert "operation deadline" in retry.failure_suffix()


def test_zero_env_cap_disables_credential_retries(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock, env={"SASE_GIT_CREDENTIAL_RETRY_MAX_SECONDS": "0"})

    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert retry.attempts == 0
    assert clock.sleeps == []
    assert "sleep cap" in retry.failure_suffix()


def test_absent_credential_fails_fast_and_records_reason(monkeypatch) -> None:
    memo: dict[str, tuple[float, str]] = {}
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", memo)
    clock = _Clock()
    retry = _retry(clock, probe_state="absent")

    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert retry.attempts == 0
    assert retry.first_detail == _DENIAL
    assert "no local SSH credential" in retry.failure_suffix()
    assert "github.com" in memo


def test_exhaustion_memo_short_circuits_and_success_clears_it(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock, CredentialRetryBudget("small", (1,)))
    assert retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)

    later = _retry(clock, CredentialRetryBudget("later", (2,)))
    assert not later.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert "recently exhausted" in later.failure_suffix()

    retry.note_success()
    after_success = _retry(clock, CredentialRetryBudget("after-success", (3,)))
    assert after_success.retry_after(
        RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL
    )


def test_exhaustion_memo_expires_after_ten_minutes(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock, CredentialRetryBudget("small", (1,)))
    assert retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)
    assert not retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)

    clock.now += 601
    later = _retry(clock, CredentialRetryBudget("later", (2,)))
    assert later.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)


def test_non_publickey_verdict_never_retries(monkeypatch) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock)

    assert not retry.retry_after("permanent", _DENIAL)
    assert retry.attempts == 0
    assert retry.first_detail is None
    assert clock.sleeps == []


def test_background_budget_has_one_confirmation_retry() -> None:
    assert BACKGROUND_CREDENTIAL_RETRY_BUDGET.delays == (10,)


def test_retry_warning_contains_attempt_delay_and_original_stderr(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr("sase.git_credential_retry._EXHAUSTED_HOSTS", {})
    clock = _Clock()
    retry = _retry(clock, CredentialRetryBudget("launch", (5,)))

    with caplog.at_level(logging.WARNING, logger="sase.git_credential_retry"):
        assert retry.retry_after(RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED, _DENIAL)

    assert "retry 1" in caplog.text
    assert "after 5s" in caplog.text
    assert "git@github.com: Permission denied (publickey)." in caplog.text
