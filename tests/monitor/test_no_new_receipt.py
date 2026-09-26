"""E4 verdict-completion: explicit no-new prepared completion on receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.prepare import (
    format_prepare_preview,
    prepare_conditional_completion,
)
from sase.monitor.host_completion import settle_host_completion
from sase.monitor.no_new_receipt import (
    NoNewEvidence,
    evidence_provenance,
    intent_accept,
    is_no_new_intent,
    verify_no_new_receipt,
)
from sase.monitor.output import OutputCapture
from sase.shells.followup import FollowupLaunchResult

from ..finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _core_supports_no_new() -> bool:
    """Return whether the installed core seals the accept policy.

    The sase-core revision pin moves past the accept-capable core commit
    after that commit lands; until then no-new tests skip instead of
    failing against a core that seals every intent as pass.
    """

    try:
        from sase.core.continuation_facade import seal_conditional_completion
        from tests.core._continuation_facade_helpers import (
            make_prepare_request,
        )

        request = make_prepare_request()
        request["accept"] = "no_new_failures"
        intent = seal_conditional_completion(request)
        return intent.get("accept") == "no_new_failures"
    except Exception:  # noqa: BLE001 - any failure means unsupported.
        return False


needs_no_new_core = pytest.mark.skipif(
    not _core_supports_no_new(),
    reason="installed core predates the sealed accept policy",
)


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


def _meta(**overrides: object) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": "cci:no-new",
        "monitor_profile": "verify",
        "monitor_tool_run_id": "run-1",
        "monitor_cwd": "/repo",
        "monitor_command": "just check",
        "monitor_execution_argv": ["just", "check"],
        "workspace_dir": "/ws/20",
        "continuation_monitor_result_id": "result-1",
    }
    meta.update(overrides)
    return meta


class _Resolved:
    tool_name = "check"
    digest = "d" * 64
    adhoc = False
    definition = {"receipt": {"accept": ["pass", "no_new_failures"]}}

    def resolved_project_identity(self) -> str:
        return "sase"


def _fingerprint(*identities: str) -> dict[str, Any]:
    repos = list(identities) or ["sase"]
    return {
        "schema_version": 1,
        "definition_digest": "d" * 64,
        "extra_args_digest": "e" * 64,
        "repos": [{"identity": identity} for identity in repos],
        "completeness": {"complete": True, "missing": []},
    }


def _receipt(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "receipt_id": "rc-1",
        "source_run_id": "run-1",
        "verdict": "no_new_failures",
        "signature_refs": [
            {
                "extractor": "triage",
                "extractor_version": 1,
                "signature": "known:flake-1",
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def _tool_doubles(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Wire the settled ToolRun, triage, fingerprint, and receipt doubles."""

    run = {
        "run_id": "run-1",
        "state": "failed",
        "tool_name": "check",
        "definition_digest": "d" * 64,
        "extra_args_digest": "e" * 64,
        "owner_kind": "monitor",
        "owner_id": "monitor-1",
        "project": "sase",
        "exit_code": 1,
    }
    lookup = {"outcome": "covered", "receipt": _receipt(), "refusal": None}
    doubles = {
        "run": run,
        "triage": {"verdict": "no_new_failures"},
        "fingerprint": _fingerprint(),
        "lookup": lookup,
    }
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_show",
        lambda _run_id: {"run": dict(doubles["run"])},
    )
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_triage_show",
        lambda _request: dict(doubles["triage"]),
    )
    monkeypatch.setattr(
        "sase.tool.argv.resolve_run_argv",
        lambda _words, **_kwargs: _Resolved(),
    )
    monkeypatch.setattr(
        "sase.tool.receipts.receipt_policy_for_resolved",
        lambda _resolved: {"accept": ["pass", "no_new_failures"], "ttl": "2h"},
    )
    monkeypatch.setattr(
        "sase.tool.observe.observe_fingerprint",
        lambda _resolved: dict(doubles["fingerprint"]),
    )
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_receipt_lookup",
        lambda _payload: dict(doubles["lookup"]),
    )
    return doubles


