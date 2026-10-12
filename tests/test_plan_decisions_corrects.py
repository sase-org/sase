"""Host verification for memory-decision ``corrects:`` defaults."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.sdd._plan_decisions_shared import (
    CORRECTS_UNVERIFIED_CODE,
    UNVERIFIED_CODE,
)
from sase.sdd.plan_decisions import (
    build_definitions,
    digest_binding,
    prompt_block_binding,
    resolve_binding,
    sheet_binding,
    validate_host_checks,
)
from sase.sdd.plan_decisions_host import _build_host_facts
from sase.sdd.plan_validate import validate_plan

CLAIM = "sase plan approve writes the durable plan"
CLOSEST = "sase plan propose writes the durable plan"


def _needs_core(*names: str) -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    for name in names:
        if not hasattr(core, name):
            pytest.skip(f"stale core without {name}")


def _note(body: str, *, description: str = "Overlay conventions.") -> str:
    return (
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        f"description: {description}\n"
        "---\n"
        f"{body}\n"
    )


def _write_note(
    root: Path,
    stem: str,
    body: str,
    *,
    description: str = "Overlay conventions.",
) -> None:
    path = root / "sase" / "memory" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_note(body, description=description), encoding="utf-8")


def _overlay_tale(
    *,
    corrects: str | None = CLAIM,
    requested: str | None = None,
    memory: str = "[overlay.md]",
    default: str = "true",
    decision_id: str = "overlay_note",
    extra_decisions: str = "",
) -> str:
    quotes = ""
    if requested is not None:
        quotes += f'    requested: "{requested}"\n'
    if corrects is not None:
        quotes += f'    corrects: "{corrects}"\n'
    return (
        "---\n"
        "tier: tale\n"
        "title: Overlay conventions\n"
        "goal: Pressing ? shows bindings.\n"
        "size: small\n"
        "decisions:\n"
        f"  {decision_id}:\n"
        "    ask: Correct the overlay memory note?\n"
        f"    memory: {memory}\n"
        f"{quotes}"
        f"    default: {default}\n"
        f"{extra_decisions}"
        "---\n"
        "# Plan\n"
        "\n"
        f"Body mentions {decision_id}.\n"
    )


def test_corrects_quote_found_keeps_true_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    monkeypatch.chdir(tmp_path)
    _write_note(tmp_path, "overlay", CLAIM)
    validation = validate_plan(_overlay_tale(), "tale")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    facts = _build_host_facts(validation, str(tmp_path))
    assert facts["overlay_note"]["provenance"] == "correction"
    assert facts["overlay_note"]["requested_verified"] is True
    definitions = build_definitions(validation, str(tmp_path))
    assert definitions[0]["effective_default"] is True
    assert definitions[0]["provenance"] == "correction"
    assert definitions[0]["corrects"] == CLAIM
    resolved = resolve_binding(definitions, {}, "auto")
    assert resolved["values"]["overlay_note"] is True
    sheet = sheet_binding(definitions, resolved["values"], 0)
    block = prompt_block_binding(sheet, "auto", None, "tale_coder")
    assert "/sase_new_task" not in block
    assert "PROPOSED FOLLOW-UP:" not in block


def test_corrects_quote_missing_clamps_and_strict_quotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decision_quote_match", "plan_decisions_payload")
    monkeypatch.chdir(tmp_path)
    _write_note(tmp_path, "overlay", CLOSEST)
    content = _overlay_tale()
    validation = validate_plan(content, "tale")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    facts = _build_host_facts(validation, str(tmp_path))
    assert facts["overlay_note"]["provenance"] == "claim_not_found"
    assert facts["overlay_note"]["requested_verified"] is False
    definitions = build_definitions(validation, str(tmp_path))
    assert definitions[0]["default"] is True
    assert definitions[0]["effective_default"] is False
    extra = validate_host_checks(content, validation, str(tmp_path), strict_quotes=True)
    assert extra
    diagnostic = extra[0]
    assert diagnostic.code == CORRECTS_UNVERIFIED_CODE
    assert diagnostic.field_path == "decisions.overlay_note.corrects"
    assert "overlay.md" in diagnostic.message
    assert "closest:" in diagnostic.message
    assert CLOSEST in diagnostic.message
    resolved = resolve_binding(definitions, {}, "auto")
    assert resolved["values"]["overlay_note"] is False
    sheet = sheet_binding(definitions, resolved["values"], 0)
    block = prompt_block_binding(sheet, "auto", None, "tale_coder")
    assert "/sase_new_task" in block


def test_future_grant_missing_note_is_claim_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decisions_payload")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase" / "memory").mkdir(parents=True, exist_ok=True)
    validation = validate_plan(_overlay_tale(), "tale")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    facts = _build_host_facts(validation, str(tmp_path))
    assert facts["overlay_note"]["provenance"] == "claim_not_found"
    assert facts["overlay_note"]["requested_verified"] is False
    resolved = facts["overlay_note"]["resolved"]
    assert resolved and resolved[0]["exists"] is False


def test_corrects_with_requested_is_rejected() -> None:
    _needs_core()
    result = validate_plan(
        _overlay_tale(requested="please update the overlay note", corrects=CLAIM),
        "tale",
    )
    assert not result.ok
    diagnostic = next(
        item
        for item in result.diagnostics
        if item.code == "decision-corrects-with-requested"
    )
    assert diagnostic.field_path == "decisions.overlay_note.corrects"


def test_corrects_on_non_memory_is_rejected() -> None:
    _needs_core()
    content = (
        "---\n"
        "tier: tale\n"
        "title: Overlay conventions\n"
        "goal: Pressing ? shows bindings.\n"
        "size: small\n"
        "decisions:\n"
        "  notify:\n"
        "    ask: Send a notification?\n"
        "    default: false\n"
        f'    corrects: "{CLAIM}"\n'
        "---\n"
        "# Plan\n"
        "\n"
        "Body mentions notify.\n"
    )
    result = validate_plan(content, "tale")
    assert not result.ok
    assert any(
        item.code == "decision-corrects-not-memory" for item in result.diagnostics
    )


def test_requested_unverified_keeps_old_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decision_quote_match")
    monkeypatch.chdir(tmp_path)
    _write_note(tmp_path, "overlay", CLAIM)
    content = _overlay_tale(
        corrects=None,
        requested="please update the overlay conventions in the memory note",
    )
    validation = validate_plan(content, "tale")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    monkeypatch.setattr(
        "sase.sdd.plan_human_text.human_authored_texts",
        lambda _directory: (
            SimpleNamespace(
                source="prompt",
                ref="root",
                text="please update the overlay tomorrow after lunch",
            ),
        ),
    )
    extra = validate_host_checks(content, validation, str(tmp_path), strict_quotes=True)
    assert extra
    diagnostic = extra[0]
    assert diagnostic.code == UNVERIFIED_CODE
    assert diagnostic.code != CORRECTS_UNVERIFIED_CODE
    assert diagnostic.field_path == "decisions.overlay_note.requested"
    assert "closest:" in diagnostic.message


def test_kind_validation_accepts_correction_and_claim_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decisions_digest", "plan_decisions_payload")
    monkeypatch.chdir(tmp_path)
    _write_note(tmp_path, "overlay", CLAIM)
    _write_note(
        tmp_path,
        "extra",
        "Keymap overlay grouping stays pane-first.",
        description="Extra conventions.",
    )
    extra = (
        "  extra_note:\n"
        "    ask: Correct the extra memory note?\n"
        "    memory: [extra.md]\n"
        f'    corrects: "{CLAIM}"\n'
        "    default: true\n"
    )
    content = _overlay_tale(extra_decisions=extra)
    content = content.replace(
        "Body mentions overlay_note.",
        "Body mentions overlay_note extra_note.",
    )
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(content, encoding="utf-8")
    validation = validate_plan(content, "tale", mode="launch")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    from sase.notification_gates.kind_validation.plan import _validate_plan_decisions
    from sase.notification_gates.models import GateSpec
    from sase.plan_gate import _build_plan_gate_spec

    spec = _build_plan_gate_spec(
        plan_file,
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
    by_id = {item["id"]: item for item in spec["payload"]["decisions"]}
    assert by_id["overlay_note"]["provenance"] == "correction"
    assert by_id["extra_note"]["provenance"] == "claim_not_found"
    _validate_plan_decisions(GateSpec.from_mapping(spec), "tale")


def test_digest_unchanged_when_corrects_is_none() -> None:
    _needs_core("plan_decisions_digest")
    from tests._plan_decide_cli_shared import PENDING_TALE

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok, [str(item) for item in validation.diagnostics]
    definitions = build_definitions(validation, "")
    omitted = digest_binding(definitions)
    with_none = [{**item, "corrects": None} for item in definitions]
    assert digest_binding(with_none) == omitted


def test_explain_guidance_names_corrects() -> None:
    from sase.main.plan_explain import PLAN_DECISIONS_GUIDANCE

    assert "`corrects:`" in PLAN_DECISIONS_GUIDANCE
    assert "never carry both" in PLAN_DECISIONS_GUIDANCE
    assert "Do not restate the choice key" in " ".join(PLAN_DECISIONS_GUIDANCE.split())


def test_pending_chips_for_correction_and_claim_not_found() -> None:
    from sase.sdd._plan_display_decisions import (
        pending_decisions_text,
        provenance_chip,
    )

    assert provenance_chip("correction") == "corrects note"
    assert provenance_chip("claim_not_found") == "\u26a0 claim not found \u00b7 off"
    sheet = {
        "rows": [
            {
                "id": "overlay_note",
                "kind": "toggle",
                "ask": "Correct?",
                "default": True,
                "memory": {
                    "selectors": ["overlay.md"],
                    "provenance": "correction",
                    "quote": CLAIM,
                },
            },
            {
                "id": "extra_note",
                "kind": "toggle",
                "ask": "Correct extra?",
                "default": False,
                "memory": {
                    "selectors": ["extra.md"],
                    "provenance": "claim_not_found",
                    "quote": CLAIM,
                },
            },
        ]
    }
    text = pending_decisions_text(sheet).plain
    assert "corrects note" in text
    assert "claim not found" in text
    assert text.count("you asked") == 0


def test_tui_correction_and_claim_not_found_copy() -> None:
    from sase.ace.tui.modals.plan_decision_cards import (
        expanded_card,
        _is_unverified_row as _is_unverified_row,
        render_lines,
        _unverified_warning_line as _unverified_warning_line,
    )

    correction = {
        "id": "overlay_note",
        "kind": "toggle",
        "value": True,
        "default": True,
        "changed": False,
        "ask": "Correct the overlay memory note?",
        "memory": {
            "selectors": ["overlay.md"],
            "provenance": "correction",
            "quote": CLAIM,
        },
    }
    expanded_lines = render_lines(expanded_card(correction, None, 76).renderable, 76)
    expanded = "\n".join(expanded_lines)
    assert "corrects a statement this plan makes false" in expanded
    # Long quotes fold across lines; compare spaceless on both sides.
    expanded_flat = "".join(
        "".join(line.replace("▌", "").split()) for line in expanded_lines
    )
    assert "".join(CLAIM.split()) in expanded_flat
    assert "you asked:" not in expanded
    assert not _is_unverified_row(correction)

    missing = {
        "id": "overlay_note",
        "kind": "toggle",
        "value": False,
        "default": True,
        "changed": False,
        "ask": "Correct the overlay memory note?",
        "memory": {
            "selectors": ["overlay.md"],
            "provenance": "claim_not_found",
            "quote": CLAIM,
        },
    }
    assert _is_unverified_row(missing)
    warning = _unverified_warning_line(missing["memory"])
    assert "not in the note" in warning
    assert "not in your messages" not in warning
    assert _unverified_warning_line(
        {"provenance": "quote_not_found", "quote": CLAIM}
    ).startswith("⚠")
    assert "not in your messages" in _unverified_warning_line(
        {"provenance": "quote_not_found", "quote": CLAIM}
    )


def test_receipt_correction_on_and_claim_not_found_follow_up() -> None:
    from sase.sdd.plan_decision_handoff import _receipt_notes

    sheet = {
        "rows": [
            {
                "id": "overlay_note",
                "kind": "toggle",
                "value": True,
                "changed": False,
                "memory": {
                    "selectors": ["overlay.md"],
                    "provenance": "correction",
                    "quote": CLAIM,
                },
            },
            {
                "id": "extra_note",
                "kind": "toggle",
                "value": False,
                "changed": False,
                "memory": {
                    "selectors": ["extra.md"],
                    "provenance": "claim_not_found",
                    "quote": CLAIM,
                },
            },
        ]
    }
    notes = _receipt_notes("tale · overlay", sheet)
    assert any(f"corrects: {CLAIM!r}" in note for note in notes)
    assert any(
        "claim not found" in note
        and "left off because no human reviewed this plan" in note
        for note in notes
    )
