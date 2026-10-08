"""Gate decision repairs: stamping, surfaces, revision, validation, grants."""

from __future__ import annotations

import pytest

VALID_ORDERED = """---
tier: tale
title: Order check
goal: Keep author order.
size: small
decisions:
  zeta:
    ask: Pick zeta value?
    choices:
      b: Second choice
      a: First choice
    default: b
    why: zeta why
  alpha:
    ask: Turn alpha on?
    default: false
---
# Plan

> [!decision] zeta = b Zeta b branch.
> [!decision] alpha Alpha yes branch.
"""


def _needs_core(*names: str) -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    for name in names:
        if not hasattr(core, name):
            pytest.skip(f"stale core without {name}")


def test_stamp_preserves_author_order(tmp_path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.plan_gate_stamp import stamp_direct_file
    from sase.sdd.frontmatter import parse_frontmatter

    plan = tmp_path / "plan.md"
    plan.write_text(VALID_ORDERED, encoding="utf-8")
    stamp_direct_file(
        plan, {"zeta": "b", "alpha": False}, decided_by="reviewer", decided_via="cli"
    )
    frontmatter, _, _ = parse_frontmatter(plan.read_text(encoding="utf-8"))
    assert list(frontmatter["decisions"].keys()) == ["zeta", "alpha"]
    zeta = frontmatter["decisions"]["zeta"]
    assert list(zeta["choices"].keys()) == ["b", "a"]
    assert zeta["ask"].endswith("?")
    assert frontmatter["decided_by"] == "reviewer"
    assert frontmatter["decided_via"] == "cli"


def test_stamp_rejects_unexpected_and_conflicting(tmp_path) -> None:
    _needs_core("plan_decisions_payload")
    from sase.plan_approval_actions import PlanApprovalActionError
    from sase.plan_gate_stamp import stamp_direct_file

    plan = tmp_path / "plan.md"
    plan.write_text(VALID_ORDERED, encoding="utf-8")
    with pytest.raises(PlanApprovalActionError):
        stamp_direct_file(
            plan,
            {"nope": "x", "zeta": "b", "alpha": False},
            decided_by="reviewer",
            decided_via="cli",
        )
    stamp_direct_file(
        plan, {"zeta": "b", "alpha": False}, decided_by="reviewer", decided_via="cli"
    )
    # Identical re-stamp is a no-op.
    stamp_direct_file(
        plan, {"zeta": "b", "alpha": False}, decided_by="reviewer", decided_via="cli"
    )
    with pytest.raises(PlanApprovalActionError):
        stamp_direct_file(
            plan,
            {"zeta": "a", "alpha": False},
            decided_by="reviewer",
            decided_via="cli",
        )
    with pytest.raises(PlanApprovalActionError):
        stamp_direct_file(
            plan, {"zeta": "b", "alpha": False}, decided_by="agent", decided_via="cli"
        )


def test_surfaces_map_to_expected_coordinates() -> None:
    from sase.plan_gate_stamp import _stamp_coordinates

    assert _stamp_coordinates("cli", "human") == ("reviewer", "cli")
    assert _stamp_coordinates("tui", "human") == ("reviewer", "tui")
    assert _stamp_coordinates("plan_response", "human") == ("reviewer", "tui")
    assert _stamp_coordinates("telegram", "human") == ("reviewer", "telegram")
    assert _stamp_coordinates("mobile", "human") == ("reviewer", "mobile")
    assert _stamp_coordinates("cli", "agent") == ("agent", "cli")
    assert _stamp_coordinates("auto_resolution", "human") == ("auto", None)
    from sase.plan_approval_actions import PlanApprovalActionError

    with pytest.raises(PlanApprovalActionError):
        _stamp_coordinates("unknown-surface", "human")


def test_unknown_source_fails_before_acceptance() -> None:
    _needs_core("plan_decisions_resolve")
    from sase.notification_gates.models import GateError
    from sase.plan_gate_decisions import normalize_plan_option_inputs
    from sase.sdd.plan_validate import validate_plan
    from sase.plan_gate import _build_plan_gate_spec
    from pathlib import Path

    validation = validate_plan(VALID_ORDERED, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        Path("/tmp/order.md"),
        "sess-src",
        tier="tale",
        validation=validation,
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    with pytest.raises(GateError) as excinfo:
        normalize_plan_option_inputs(
            dict(spec),
            ["approve", "commit"],
            {},
            source="carrier-pigeon",
            caller="human",
        )
    assert excinfo.value.code == "unknown_source"


def test_caller_for_decide_fails_closed(monkeypatch) -> None:
    from sase.main import plan_decide

    monkeypatch.setattr(
        "sase.notification_gates.executor.gate_response_caller",
        lambda: (_ for _ in ()).throw(RuntimeError("classifier down")),
    )
    assert plan_decide.caller_for_decide() == "agent"
    monkeypatch.setattr(
        "sase.notification_gates.executor.gate_response_caller", lambda: "human"
    )
    assert plan_decide.caller_for_decide() == "human"


def test_review_revision_validation() -> None:
    from sase.notification_gates.cli_answer_inputs import request_review_revision
    from sase.notification_gates.cli_support import GateCliError

    assert request_review_revision({}) is None
    assert request_review_revision({"review_revision": 3}) == 3
    assert request_review_revision({"review_revision": "4"}) == 4
    for bad in (True, False, 1.5, "abc", "", {"n": 1}, [1]):
        with pytest.raises(GateCliError):
            request_review_revision({"review_revision": bad})


def test_detached_payload_carries_revision_and_source(tmp_path) -> None:
    from types import SimpleNamespace
    from pathlib import Path
    from sase.notification_gates import cli_answer_submit as mod

    captured: dict = {}

    class _Proc:
        proc_id = "p1"

    orig = mod.submit_proc_request
    try:

        def _capture(req):  # type: ignore[no-untyped-def]
            captured["payload"] = req.operation_payload
            return _Proc()

        mod.submit_proc_request = _capture  # type: ignore[method-assign]
        opt = SimpleNamespace(id="approve", requires_tty=False)
        fake_bundle = SimpleNamespace(
            request_id="r", kind="plan", response_path=Path("/tmp/x")
        )
        mod.submit_detached_answer(
            fake_bundle,
            (opt,),
            input_data=None,
            feedback=None,  # type: ignore[arg-type]
            retry=None,
            option_inputs=None,
            source="cli",
            review_revision=7,
        )
        payload = captured.get("payload", {})
        assert payload.get("source") == "cli"
        assert payload.get("review_revision") == 7
    finally:
        mod.submit_proc_request = orig  # type: ignore[method-assign]


def test_kind_validation_rejects_reject_decisions(tmp_path) -> None:
    _needs_core("plan_decisions_digest", "plan_decisions_resolve")
    from sase.notification_gates.kind_validation.plan import _validate_plan_decisions
    from sase.notification_gates.models import GateError, GateSpec
    from sase.sdd.plan_validate import validate_plan
    from sase.plan_gate import _build_plan_gate_spec
    from pathlib import Path

    plan_file = tmp_path / "order2.md"
    plan_file.write_text(VALID_ORDERED, encoding="utf-8")
    validation = validate_plan(VALID_ORDERED, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        Path(str(plan_file)),
        "sess-reject",
        tier="tale",
        validation=validation,
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    good = GateSpec.from_mapping(spec)
    _validate_plan_decisions(good, "tale")
    broken = dict(spec)
    broken_options = []
    for option in spec["options"]:
        opt = dict(option)
        if opt["id"] == "reject":
            schema = dict(opt["input_schema"])
            props = dict(schema.get("properties", {}))
            props["decision_zeta"] = {"enum": ["a", "b"]}
            schema["properties"] = props
            opt["input_schema"] = schema
        broken_options.append(opt)
    broken["options"] = broken_options
    with pytest.raises(GateError):
        _validate_plan_decisions(GateSpec.from_mapping(broken), "tale")


def test_future_flat_note_grant(tmp_path, monkeypatch) -> None:
    _needs_core("plan_decisions_payload")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase" / "memory").mkdir(parents=True, exist_ok=True)
    from sase.sdd._plan_decisions_shared import resolve_memory_records

    records, keys = resolve_memory_records(["brand-new-note-xyz.md"])
    assert records and records[0]["exists"] is False
    assert records[0]["kind"] == "note"
    assert records[0]["type"] == "reference"
    assert records[0]["scope"] == "project"
    assert keys == {f"note:project:{records[0]['path']}"}


def test_rebuild_coerces_nonlist_resolved(monkeypatch) -> None:
    from types import SimpleNamespace

    from sase.notification_gates.kind_validation import plan as plan_mod
    from sase.notification_gates.model_request import GateResource, GateSpec, _GateAuto
    import sase.sdd.plan_decisions as decisions_mod
    import sase.sdd.plan_validate as validate_mod

    captured: dict = {}

    def _fake_binding(wired, host_facts):  # type: ignore[no-untyped-def]
        captured.update(host_facts)
        return [{"id": "ok"}]

    monkeypatch.setattr(decisions_mod, "payload_binding", _fake_binding)
    monkeypatch.setattr(decisions_mod, "validated_to_wire_dict", lambda plan: {})
    monkeypatch.setattr(
        validate_mod,
        "validate_plan",
        lambda content, tier, **kwargs: SimpleNamespace(
            ok=True,
            plan=SimpleNamespace(
                decisions=[SimpleNamespace(id="zeta"), SimpleNamespace(id="alpha")]
            ),
        ),
    )
    spec = GateSpec(
        schema_version=3,
        kind="tale_plan",
        request_id="r",
        producer={},
        continuation_mode="plan",
        gate_timeout_seconds=None,
        payload={},
        presentation={},
        query="q",
        options=(),
        groups=(),
        branches=(),
        primary_branch=(),
        operations=(),
        resources=(GateResource(path="plan.md", role="plan", content=VALID_ORDERED),),
        auto=_GateAuto(),
        turn=None,
    )
    rebuilt = plan_mod._rebuild_definitions_from_resource(
        spec,
        "tale",
        [
            {"id": "zeta", "resolved": "not-a-list"},
            {"id": "alpha", "resolved": ("a",)},
        ],
    )
    assert rebuilt == [{"id": "ok"}]
    assert captured["zeta"]["resolved"] == []
    assert captured["alpha"]["resolved"] == ["a"]


def test_future_grant_rejects_traversal_and_unknown_web(tmp_path, monkeypatch) -> None:
    _needs_core("plan_decisions_payload")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase" / "memory").mkdir(parents=True, exist_ok=True)
    from sase.sdd._plan_decisions_shared import (
        PlanDecisionError,
        resolve_memory_records,
    )

    with pytest.raises(PlanDecisionError):
        resolve_memory_records(["../escape.md"])
    with pytest.raises(PlanDecisionError):
        resolve_memory_records(["no-such-web-xyz:missing-strand"])