def test_intent_accept_defaults_to_pass() -> None:
    assert intent_accept({}) == "pass"
    assert intent_accept({"accept": None}) == "pass"
    assert is_no_new_intent({}) is False
    assert is_no_new_intent({"accept": "no_new_failures"}) is True
    assert is_no_new_intent({"accept": "pass"}) is False


def test_verify_happy_path_returns_auditable_evidence(
    _tool_doubles: dict[str, Any],
) -> None:
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
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
    _tool_doubles: dict[str, Any],
    meta_override: dict[str, Any],
    monitor_state: str,
    expected: str,
) -> None:
    meta = _meta()
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
    _tool_doubles: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for state, expected in [
        ("created", "no_new_run_unsettled"),
        ("running", "no_new_run_unsettled"),
        ("lost", "no_new_run_lost"),
    ]:
        _tool_doubles["run"]["state"] = state
        evidence, reason = verify_no_new_receipt(
            intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
        )
        assert evidence is None
        assert reason is not None and expected in reason
    _tool_doubles["run"]["state"] = "failed"

    _tool_doubles["run"]["owner_kind"] = None
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_missing_owner_link" in reason

    _tool_doubles["run"]["owner_kind"] = "monitor"
    _tool_doubles["run"]["owner_id"] = "monitor-other"
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_unrelated_tool_run" in reason


def test_verify_rejects_command_verdict_and_policy_mismatch(
    _tool_doubles: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _tool_doubles["run"]["tool_name"] = "check-full"
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_command_mismatch" in reason
    _tool_doubles["run"]["tool_name"] = "check"

    for verdict in ("new_failures", "undetermined", ""):
        _tool_doubles["triage"] = {"verdict": verdict}
        evidence, reason = verify_no_new_receipt(
            intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
        )
        assert reason is not None and "no_new_verdict_insufficient" in reason
    _tool_doubles["triage"] = {"verdict": "no_new_failures"}

    monkeypatch.setattr(
        "sase.tool.receipts.receipt_policy_for_resolved",
        lambda _resolved: {"accept": ["pass"], "ttl": "2h"},
    )
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
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
    _tool_doubles: dict[str, Any], lookup: dict[str, Any], expected: str
) -> None:
    _tool_doubles["lookup"] = lookup

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
    )

    assert evidence is None
    assert reason is not None and expected in reason


def test_verify_rejects_wrong_source_run_and_changed_receipt(
    _tool_doubles: dict[str, Any],
) -> None:
    _tool_doubles["lookup"] = {
        "outcome": "covered",
        "receipt": _receipt(source_run_id="run-other"),
    }
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="failed"
    )
    assert reason is not None and "no_new_wrong_source_run" in reason

    _tool_doubles["lookup"] = {"outcome": "covered", "receipt": _receipt()}
    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(),
        meta=_meta(),
        monitor_state="failed",
        expected_receipt_id="rc-other",
        expected_run_id="run-1",
    )
    assert reason is not None and "no_new_receipt_changed" in reason

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(),
        meta=_meta(),
        monitor_state="failed",
        expected_receipt_id="rc-1",
        expected_run_id="run-other",
    )
    assert reason is not None and "no_new_wrong_source_run" in reason


def test_verify_refuses_multi_repo_all_or_nothing(
    _tool_doubles: dict[str, Any],
) -> None:
    intent = _no_new_intent("repo-main", "repo-side")

    evidence, reason = verify_no_new_receipt(
        intent=intent, meta=_meta(), monitor_state="failed"
    )

    assert evidence is None
    assert reason is not None and "no_new_incomplete_coverage" in reason


