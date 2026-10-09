"""Gate-phase coverage for Plan Decisions (sase-1hi.3)."""

from __future__ import annotations

import pytest

from sase.sdd.plan_validate import plan_frontmatter_schema, validate_plan


VALID_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
---
# Plan

> [!decision] grouping = pane Order by pane.
"""

MEMORY_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "and note the convention in the tui memory"
    default: true
---
# Plan

Body mentions tui_note.
"""


def test_decision_schema_rows_are_always_present() -> None:
    names = [field.name for field in plan_frontmatter_schema("tale")]
    assert "decisions" in names
    assert "decisions.<id>.ask" in names
    assert "decided_by" in names
    assert "decided_via" in names


def test_decision_free_gate_spec_is_unchanged() -> None:
    from sase.plan_gate import _build_plan_gate_spec
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(
        "---\ntier: tale\ntitle: T\ngoal: G\nsize: small\n---\n# Plan\n\nBody.\n",
        "tale",
        mode="launch",
    )
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        __import__("pathlib").Path("/tmp/plan.md"),
        "sess",
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
    assert "decisions" not in spec["payload"]
    for option in spec["options"]:
        props = option["input_schema"].get("properties", {})
        assert not [name for name in props if name.startswith("decision_")]


def test_gate_build_freezes_decisions_and_notes() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    for name in (
        "plan_decisions_payload",
        "plan_decisions_digest",
        "plan_decisions_resolve",
    ):
        if not hasattr(core, name):
            pytest.skip(f"stale core without {name}")
    from sase.plan_gate import _build_plan_gate_spec

    validation = validate_plan(VALID_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        __import__("pathlib").Path("/tmp/keymap.md"),
        "sess",
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
    assert isinstance(spec["payload"].get("decisions"), list)
    assert spec["presentation"]["notes"][0].startswith("Tale ready for review:")
    assert spec["presentation"]["notes"][1] == "1 decision · 🧠 0"
    by_id = {option["id"]: option for option in spec["options"]}
    assert by_id["approve"]["input_schema"]["properties"]["decision_grouping"] == {
        "enum": ["pane", "mode"]
    }
    assert by_id["commit"]["input_schema"]["properties"]["decision_grouping"] == {
        "enum": ["pane", "mode"]
    }
    assert "decision_grouping" in by_id["feedback"]["input_schema"]["properties"]
    assert "decisions" in by_id["approve"]["result_schema"]["properties"]
    assert "decisions" in by_id["approve"]["result_schema"]["required"]


def test_kind_validation_rejects_decision_drift(tmp_path) -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_decisions_digest"):
        pytest.skip("stale core")
    from sase.notification_gates.kind_validation.plan import _validate_plan_decisions
    from sase.notification_gates.models import GateError
    from sase.plan_gate import _build_plan_gate_spec

    plan_file = tmp_path / "keymap.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    validation = validate_plan(VALID_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        __import__("pathlib").Path(str(plan_file)),
        "sess",
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
    from sase.notification_gates.models import GateSpec

    good = GateSpec.from_mapping(spec)
    _validate_plan_decisions(good, "tale")
    broken = dict(spec)
    broken_options = [dict(option) for option in spec["options"]]
    for option in broken_options:
        if option["id"] == "approve":
            props = dict(option["input_schema"]["properties"])
            props.pop("decision_grouping", None)
            option["input_schema"] = dict(option["input_schema"], properties=props)
    broken["options"] = broken_options
    with pytest.raises(GateError):
        _validate_plan_decisions(GateSpec.from_mapping(broken), "tale")


def test_omitted_and_explicit_defaults_share_identity() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_decisions_resolve"):
        pytest.skip("stale core")
    from sase.notification_gates.journal import value_digest
    from sase.plan_gate_decisions import normalize_plan_option_inputs

    validation = validate_plan(VALID_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    from sase.plan_gate import _build_plan_gate_spec

    spec = _build_plan_gate_spec(
        __import__("pathlib").Path("/tmp/keymap.md"),
        "sess",
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
    envelope = dict(spec)
    omitted = normalize_plan_option_inputs(
        envelope, ["approve", "commit"], {}, source="cli", caller="human"
    )
    explicit = normalize_plan_option_inputs(
        envelope,
        ["approve", "commit"],
        {
            "approve": {"decision_grouping": "pane"},
            "commit": {"decision_grouping": "pane"},
        },
        source="cli",
        caller="human",
    )
    assert omitted is not None and explicit is not None
    assert value_digest(dict(omitted)) == value_digest(dict(explicit))


def test_decision_conflict_rejects_disagreement() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_decisions_resolve"):
        pytest.skip("stale core")
    from sase.notification_gates.models import GateError
    from sase.plan_gate_decisions import normalize_plan_option_inputs

    validation = validate_plan(VALID_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    from sase.plan_gate import _build_plan_gate_spec

    spec = _build_plan_gate_spec(
        __import__("pathlib").Path("/tmp/keymap.md"),
        "sess",
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
            {
                "approve": {"decision_grouping": "pane"},
                "commit": {"decision_grouping": "mode"},
            },
            source="cli",
            caller="human",
        )
    assert excinfo.value.code == "decision_conflict"


def test_agent_cannot_switch_memory_on() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_decisions_resolve"):
        pytest.skip("stale core")
    from sase.sdd.plan_decisions import resolve_binding

    definitions = [
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Edit tui.md?",
            "default": False,
            "effective_default": False,
            "memory": {"selectors": ["tui.md"]},
            "provenance": "not_asked",
            "requested_verified": False,
            "resolved": [],
        }
    ]
    result = resolve_binding(definitions, {"tui_note": True}, "agent")
    assert result.get("errors")


def test_auto_clamps_unverified_memory_default() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_decisions_resolve"):
        pytest.skip("stale core")
    from sase.sdd.plan_decisions import resolve_binding

    verified = [
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Edit tui.md?",
            "default": True,
            "effective_default": True,
            "memory": {"selectors": ["tui.md"]},
            "provenance": "asked",
            "requested_verified": True,
            "resolved": [],
        }
    ]
    result = resolve_binding(verified, {}, "auto")
    assert result.get("values", {}).get("tui_note") is True
    unverified = [
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Edit tui.md?",
            "default": True,
            "effective_default": False,
            "memory": {"selectors": ["tui.md"]},
            "provenance": "quote_not_found",
            "requested_verified": False,
            "resolved": [],
        }
    ]
    clamped = resolve_binding(unverified, {}, "auto")
    assert clamped.get("values", {}).get("tui_note") is False


def test_edit_freeze_blocks_question_edits_allows_prose(tmp_path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.notification_gates.adapters import GateAdapter
    from sase.plan_gate import _build_plan_gate_spec

    plan_file = tmp_path / "plan.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    validation = validate_plan(VALID_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None
    spec = _build_plan_gate_spec(
        plan_file,
        "sess-freeze",
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
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    import json

    (bundle / "request.json").write_text(json.dumps(spec), encoding="utf-8")
    bundle_plan = bundle / "plan.md"
    bundle_plan.write_text(VALID_TALE, encoding="utf-8")
    adapter = GateAdapter(
        kind="plan",
        display_title="Plan",
        action="PlanApproval",
        pending_action_kind="plan",
        sender="sase",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="response_dir",
        auto_capabilities={"approve_archive"},
    )
    # Prose-only edit succeeds.
    prose = VALID_TALE.replace("# Plan", "# Plan\n\nExtra prose line.")
    bundle_plan.write_text(prose, encoding="utf-8")
    adapter.validate_edited_resource(path=bundle_plan)
    # Question edit fails with the freeze message.
    from sase.notification_gates.models import GateError

    changed = VALID_TALE.replace(
        "By pane, matching the footer hints", "By pane, changed"
    )
    bundle_plan.write_text(changed, encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        adapter.validate_edited_resource(path=bundle_plan)
    assert "Decisions are fixed for this review" in str(excinfo.value)
    # System-answer edit fails as well.
    answered = VALID_TALE.replace("default: pane", "default: pane\n    answer: pane")
    bundle_plan.write_text(answered, encoding="utf-8")
    with pytest.raises(GateError):
        adapter.validate_edited_resource(path=bundle_plan)


def test_feedback_prompt_only_changed_values() -> None:
    from sase.main.feedback_prompt import assemble_feedback_replan_prompt

    rows = [
        {
            "id": "grouping",
            "value": "mode",
            "default": "pane",
            "memory": False,
            "changed": True,
        },
        {
            "id": "other",
            "value": "pane",
            "default": "pane",
            "memory": False,
            "changed": False,
        },
    ]
    prompt = assemble_feedback_replan_prompt("Base", ["Fix it"], None, rows)
    assert "### Reviewer's provisional decisions" in prompt
    assert "- grouping = mode (was pane)" in prompt
    assert "other" not in prompt.split("### Reviewer's provisional decisions")[1]
    memory_rows = [
        {
            "id": "tui_note",
            "value": True,
            "default": False,
            "memory": True,
            "changed": True,
        }
    ]
    memory_prompt = assemble_feedback_replan_prompt(
        "Base", ["Fix it"], None, memory_rows
    )
    assert "not authorization" in memory_prompt


def test_committed_archived_accepts_stamp() -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    if not hasattr(core, "plan_validate"):
        pytest.skip("stale core")
    try:
        validation = validate_plan(VALID_TALE, "tale", mode="archived")
    except Exception:
        pytest.skip("core without archived mode")
    assert validation.ok
    from sase.sdd.committed_plan_validation import inspect_committed_plan

    issues = inspect_committed_plan(
        VALID_TALE, tier="tale", path="plan.md", yyyymm="202610"
    )
    assert not [issue for issue in issues if issue.is_error]
