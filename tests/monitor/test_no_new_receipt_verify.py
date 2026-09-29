"""No-new receipt verification gate."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.monitor.no_new_receipt import (
    NoNewEvidence,
    _intent_accept,
    evidence_provenance,
    is_no_new_intent,
    verify_no_new_receipt,
)

from ._no_new_receipt import make_meta, receipt

pytest_plugins = ("tests.monitor._no_new_receipt",)

__all__ = [
    "test_intent_accept_defaults_to_pass",
    "test_verify_accepts_pass_verdict_under_no_new_lookup",
    "test_verify_happy_path_returns_auditable_evidence",
    "test_verify_refuses_multi_repo_all_or_nothing",
    "test_verify_rejects_command_verdict_and_policy_mismatch",
    "test_verify_rejects_non_verify_and_unrelated_outcomes",
    "test_verify_rejects_unsettled_lost_and_unowned_runs",
    "test_verify_rejects_wrong_source_run_and_changed_receipt",
    "test_verify_retains_typed_receipt_refusals",
]


def _observation(
    repo_id: str, *, name: str = "sase", kind: str = "main"
) -> dict[str, Any]:
    digest = "a" * 64
    return {
        "repo_id": repo_id,
        "kind": kind,
        "name": name,
        "head": digest,
        "head_tree": digest,
        "index_tree": digest,
        "complete": True,
        "paths": [],
    }


def _no_new_intent(*repo_ids: str) -> dict[str, Any]:
    repos = list(repo_ids) or ["repo-main"]
    repositories = [
        {"repo_id": repo_id, "action": "commit", "message": "fix: it"}
        for repo_id in repos
    ]
    observations = [
        _observation(
            repo_id,
            name="sase" if repo_id == "repo-main" else repo_id,
            kind="main" if repo_id == "repo-main" else "sibling",
        )
        for repo_id in repos
    ]
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "cci:no-new",
        "kind": "conditional_completion",
        "status": "bound",
        "success_message": "Checks done.",
        "declaration": {
            "payloads": [
                {
                    "instance_id": "commit",
                    "payload": {
                        "repositories": repositories,
                        "deferrals": [],
                    },
                }
            ]
        },
        "repository_decisions": repositories,
        "observations": observations,
        "seal": {"policy_version": 1},
        "verification": {"command": ["just", "check"], "level": "check"},
        "binding": {"monitor_id": "monitor-1"},
        "accept": "no_new_failures",
    }


def test_intent_accept_defaults_to_pass() -> None:
    assert _intent_accept({}) == "pass"
    assert _intent_accept({"accept": None}) == "pass"
    assert is_no_new_intent({}) is False
    assert is_no_new_intent({"accept": "no_new_failures"}) is True
    assert is_no_new_intent({"accept": "pass"}) is False


def test_verify_happy_path_returns_auditable_evidence(
    tool_doubles: dict[str, Any],
) -> None:
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )

    assert reason is None
    assert isinstance(evidence, NoNewEvidence)
    assert evidence.receipt_id == "rc-1"
    assert evidence.run_id == "run-1"
    assert evidence.verdict == "no_new_failures"
    assert evidence.known_signatures == ("known:flake-1",)
    provenance = evidence_provenance(evidence)
    assert provenance["receipt_id"] == "rc-1"
    assert provenance["run_id"] == "run-1"
    assert provenance["verdict"] == "no_new_failures"
    assert provenance["known_signatures"] == ["known:flake-1"]


@pytest.mark.parametrize(
    ("meta_override", "monitor_state", "expected"),
    [
        ({"monitor_profile": "other"}, "failed", "no_new_requires_verify"),
        ({"monitor_profile": None}, "failed", "no_new_requires_verify"),
        ({"monitor_tool_run_id": None}, "failed", "no_new_missing_tool_run"),
        ({}, "timeout", "no_new_unsupported_outcome"),
        ({}, "stopped", "no_new_unsupported_outcome"),
        ({}, "lost", "no_new_unsupported_outcome"),
        ({}, "unknown", "no_new_unsupported_outcome"),
    ],
)
def test_verify_rejects_non_verify_and_unrelated_outcomes(
    tool_doubles: dict[str, Any],
    meta_override: dict[str, Any],
    monitor_state: str,
    expected: str,
) -> None:
    meta = make_meta()
    for key, value in meta_override.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=meta, monitor_state=monitor_state
    )

    assert evidence is None
    assert reason is not None and expected in reason


def test_verify_rejects_unsettled_lost_and_unowned_runs(
    tool_doubles: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for state, expected in [
        ("created", "no_new_run_unsettled"),
        ("running", "no_new_run_unsettled"),
        ("lost", "no_new_run_lost"),
    ]:
        tool_doubles["run"]["state"] = state
        evidence, reason = verify_no_new_receipt(
            intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
        )
        assert evidence is None
        assert reason is not None and expected in reason
    tool_doubles["run"]["state"] = "failed"

    tool_doubles["run"]["owner_kind"] = None
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_missing_owner_link" in reason

    tool_doubles["run"]["owner_kind"] = "monitor"
    tool_doubles["run"]["owner_id"] = "monitor-other"
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_unrelated_tool_run" in reason


def test_verify_rejects_command_verdict_and_policy_mismatch(
    tool_doubles: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_doubles["run"]["tool_name"] = "check-full"
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_command_mismatch" in reason
    tool_doubles["run"]["tool_name"] = "check"

    for verdict in ("new_failures", "undetermined", ""):
        tool_doubles["triage"] = {"verdict": verdict}
        evidence, reason = verify_no_new_receipt(
            intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
        )
        assert reason is not None and "no_new_verdict_insufficient" in reason
    tool_doubles["triage"] = {"verdict": "no_new_failures"}

    monkeypatch.setattr(
        "sase.tool.receipts.receipt_policy_for_resolved",
        lambda _resolved: {"accept": ["pass"], "ttl": "2h"},
    )
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_policy_changed" in reason


@pytest.mark.parametrize(
    ("lookup", "expected"),
    [
        (
            {"outcome": "refused", "refusal": "expired", "reason": "expired"},
            "no_new_receipt_expired",
        ),
        (
            {
                "outcome": "refused",
                "refusal": "invalidated_by_later_run",
                "reason": "invalidated",
            },
            "no_new_receipt_invalidated_by_later_run",
        ),
        (
            {"outcome": "refused", "refusal": "no_receipt", "reason": "none"},
            "no_new_receipt_no_receipt",
        ),
        (
            {
                "outcome": "refused",
                "refusal": "fingerprint_changed",
                "reason": "drift",
            },
            "no_new_receipt_fingerprint_changed",
        ),
        (
            {
                "outcome": "refused",
                "refusal": "definition_changed",
                "reason": "definition",
            },
            "no_new_receipt_definition_changed",
        ),
        (
            {
                "outcome": "refused",
                "refusal": "verdict_insufficient",
                "reason": "verdict",
            },
            "no_new_receipt_verdict_insufficient",
        ),
        (
            {
                "outcome": "refused",
                "refusal": "incomplete_fingerprint",
                "reason": "incomplete",
            },
            "no_new_receipt_incomplete_fingerprint",
        ),
    ],
)
def test_verify_retains_typed_receipt_refusals(
    tool_doubles: dict[str, Any], lookup: dict[str, Any], expected: str
) -> None:
    tool_doubles["lookup"] = lookup

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )

    assert evidence is None
    assert reason is not None and expected in reason


def test_verify_rejects_wrong_source_run_and_changed_receipt(
    tool_doubles: dict[str, Any],
) -> None:
    tool_doubles["lookup"] = {
        "outcome": "covered",
        "receipt": receipt(source_run_id="run-other"),
    }
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_wrong_source_run" in reason

    tool_doubles["lookup"] = {"outcome": "covered", "receipt": receipt()}
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(),
        meta=make_meta(),
        monitor_state="failed",
        expected_receipt_id="rc-other",
        expected_run_id="run-1",
    )
    assert reason is not None and "no_new_receipt_changed" in reason

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(),
        meta=make_meta(),
        monitor_state="failed",
        expected_receipt_id="rc-1",
        expected_run_id="run-other",
    )
    assert reason is not None and "no_new_wrong_source_run" in reason


def test_verify_refuses_multi_repo_all_or_nothing(
    tool_doubles: dict[str, Any],
) -> None:
    intent = _no_new_intent("repo-main", "repo-side")

    evidence, reason = verify_no_new_receipt(
        intent=intent, meta=make_meta(), monitor_state="failed"
    )

    assert evidence is None
    assert reason is not None and "no_new_incomplete_coverage" in reason


def test_verify_accepts_pass_verdict_under_no_new_lookup(
    tool_doubles: dict[str, Any],
) -> None:
    tool_doubles["triage"] = {"verdict": "pass"}
    tool_doubles["lookup"] = {
        "outcome": "covered",
        "receipt": receipt(verdict="pass", signature_refs=[]),
    }

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=make_meta(), monitor_state="completed"
    )

    assert reason is None
    assert evidence is not None and evidence.verdict == "pass"
    assert evidence.known_signatures == ()
