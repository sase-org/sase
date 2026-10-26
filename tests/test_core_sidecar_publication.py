"""Tests for the sidecar publication policy facade."""

from __future__ import annotations

import pytest

from sase.core.sidecar_publication_facade import (
    SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY,
    SIDECAR_PUBLICATION_ACTION_STOP,
    _SidecarPublicationDecision,
    classify_sidecar_publication_push_result,
    decide_sidecar_publication_after_push,
)

from ._rust_extension_module_helpers import install_fake_rust_extension


def _decision(action: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "action": action,
        "classification": "rejected_fetch_first",
        "reason": "integrate upstream and retry",
        "attempt": 1,
        "max_attempts": 3,
        "retryable": action == SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY,
    }


def test_sidecar_publication_facade_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str, str, int]] = []

    def fake_binding(returncode: int, stdout: str, stderr: str, attempt: int) -> dict:
        calls.append((returncode, stdout, stderr, attempt))
        return _decision(SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY)

    install_fake_rust_extension(
        monkeypatch,
        decide_sidecar_publication_after_push=fake_binding,
    )

    decision = decide_sidecar_publication_after_push(
        returncode=1,
        stdout="",
        stderr="! [rejected] main -> main (fetch first)",
        attempt=1,
    )

    assert decision == _SidecarPublicationDecision(
        schema_version=1,
        action=SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY,
        classification="rejected_fetch_first",
        reason="integrate upstream and retry",
        attempt=1,
        max_attempts=3,
        retryable=True,
    )
    assert calls == [(1, "", "! [rejected] main -> main (fetch first)", 1)]


def test_sidecar_publication_facade_rejects_stale_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch,
        decide_sidecar_publication_after_push=lambda *_args: {
            **_decision(SIDECAR_PUBLICATION_ACTION_STOP),
            "schema_version": 0,
        },
    )

    with pytest.raises(RuntimeError, match="wire is stale"):
        decide_sidecar_publication_after_push(
            returncode=1,
            stdout="",
            stderr="fatal",
            attempt=1,
        )


def test_sidecar_publication_facade_rejects_zero_attempt() -> None:
    with pytest.raises(ValueError, match="attempt"):
        decide_sidecar_publication_after_push(
            returncode=1,
            stdout="",
            stderr="fatal",
            attempt=0,
        )


def test_sidecar_rejection_facade_returns_sanitized_core_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SYNTHETIC_SECRET_NEVER_SERIALIZED"
    calls: list[tuple[int, str, str]] = []

    def fake_binding(returncode: int, stdout: str, stderr: str) -> dict:
        calls.append((returncode, stdout, stderr))
        return {
            "schema_version": 1,
            "classification": "rejected_secret_scan",
            "commit_ids": ["a" * 40],
            "relative_paths": ["agents/a/chat.md"],
        }

    install_fake_rust_extension(
        monkeypatch,
        classify_sidecar_publication_push_result=fake_binding,
    )
    result = classify_sidecar_publication_push_result(
        returncode=1,
        stdout="",
        stderr=f"GH013: {secret}",
    )

    assert result.classification == "rejected_secret_scan"
    assert result.commit_ids == ("a" * 40,)
    assert result.relative_paths == ("agents/a/chat.md",)
    assert calls == [(1, "", f"GH013: {secret}")]


def test_sidecar_rejection_facade_rejects_unknown_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch,
        classify_sidecar_publication_push_result=lambda *_args: {
            "schema_version": 1,
            "classification": "not_a_classification",
            "commit_ids": ["not-a-commit"],
            "relative_paths": [],
        },
    )
    with pytest.raises(RuntimeError, match="unknown"):
        classify_sidecar_publication_push_result(
            returncode=1,
            stdout="",
            stderr="GH013",
        )
