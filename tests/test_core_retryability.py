"""Golden tests for the Rust-backed retryability classifier facade."""

from __future__ import annotations

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.retryability_facade import (
    classify_failure_retryability,
    is_retryable_failure,
)
from sase.core.retryability_wire import (
    RETRYABILITY_VERDICT_AFTER_DELAY,
    RETRYABILITY_VERDICT_PERMANENT,
    RETRYABILITY_VERDICT_TRANSIENT,
    RETRYABILITY_WIRE_SCHEMA_VERSION,
    RETRY_OPERATION_GH,
    RETRY_OPERATION_GIT_CLONE,
)
from sase.sdd._store_clone_ops import _is_transient_remote_clone_failure

from ._rust_extension_module_helpers import install_fake_rust_extension


def test_retryability_facade_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None, str, str]] = []

    def fake_classifier(
        operation_kind: str,
        exit_status: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> dict[str, object]:
        calls.append((operation_kind, exit_status, stdout, stderr))
        return {
            "schema_version": RETRYABILITY_WIRE_SCHEMA_VERSION,
            "verdict": RETRYABILITY_VERDICT_TRANSIENT,
            "reason": "fake: transient",
            "retryable": True,
            "retry_after_seconds": None,
        }

    install_fake_rust_extension(
        monkeypatch,
        classify_failure_retryability=fake_classifier,
    )

    verdict = classify_failure_retryability(
        RETRY_OPERATION_GIT_CLONE,
        exit_status=128,
        stderr="fatal: early EOF",
    )

    assert verdict.verdict == RETRYABILITY_VERDICT_TRANSIENT
    assert verdict.retryable
    assert calls == [
        (RETRY_OPERATION_GIT_CLONE, 128, "", "fatal: early EOF"),
    ]


def test_is_retryable_failure_uses_classifier_retryable_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_classifier(
        _operation_kind: str,
        _exit_status: int | None = None,
        _stdout: str = "",
        _stderr: str = "",
    ) -> dict[str, object]:
        return {
            "schema_version": RETRYABILITY_WIRE_SCHEMA_VERSION,
            "verdict": RETRYABILITY_VERDICT_PERMANENT,
            "reason": "fake: permanent",
            "retryable": False,
            "retry_after_seconds": None,
        }

    install_fake_rust_extension(
        monkeypatch,
        classify_failure_retryability=fake_classifier,
    )

    assert not is_retryable_failure(
        operation_kind=RETRY_OPERATION_GH,
        stderr="gh: Not Found (HTTP 404)",
    )


def test_legacy_clone_helper_routes_to_shared_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_classifier(
        operation_kind: str,
        _exit_status: int | None = None,
        _stdout: str = "",
        stderr: str = "",
    ) -> dict[str, object]:
        seen.append(operation_kind)
        return {
            "schema_version": RETRYABILITY_WIRE_SCHEMA_VERSION,
            "verdict": RETRYABILITY_VERDICT_TRANSIENT,
            "reason": "fake: transient",
            "retryable": "connection reset" in stderr.casefold(),
            "retry_after_seconds": None,
        }

    install_fake_rust_extension(
        monkeypatch,
        classify_failure_retryability=fake_classifier,
    )

    assert _is_transient_remote_clone_failure("fatal: connection reset by peer")
    assert not _is_transient_remote_clone_failure("fatal: repository not found")
    assert seen == [RETRY_OPERATION_GIT_CLONE, RETRY_OPERATION_GIT_CLONE]


def test_rust_extension_parity_for_retryability_cases() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "classify_failure_retryability"):
        pytest.skip("sase_core_rs is too old (no classify_failure_retryability).")

    cases = [
        (
            RETRY_OPERATION_GIT_CLONE,
            "fatal: early EOF",
            RETRYABILITY_VERDICT_TRANSIENT,
            True,
            None,
        ),
        (
            RETRY_OPERATION_GIT_CLONE,
            "fatal: HTTP 502 from github.com",
            RETRYABILITY_VERDICT_TRANSIENT,
            True,
            None,
        ),
        (
            RETRY_OPERATION_GH,
            "API rate limit exceeded\nRetry-After: 5",
            RETRYABILITY_VERDICT_AFTER_DELAY,
            True,
            5,
        ),
        (
            RETRY_OPERATION_GH,
            "gh: Not Found (HTTP 404)",
            RETRYABILITY_VERDICT_PERMANENT,
            False,
            None,
        ),
        (
            RETRY_OPERATION_GH,
            "gh: Bad credentials (HTTP 401)",
            RETRYABILITY_VERDICT_PERMANENT,
            False,
            None,
        ),
    ]

    for operation_kind, stderr, expected_verdict, retryable, retry_after in cases:
        verdict = classify_failure_retryability(
            operation_kind,
            exit_status=1,
            stderr=stderr,
        )
        assert verdict.verdict == expected_verdict
        assert verdict.retryable is retryable
        assert verdict.retry_after_seconds == retry_after