def test_verify_accepts_pass_verdict_under_no_new_lookup(
    _tool_doubles: dict[str, Any],
) -> None:
    _tool_doubles["triage"] = {"verdict": "pass"}
    _tool_doubles["lookup"] = {
        "outcome": "covered",
        "receipt": _receipt(verdict="pass", signature_refs=[]),
    }

    evidence, reason = verify_no_new_receipt(
        intent=_no_new_intent(), meta=_meta(), monitor_state="completed"
    )

    assert reason is None
    assert evidence is not None and evidence.verdict == "pass"
    assert evidence.known_signatures == ()


def test_prepare_defaults_to_pass_and_rejects_malformed_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [
            {
                "repo_id": repo_id,
                "kind": "main",
                "name": "main",
                "head": "a" * 64,
                "head_tree": "a" * 64,
                "index_tree": "a" * 64,
                "complete": True,
                "paths": [],
            }
        ],
    )

    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check"]},
        "declaration": valid_manifest(publication),
    }
    prepared = prepare_conditional_completion(wrapper)
    assert prepared.intent.get("accept", "pass") == "pass"
    assert "accept" not in format_prepare_preview(prepared, json_output=False)

    with pytest.raises(FinalizerDeclarationError, match="must be 'pass'"):
        prepare_conditional_completion(dict(wrapper, accept="sometimes"))
    with pytest.raises(FinalizerDeclarationError, match="must be 'pass'"):
        prepare_conditional_completion(dict(wrapper, accept=7))


@needs_no_new_core
def test_prepare_seals_explicit_no_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [
            {
                "repo_id": repo_id,
                "kind": "main",
                "name": "main",
                "head": "a" * 64,
                "head_tree": "a" * 64,
                "index_tree": "a" * 64,
                "complete": True,
                "paths": [],
            }
        ],
    )
    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check"]},
        "declaration": valid_manifest(publication),
        "accept": "no-new",
    }

    prepared = prepare_conditional_completion(wrapper)

    assert prepared.intent["accept"] == "no_new_failures"
    assert "accept" in format_prepare_preview(prepared, json_output=False)


def _settle_arguments(
    artifacts: Path,
    meta: dict[str, Any],
    recoveries: list[dict[str, Any]],
    *,
    monitor_state: str = "failed",
    exit_code: int | None = 1,
) -> dict[str, Any]:
    def launch_recovery(
        artifacts_dir: str,
        meta: dict[str, Any],
        *,
        monitor_state: str,
        exit_code: int | None,
        elapsed_seconds: float,
        capture: OutputCapture,
        project_name: str,
        timeout_kind: str | None = None,
        transfer_from_pid: int | None = None,
    ) -> FollowupLaunchResult:
        recoveries.append({"exit_code": exit_code, "monitor_state": monitor_state})
        return FollowupLaunchResult(launched=True, agent_name="acme--2")

    return {
        "monitor_state": monitor_state,
        "exit_code": exit_code,
        "elapsed_seconds": 60,
        "project_name": "proj",
        "capture": OutputCapture(),
        "launch_recovery": launch_recovery,
        "release_claim": lambda _meta, _project: None,
    }


def _real_bound_intent(*, accept: str = "no_new_failures") -> dict[str, Any]:
    """Seal and bind a real intent so strict Rust validation accepts it."""

    from sase.core.continuation_facade import (
        bind_conditional_completion,
        seal_conditional_completion,
    )
    from tests.core._continuation_facade_helpers import make_prepare_request

    request = make_prepare_request()
    request["accept"] = accept
    prepared = seal_conditional_completion(request)
    return bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )


