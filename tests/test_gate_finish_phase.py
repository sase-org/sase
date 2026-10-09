"""Gate finish phase: answer reuse, durable rejections, restamp, keys, guard, receipts."""

from __future__ import annotations

from pathlib import Path

import pytest


PENDING_EPIC = """---
tier: epic
title: Epic demo
goal: Ship the epic.
phases:
  - id: implementation
    title: Implement
    depends_on: []
    description: "implementation: build it."
    size: small
decisions:
  zeta:
    ask: Pick zeta?
    choices:
      b: Bee
      a: Ay
    default: b
  alpha:
    ask: Pick alpha?
    choices:
      b: Bee
      a: Ay
    default: b
---
# Plan

> [!decision] zeta = b Zee.
"""

PENDING_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  zeta:
    ask: Pick zeta?
    choices:
      b: Bee
      a: Ay
    default: b
  alpha:
    ask: Pick alpha?
    choices:
      b: Bee
      a: Ay
    default: b
---
# Plan

> [!decision] zeta = b Zee.
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_bead_reuse_partial_stamp_raises(tmp_path: Path) -> None:
    from sase.bead.cli_work_from_plan import _reuse_stamped_bead_work_answers
    from sase.bead.cli_work_from_plan_types import PlanFileWorkError
    from sase.sdd.plan_validate import validate_plan_file

    plan = _write(
        tmp_path / "plan.md",
        PENDING_EPIC.replace("zeta:\n", "zeta:\n    answer: b\n"),
    )
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok
    frontmatter = {"decisions": {"zeta": {"answer": "b"}}, "decided_by": "reviewer"}
    with pytest.raises(PlanFileWorkError, match="missing accepted answers"):
        _reuse_stamped_bead_work_answers(plan, frontmatter, validation)


def test_bead_reuse_invalid_attribution_raises(tmp_path: Path) -> None:
    from sase.bead.cli_work_from_plan import _reuse_stamped_bead_work_answers
    from sase.bead.cli_work_from_plan_types import PlanFileWorkError
    from sase.sdd.plan_validate import validate_plan_file

    plan = _write(tmp_path / "plan.md", PENDING_EPIC)
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok
    frontmatter = {
        "decisions": {"zeta": {"answer": "b"}, "alpha": {"answer": "b"}},
        "decided_by": "nobody",
    }
    with pytest.raises(PlanFileWorkError, match="invalid acceptance attribution"):
        _reuse_stamped_bead_work_answers(plan, frontmatter, validation)


def test_bead_reuse_does_not_resolve(tmp_path: Path, monkeypatch) -> None:
    from sase.bead import cli_work_from_plan as bead_module
    from sase.sdd.plan_validate import validate_plan_file

    plan = _write(tmp_path / "plan.md", PENDING_EPIC)
    from sase.plan_gate_stamp import stamp_direct_file

    stamp_direct_file(
        plan,
        {"zeta": "b", "alpha": "b"},
        decided_by="reviewer",
        decided_via="cli",
    )

    def _fail(*args, **kwargs):
        raise AssertionError("resolver must not run for accepted plans")

    monkeypatch.setattr(
        "sase.sdd.plan_decisions.resolve_plan_decisions_for_direct_approval", _fail
    )
    monkeypatch.setattr("sase.sdd.plan_decisions.build_definitions", _fail)
    validation = validate_plan_file(plan, "epic", mode="launch")
    bead_module._stamp_bead_work_decisions(plan, validation, dry_run=False)
    bead_module._stamp_bead_work_decisions(plan, validation, dry_run=True)


def test_strip_private_keys_decision_free() -> None:
    from sase.plan_approval_actions import _stamp_decisions_best_effort

    class _Note:
        pass

    response = {"_gate_source": "cli", "_gate_caller": "human", "action": "approve"}
    _stamp_decisions_best_effort(_Note(), response, None, None)  # type: ignore[arg-type]
    assert "_gate_source" not in response
    assert "_gate_caller" not in response


def test_quiet_receipt_predicate() -> None:
    from sase.sdd.plan_decision_handoff import is_quiet_decision_receipt

    good = {
        "silent": True,
        "muted": False,
        "tags": ["plan_decisions_receipt"],
        "action": None,
    }
    assert is_quiet_decision_receipt(good) is True
    assert is_quiet_decision_receipt({**good, "silent": False}) is False
    assert is_quiet_decision_receipt({**good, "muted": True}) is False
    assert is_quiet_decision_receipt({**good, "action": "HITL"}) is False
    assert is_quiet_decision_receipt({**good, "tags": ["other"]}) is False


