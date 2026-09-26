"""Tests for the ``llm.model_policy`` doctor check."""

from __future__ import annotations

import pytest

from sase.doctor.checks_providers_registry import check_llm_shipped_model_policy
from sase.llm_provider import model_manifest, model_policy


def test_shipped_model_policy_reports_ok(
    real_model_alias_defaults: None,
) -> None:
    check = check_llm_shipped_model_policy()

    assert check.id == "llm.model_policy"
    assert check.status == "OK"
    assert check.data["violation_count"] == 0


def test_shipped_model_policy_warns_on_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    violation = model_policy.PolicyViolation(
        alias="medium",
        member="claude/c-larg@xhigh",
        message="unknown model",
        suggestion="fix it",
    )
    monkeypatch.setattr(
        model_policy, "validate_manifest_policy", lambda _manifest: (violation,)
    )

    check = check_llm_shipped_model_policy()

    assert check.status == "WARN"
    assert check.data == {"violation_count": 1}
    assert any("c-larg" in detail for detail in check.details)


def test_shipped_model_policy_errors_when_manifest_wont_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> model_manifest.ModelManifest:
        raise RuntimeError("no manifest here")

    monkeypatch.setattr(model_manifest, "get_model_manifest", _boom)

    check = check_llm_shipped_model_policy()

    assert check.status == "ERROR"
    assert "could not be loaded" in check.summary
