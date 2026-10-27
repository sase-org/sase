"""Push-classifier and error-sanitization unit tests."""

from __future__ import annotations

import pytest

from sase.agents_sync import publication_recovery as recovery
from tests.agents_sync.test_publication_recovery._helpers import (
    BLOCKED_REL,
    TOKEN,
    gh013_stderr,
)


def test_secret_scan_precedes_fetch_first_hints() -> None:
    rejection = recovery.classify_publication_push(
        returncode=1,
        stdout="",
        stderr=gh013_stderr(BLOCKED_REL) + "update rejected: fetch first\n",
    )
    assert rejection.classification == recovery.REJECTED_SECRET_SCAN
    assert rejection.relative_paths == (BLOCKED_REL,)


def test_push_cannot_contain_secrets_is_a_secret_rejection() -> None:
    rejection = recovery.classify_publication_push(
        returncode=1, stdout="", stderr="remote: Push cannot contain secrets.\n"
    )
    assert rejection.classification == recovery.REJECTED_SECRET_SCAN


def test_empty_push_output_is_an_unattributed_unknown() -> None:
    rejection = recovery.classify_publication_push(returncode=1, stdout="", stderr="")
    assert rejection.classification == "unknown_failure"
    assert rejection.relative_paths == ()


def test_classifier_failure_degrades_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.sidecar_publication_facade as facade

    def missing_binding(_name: str) -> object:
        raise RuntimeError("sase_core_rs is unavailable")

    monkeypatch.setattr(facade, "require_rust_binding", missing_binding)
    rejection = recovery.classify_publication_push(
        returncode=1, stdout="", stderr=gh013_stderr(BLOCKED_REL)
    )
    assert rejection.classification == "unknown_failure"
    assert rejection.relative_paths == ()


def test_sanitized_secret_error_names_paths_but_never_the_token() -> None:
    rejection = recovery.PublicationPushRejection(
        recovery.REJECTED_SECRET_SCAN, (), (BLOCKED_REL,)
    )
    message = recovery.sanitized_push_error("git push failed", rejection)
    assert BLOCKED_REL in message
    assert TOKEN not in message
    assert "GH013" in message or "secret scanning" in message


def test_sanitized_rule_error_confirms_no_secret() -> None:
    rejection = recovery.PublicationPushRejection(
        recovery.REJECTED_REPOSITORY_RULE, (), ()
    )
    message = recovery.sanitized_push_error("git push failed", rejection)
    assert "no secret was confirmed" in message