def _patch_completion_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    intent: dict[str, Any],
    verify: tuple[Any, Any],
) -> None:
    import sase.monitor.host_completion as host_completion

    monkeypatch.setattr(
        host_completion,
        "load_prepared_completion",
        lambda _ref, artifacts_dir=None: dict(intent),
    )
    snapshot = MagicMock()
    snapshot.plan.entries = []
    snapshot.plan.plan_digest = "p" * 64
    snapshot.obligation_ids = ()
    snapshot.observation_fingerprint = ()
    snapshot.publication.context.obligations = []
    monkeypatch.setattr(
        host_completion, "_snapshot_execution_context", lambda *_a, **_k: snapshot
    )
    monkeypatch.setattr(
        host_completion,
        "_evaluate_intent",
        lambda *_a, **_k: {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "eligible": True,
            "action": "complete",
            "reason": None,
            "reasons": [],
            "rendered_message": "done",
        },
    )
    monkeypatch.setattr(host_completion, "_verify_no_new_receipt", lambda **_k: verify)
    monkeypatch.setattr(
        host_completion,
        "consume_conditional_completion",
        lambda request: dict(request.get("intent") or {}),
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion_state.publish_final_context",
        lambda artifacts_dir=None: snapshot.publication,
    )


@needs_no_new_core
def test_host_completion_no_new_persists_verdict_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion as host_completion
    from sase.monitor.delivery import load_host_completion_receipt

    intent = _real_bound_intent()
    evidence = NoNewEvidence(
        receipt_id="rc-1",
        run_id="run-1",
        verdict="no_new_failures",
        known_signatures=("known:flake-1",),
        accept="no_new_failures",
        tool_name="check",
    )
    _patch_completion_harness(monkeypatch, intent=intent, verify=(evidence, None))
    monkeypatch.setattr(
        host_completion,
        "can_finish_without_rerun",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        host_completion, "_install_prepared_declaration", lambda *_a, **_k: None
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = _meta()
    recoveries: list[dict[str, Any]] = []

    settlement = settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert recoveries == []
    assert settlement is not None
    assert settlement.launch_result is not None
    assert settlement.launch_result.host_completed is True
    receipt = load_host_completion_receipt(str(artifacts))
    assert receipt is not None and receipt.get("status") == "completed"
    verdict = receipt.get("verdict_receipt")
    assert verdict["receipt_id"] == "rc-1"
    assert verdict["run_id"] == "run-1"
    assert verdict["verdict"] == "no_new_failures"
    assert verdict["known_signatures"] == ["known:flake-1"]


@needs_no_new_core
def test_host_completion_no_new_refusal_recovers_with_typed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _real_bound_intent()
    _patch_completion_harness(
        monkeypatch, intent=intent, verify=(None, "no_new_receipt_expired")
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = _meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(recoveries) == 1
    # The monitored child exit stays nonzero through recovery.
    assert recoveries[0]["exit_code"] == 1
    assert recoveries[0]["monitor_state"] == "failed"


@needs_no_new_core
def test_host_completion_no_new_shortcut_still_runs_precommit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion as host_completion

    intent = _real_bound_intent()
    evidence = NoNewEvidence(
        receipt_id="rc-1",
        run_id="run-1",
        verdict="no_new_failures",
        known_signatures=(),
        accept="no_new_failures",
        tool_name="check",
    )
    _patch_completion_harness(monkeypatch, intent=intent, verify=(evidence, None))
    monkeypatch.setattr(
        host_completion, "can_finish_without_rerun", lambda *_a, **_k: True
    )
    calls: list[dict[str, Any]] = []
    real_verify = host_completion._verify_no_new_receipt

    def _gated(**kwargs: Any) -> tuple[Any, Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return evidence, None
        return None, "no_new_receipt_fingerprint_changed"

    monkeypatch.setattr(host_completion, "_verify_no_new_receipt", _gated)
    assert real_verify is not None
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = _meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(calls) == 2
    assert calls[1].get("expected_receipt_id") == "rc-1"
    assert calls[1].get("expected_run_id") == "run-1"
    assert len(recoveries) == 1


@needs_no_new_core
def test_host_completion_resume_reruns_gate_instead_of_trusting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import sase.monitor.host_completion as host_completion
    from sase.monitor.delivery import persist_host_completion_receipt

    intent = _real_bound_intent()
    _patch_completion_harness(
        monkeypatch,
        intent=intent,
        verify=(None, "no_new_receipt_fingerprint_changed"),
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    # A successful marker exists but the obligated repo is still outstanding:
    # this is a resumed host completion, which must re-run the gate.
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "repo_id": "repo-other",
                    "result": "ok",
                    "commit_sha": "s" * 40,
                    "cwd": "/other",
                }
            ]
        ),
        encoding="utf-8",
    )
    persist_host_completion_receipt(
        str(artifacts),
        {
            "schema_version": 1,
            "status": "finalizing",
            "intent_ref": "cci:no-new",
            "verdict_receipt": {
                "receipt_id": "rc-1",
                "run_id": "run-1",
                "verdict": "no_new_failures",
                "known_signatures": [],
            },
        },
    )
    monkeypatch.setattr(
        host_completion,
        "run_finalizers",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must refuse before any commit action")
        ),
    )
    meta = _meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(recoveries) == 1