def test_quiet_receipt_visible_on_direct_page(tmp_path: Path, monkeypatch) -> None:
    from sase.sdd.plan_decision_handoff import post_auto_approval_receipt

    monkeypatch.setenv("SASE_NOTIFICATIONS_DIR", str(tmp_path / "notes"))
    sheet = {"rows": [{"id": "zeta", "value": "b"}]}
    assert (
        post_auto_approval_receipt(request_id="r1", plan_label="Demo", sheet=sheet)
        is True
    )
    assert (
        post_auto_approval_receipt(request_id="r1", plan_label="Demo", sheet=sheet)
        is True
    )
    assert (
        post_auto_approval_receipt(request_id="r2", plan_label="Demo", sheet={})
        is False
    )
    assert (
        post_auto_approval_receipt(
            request_id="r3", plan_label="Demo", sheet={"rows": []}
        )
        is False
    )


def test_write_acceptance_meta_privatized() -> None:
    import sase.notification_gates.decision as decision

    assert not hasattr(decision, "write_acceptance_meta")
    assert hasattr(decision, "_write_acceptance_meta")
    assert "write_acceptance_meta" not in decision.__all__


def test_direct_resolver_freezes_definitions_once(tmp_path: Path, monkeypatch) -> None:
    from sase.main.plan_decide import resolve_direct_decisions
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok
    calls = {"build": 0}
    import sase.sdd.plan_decisions as decisions_mod
    import sase.sdd.plan_decisions_host as host_mod

    real_build = host_mod.build_definitions

    def _counting(validation_arg, directory=""):
        calls["build"] += 1
        return real_build(validation_arg, directory)

    # Patch where the resolver actually looks the name up: the host module
    # global read by resolve_plan_decisions_for_direct_approval, plus the
    # facade attribute read by resolve_direct_decisions. Either lookup must
    # build exactly once per call, never rebuild inside the host.
    monkeypatch.setattr(host_mod, "build_definitions", _counting)
    monkeypatch.setattr(decisions_mod, "build_definitions", _counting)
    resolved = resolve_direct_decisions(validation, {"zeta": "a"}, caller="human")
    assert resolved is not None
    values, rows, sheet, definitions = resolved
    assert values["zeta"] == "a"
    assert any(d.get("id") == "zeta" for d in definitions)
    assert calls["build"] == 1

    calls["build"] = 0
    hosted = host_mod.resolve_plan_decisions_for_direct_approval(
        validation, {"zeta": "a"}, "human"
    )
    assert hosted["values"]["zeta"] == "a"
    assert calls["build"] == 1


def test_structured_grant_wording_independent(tmp_path: Path, monkeypatch) -> None:
    from sase.sdd._plan_decisions_shared import _grant_record_for_missing_selector

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase" / "memory").mkdir(parents=True)
    grant = _grant_record_for_missing_selector(
        "notarealnote12345.md", Exception("boom")
    )
    assert grant is not None
    records, _keys = grant
    assert records[0]["exists"] is False
    # Unknown web never grants, even when wording changes.
    exc = Exception("totally different wording")
    try:
        exc.reason = "unknown_web"  # type: ignore[attr-defined]
    except Exception:
        pass
    assert _grant_record_for_missing_selector("nosuchweb:kw", exc) is None
    # Ambiguous never grants.
    amb = Exception("different wording here")
    try:
        amb.reason = "ambiguous"  # type: ignore[attr-defined]
    except Exception:
        pass
    assert _grant_record_for_missing_selector("glossary:plan", amb) is None


def test_guard_strand_coverage() -> None:
    from sase.finalizers import commit_memory_guard as guard

    rows = [
        {
            "value": True,
            "memory": {
                "selectors": ["glossary:plan-decision"],
                "resolved": [
                    {
                        "kind": "strand",
                        "path": "sase/memory/glossary/plan-decision.md",
                    }
                ],
            },
        }
    ]
    coverage = guard._coverage_from_sheet_rows(rows)
    assert "sase/memory/glossary/plan-decision.md" in coverage.exact
    assert "sase/memory/glossary/other.md" not in coverage.exact


def test_recover_stamp_never_invents_answers(tmp_path: Path) -> None:
    from sase.plan_gate_decisions import recover_plan_stamp_from_response

    bundle = tmp_path / "bundle"
    (bundle).mkdir()
    (bundle / "response.json").write_text("{}", encoding="utf-8")
    (bundle / "request.json").write_text("{}", encoding="utf-8")
    assert recover_plan_stamp_from_response(bundle) is False