def test_host_completion_pass_intent_never_calls_receipt_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion as host_completion

    intent = _real_bound_intent(accept="pass")
    _patch_completion_harness(monkeypatch, intent=intent, verify=(None, "must-not-run"))
    monkeypatch.setattr(
        host_completion, "can_finish_without_rerun", lambda *_a, **_k: True
    )
    called: list[dict[str, Any]] = []

    def _fail_on_call(**kwargs: Any) -> tuple[Any, Any]:
        called.append(kwargs)
        raise AssertionError("receipt gate must not run for pass intents")

    monkeypatch.setattr(host_completion, "_verify_no_new_receipt", _fail_on_call)
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = _meta()
    recoveries: list[dict[str, Any]] = []

    settlement = settle_host_completion(
        str(artifacts),
        meta,
        **_settle_arguments(
            artifacts, meta, recoveries, monitor_state="completed", exit_code=0
        ),
    )

    assert called == []
    assert recoveries == []
    assert settlement is not None
    assert settlement.launch_result is not None
    assert settlement.launch_result.host_completed is True


@needs_no_new_core
def test_freeze_failed_no_new_enters_host_completion() -> None:
    from sase.monitor.outcome_policy import freeze_start_outcome_policy
    from sase.monitor.request import StartMonitorRequest

    request = StartMonitorRequest(
        command="just check",
        reason="verify",
        timeout_seconds=60,
        cwd="/repo",
        project_name="sase",
        start_status="running",
        stop_status="done",
        profile="verify",
        completion_ref="cci:no-new",
    )

    frozen = freeze_start_outcome_policy(
        request, prepared_completion_accept="no_new_failures"
    )

    assert frozen is not None
    branches = frozen["branches"]
    assert branches["failed"]["action"] == "complete"
    assert branches["failed"]["completion_ref"] == "cci:no-new"
    assert branches["completed"]["action"] == "complete"
    assert branches["timeout"]["action"] == "continue"
    assert branches["stopped"]["action"] == "none"
    assert branches["lost"]["action"] == "none"


def test_freeze_failed_pass_stays_on_recovery() -> None:
    from sase.monitor.outcome_policy import freeze_start_outcome_policy
    from sase.monitor.request import StartMonitorRequest

    request = StartMonitorRequest(
        command="just check",
        reason="verify",
        timeout_seconds=60,
        cwd="/repo",
        project_name="sase",
        start_status="running",
        stop_status="done",
        profile="verify",
        completion_ref="cci:test",
    )

    frozen = freeze_start_outcome_policy(request)

    assert frozen is not None
    assert frozen["branches"]["failed"]["action"] == "continue"


def test_ordinary_submit_records_unverified_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.finalizers.declaration import submit_final_manifest

    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    manifest = valid_manifest(publication)

    payload = submit_final_manifest(manifest)

    assert payload["verdict_provenance"] == "unverified"
