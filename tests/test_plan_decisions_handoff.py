"""Handoff-phase coverage for Plan Decisions (sase-1hi.4)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


STAMPED_TALE = """---
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
    answer: mode
decided_by: reviewer
decided_via: tui
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
"""

AUTO_TALE = """---
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
    answer: pane
decided_by: auto
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
"""

MEMORY_TALE = """---
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
    answer: pane
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "please also update the tui memory note"
    default: true
    answer: false
decided_by: auto
---
# Plan

> [!decision] grouping = pane Order by pane.
Body mentions tui_note.
"""

PENDING_TALE = """---
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

STAMPED_EPIC = """---
tier: epic
title: Keymap help overlay epic
goal: Ship the overlay.
phases:
  - id: build
    title: Build it
    depends_on: []
    size: small
    description: Build the overlay.
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
    answer: mode
decided_by: reviewer
decided_via: telegram
---
# Plan

> [!decision] grouping = mode Order by mode.
"""


@pytest.fixture()
def tale_path(tmp_path: Path) -> Path:
    path = tmp_path / "tale.md"
    path.write_text(STAMPED_TALE, encoding="utf-8")
    return path


def test_reviewer_coder_block_names_branch_and_default(tale_path: Path) -> None:
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    block = coder_decisions_block(tale_path)
    assert "Reviewer decisions for this plan" in block
    assert "grouping = mode" in block
    assert "planner default: pane" in block
    assert "Implement only the branches selected above." in block


def test_auto_coder_block_says_no_human_reviewed(tmp_path: Path) -> None:
    path = tmp_path / "auto.md"
    path.write_text(AUTO_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    block = coder_decisions_block(path)
    assert "no human reviewed" in block


def test_pending_plan_yields_no_coder_block(tmp_path: Path) -> None:
    path = tmp_path / "pending.md"
    path.write_text(PENDING_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    assert coder_decisions_block(path) == ""


def test_declined_memory_routes_by_audience(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    path.write_text(MEMORY_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import coder_decisions_block

    coder_block = coder_decisions_block(path, audience="tale_coder")
    phase_block = coder_decisions_block(path, audience="epic_phase")
    assert "/sase_new_task" in coder_block
    assert "PROPOSED FOLLOW-UP:" not in coder_block
    assert "PROPOSED FOLLOW-UP:" in phase_block
    assert "/sase_new_task" not in phase_block


def test_epic_context_resolves_snapshot_and_inherits(tmp_path: Path) -> None:
    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"epic_plan_snapshot": str(epic_path)}), encoding="utf-8"
    )
    sub_path = tmp_path / "phase_sub.md"
    sub_path.write_text(STAMPED_TALE, encoding="utf-8")
    from sase.sdd.plan_decision_handoff import (
        coder_decisions_block,
        epic_decision_context,
    )

    context = epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"
    block = coder_decisions_block(sub_path, audience="epic_phase", inherited=context)
    assert "Inherited from epic" in block


def test_epic_context_fails_closed(tmp_path: Path) -> None:
    from sase.sdd.plan_decision_handoff import epic_decision_context

    assert epic_decision_context(tmp_path / "missing") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert epic_decision_context(empty) is None
    (empty / "agent_meta.json").write_text("{}", encoding="utf-8")
    assert epic_decision_context(empty) is None


def test_reviewer_block_helper_prefers_archived_copy(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(PENDING_TALE, encoding="utf-8")
    archived = tmp_path / "archived.md"
    archived.write_text(STAMPED_TALE, encoding="utf-8")
    plan_result = SimpleNamespace(
        saved_plan_path=str(archived), plan_file=str(plan_path)
    )
    from sase.axe.run_agent_exec_plan_accept import _reviewer_decisions_block

    block = _reviewer_decisions_block(plan_result, plan_path, tmp_path)
    assert block.startswith("\n\nReviewer decisions for this plan")


def test_reviewer_block_helper_fails_open(tmp_path: Path) -> None:
    plan_result = SimpleNamespace(saved_plan_path=None, plan_file="/nope.md")
    from sase.axe.run_agent_exec_plan_accept import _reviewer_decisions_block

    assert _reviewer_decisions_block(plan_result, "/nope.md", tmp_path) == ""


def test_bead_read_decisions_wire_and_lines(tmp_path: Path) -> None:
    from sase.bead.cli_detail_decisions import (
        decisions_wire_for_detail,
        render_decisions_content_lines,
    )
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    phase = Issue(
        id="sase-1hi.4", title="Handoff", issue_type=IssueType.PHASE, design=""
    )
    detail = SimpleNamespace(
        issue=phase,
        plan=PlanLink(
            section="PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    wire = decisions_wire_for_detail(detail)
    assert wire is not None
    assert wire["decided_by"] == "reviewer"
    assert wire["audience"] == "epic_phase"
    assert wire["sheet"]["changed_count"] == 1
    lines = render_decisions_content_lines(wire)
    assert any("Reviewer decisions" in line for line in lines)
    assert any("grouping = mode" in line for line in lines)


def test_bead_read_epic_lens_and_task_empty(tmp_path: Path) -> None:
    from sase.bead.cli_detail_decisions import decisions_wire_for_detail
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import BeadTier, Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    epic = Issue(
        id="sase-1hi",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="",
    )
    epic_detail = SimpleNamespace(
        issue=epic,
        plan=PlanLink(
            section="EPIC PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    task = Issue(id="sase-1", title="Task", issue_type=IssueType.TASK, design="")
    task_detail = SimpleNamespace(issue=task, plan=None)
    epic_wire = decisions_wire_for_detail(epic_detail)
    assert epic_wire is not None
    assert epic_wire["audience"] == "epic_land"
    assert decisions_wire_for_detail(task_detail) is None


def test_bead_read_json_envelope_carries_decisions(tmp_path: Path) -> None:
    from sase.bead.cli_detail_json import issue_detail_wire_dict
    from sase.bead.cli_detail_resolution import IssueDetail, PlanLink
    from sase.bead.model import Issue, IssueType

    epic_path = tmp_path / "epic.md"
    epic_path.write_text(STAMPED_EPIC, encoding="utf-8")
    issue = Issue(
        id="sase-1hi.4",
        title="Handoff",
        issue_type=IssueType.PHASE,
        design=str(epic_path),
    )
    detail = IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=PlanLink(
            section="PLAN", source="self", path=str(epic_path), from_ref=None
        ),
    )
    envelope = issue_detail_wire_dict(detail)
    decisions = envelope["decisions"]
    assert isinstance(decisions, dict)
    assert decisions["decided_by"] == "reviewer"
    assert decisions["sheet"]["count"] == 1


def test_receipt_only_posts_with_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import RECEIPT_TAG, post_auto_approval_receipt

    notifications_dir = tmp_path / "notifications"
    notifications_file = notifications_dir / "notifications.jsonl"
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_dir)
    )
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)
    )

    assert (
        post_auto_approval_receipt(request_id="r1", plan_label="tale · x", sheet={})
        is False
    )
    assert (
        post_auto_approval_receipt(
            request_id="r1", plan_label="tale · x", sheet={"rows": []}
        )
        is False
    )
    sheet = {
        "count": 2,
        "memory_count": 1,
        "changed_count": 1,
        "review_revision": 0,
        "rows": [
            {
                "id": "grouping",
                "kind": "choice",
                "ask": "How group?",
                "why": "pane keeps order",
                "choices": [
                    {"key": "pane", "label": "By pane"},
                    {"key": "mode", "label": "By mode"},
                ],
                "default": "pane",
                "value": "pane",
                "changed": False,
            },
            {
                "id": "tui_note",
                "kind": "toggle",
                "ask": "Record?",
                "why": None,
                "choices": [],
                "default": True,
                "value": True,
                "changed": False,
                "memory": {
                    "selectors": ["tui.md"],
                    "provenance": "asked",
                    "quote": "and note the convention",
                },
            },
        ],
    }
    assert (
        post_auto_approval_receipt(
            request_id="req-1", plan_label="tale · keymap_help_overlay", sheet=sheet
        )
        is True
    )
    from sase.notifications.store import load_notifications

    rows = load_notifications()
    assert len(rows) == 1
    receipt = rows[0]
    assert RECEIPT_TAG in receipt.tags
    assert receipt.silent is True
    assert receipt.action is None
    assert receipt.dedup_key == "plan-decisions-receipt-req-1"
    assert receipt.notes[0] == "\U0001f916 Auto-approved tale · keymap_help_overlay"
    assert any("grouping = pane \u2605 (auto)" in note for note in receipt.notes)
    assert any("\U0001f9e0 tui.md" in note for note in receipt.notes)


def test_auto_receipt_hook_wires_values_and_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.notification_gates.adapters import _post_plan_auto_receipt_best_effort

    bundle = tmp_path / "req-9"
    bundle.mkdir()
    envelope = {
        "payload": {
            "decisions": [{"id": "grouping"}],
            "original_plan_file": "/plans/keymap_help_overlay.md",
        }
    }
    response = {
        "source": "auto_resolution",
        "option_inputs": {
            "approve": {"decision_grouping": "mode"},
            "commit": {"decision_grouping": "mode"},
        },
    }
    calls: list[dict[str, object]] = []

    def fake_post(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        return True

    monkeypatch.setattr(
        "sase.sdd.plan_decision_handoff.post_auto_approval_receipt", fake_post
    )
    monkeypatch.setattr(
        "sase.sdd.plan_decisions.sheet_binding",
        lambda definitions, values: {"rows": [{"id": "grouping"}]},
    )

    _post_plan_auto_receipt_best_effort(
        "plan", bundle, envelope, response, ("approve", "commit")
    )
    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-9"
    assert calls[0]["plan_label"] == "tale · keymap_help_overlay.md"

    calls.clear()
    manual = dict(response)
    manual["source"] = "plan_response"
    _post_plan_auto_receipt_best_effort(
        "plan", bundle, envelope, manual, ("approve", "commit")
    )
    assert calls == []

    calls.clear()
    nodecisions = {"payload": {}}
    _post_plan_auto_receipt_best_effort(
        "plan", bundle, nodecisions, response, ("approve", "commit")
    )
    assert calls == []


def test_builders_pending_and_accepted(tale_path: Path) -> None:
    from sase.sdd._plan_display_decisions import (
        accepted_decisions_text,
        decision_text_lines,
        format_decision_value,
        pending_decisions_text,
    )
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    stamped = load_stamped_decisions(tale_path)
    assert stamped is not None
    pending = decision_text_lines(pending_decisions_text(stamped.sheet))
    accepted = decision_text_lines(
        accepted_decisions_text(stamped.sheet, stamped.decided_by, stamped.decided_via)
    )
    assert format_decision_value(True) == "yes"
    assert format_decision_value(False) == "no"
    assert format_decision_value("mode") == "mode"
    assert any("\u2605" in line for line in pending)
    assert any("How should the overlay group bindings?" in line for line in pending)
    assert accepted[0] == "decided by reviewer · TUI"
    assert any("\u25c9 grouping = mode\u25cf" in line for line in accepted)


FROZEN_MEMORY_TALE = """---
tier: tale
title: Frozen memory tale
goal: Cover frozen rendering.
size: small
decisions:
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "please also update the tui memory note"
    default: true
    answer: true
decided_by: reviewer
decided_via: tui
---
# Plan

Body mentions tui_note.
"""


def _write_frozen_sibling(plan_path: Path, definitions: list[dict]) -> None:
    import json as _json

    sibling = plan_path.parent / f"{plan_path.stem}.plan-decisions.json"
    sibling.write_text(
        _json.dumps({"schema": 1, "definitions": definitions}, indent=2) + "\n",
        encoding="utf-8",
    )


def _frozen_memory_definitions() -> list[dict]:
    return [
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Record conventions in the tui memory note?",
            "default": True,
            "effective_default": True,
            "memory": {"selectors": ["tui.md"]},
            "provenance": "asked",
            "requested_verified": True,
            "resolved": [
                {
                    "selector": "tui.md",
                    "kind": "note",
                    "scope": "project",
                    "path": "sase/memory/tui.md",
                    "type": "reference",
                    "exists": True,
                }
            ],
            "quote": "please also update the tui memory note",
        }
    ]


def test_accepted_frozen_definitions_ignore_reader_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd._plan_display_decisions import (
        accepted_decisions_text,
        decision_text_lines,
    )
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "frozen.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    _write_frozen_sibling(plan_path, _frozen_memory_definitions())
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list) and len(rows) == 1
    memory = rows[0].get("memory")
    assert isinstance(memory, dict)
    assert memory.get("provenance") == "asked"
    resolved = memory.get("resolved")
    assert isinstance(resolved, list) and resolved
    assert resolved[0].get("path") == "sase/memory/tui.md"
    assert rows[0].get("value") is True
    assert rows[0].get("changed") is False
    lines = decision_text_lines(
        accepted_decisions_text(stamped.sheet, stamped.decided_by, stamped.decided_via)
    )
    from sase.sdd._plan_display_decisions import provenance_chip as _chip

    assert _chip("asked") == "you asked"
    assert any("\u2605" in line for line in lines)


def test_accepted_synthetic_fallback_uses_authored_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "synthetic.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    sibling = plan_path.parent / f"{plan_path.stem}.plan-decisions.json"
    assert not sibling.exists()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0].get("value") is True
    assert rows[0].get("changed") is False
    text = str(stamped.sheet)
    assert "quote_not_found" not in text
    assert "quote not found" not in text.lower()


def test_frozen_resolved_path_survives_tmp_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "kept.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    _write_frozen_sibling(plan_path, _frozen_memory_definitions())
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list)
    memory = rows[0].get("memory")
    assert isinstance(memory, dict)
    resolved = memory.get("resolved")
    assert isinstance(resolved, list)
    assert any(
        isinstance(item, dict) and item.get("path") == "sase/memory/tui.md"
        for item in resolved
    )


def _write_epic_plan(tmp_path: Path, name: str = "epic.md") -> tuple[Path, Path]:
    plans_root = tmp_path / "plans"
    (plans_root / "202610").mkdir(parents=True, exist_ok=True)
    plan_path = plans_root / "202610" / name
    plan_path.write_text(STAMPED_EPIC, encoding="utf-8")
    return plans_root, plan_path


def test_bead_read_plan_ref_resolves_through_roots(tmp_path: Path) -> None:
    from types import SimpleNamespace as _NS

    from sase.bead.cli_detail_decisions import (
        decisions_wire_for_detail,
        render_decisions_content_lines,
    )
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import Issue, IssueType
    from sase.sdd.plan_decisions import prompt_block_binding

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    phase = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=""
    )
    detail = _NS(
        issue=phase,
        plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
    )
    wire = decisions_wire_for_detail(
        detail, plan_roots=(plans_root,), design_cwd=tmp_path
    )
    assert wire is not None
    assert wire["audience"] == "epic_phase"
    assert wire["decided_by"] == "reviewer"
    expected = prompt_block_binding(
        wire["sheet"], wire["decided_by"], wire["decided_via"], "epic_phase"
    )
    assert render_decisions_content_lines(wire) == [
        f"  {line}" for line in expected.splitlines()
    ]


def test_bead_read_epic_audience_differs_from_phase(tmp_path: Path) -> None:
    from types import SimpleNamespace as _NS

    from sase.bead.cli_detail_decisions import decisions_wire_for_detail
    from sase.bead.cli_detail_resolution import PlanLink
    from sase.bead.model import BeadTier, Issue, IssueType
    from sase.sdd.plan_decisions import prompt_block_binding

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    phase = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=""
    )
    epic = Issue(
        id="sase-1hi.10",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="",
    )
    phase_wire = decisions_wire_for_detail(
        _NS(
            issue=phase,
            plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
        ),
        plan_roots=(plans_root,),
        design_cwd=tmp_path,
    )
    epic_wire = decisions_wire_for_detail(
        _NS(
            issue=epic,
            plan=PlanLink(section="EPIC PLAN", source="self", path=ref, from_ref=None),
        ),
        plan_roots=(plans_root,),
        design_cwd=tmp_path,
    )
    assert phase_wire is not None and epic_wire is not None
    from sase.bead.cli_detail_decisions import render_decisions_content_lines as _lines2

    assert phase_wire["audience"] == "epic_phase"
    assert epic_wire["audience"] == "epic_land"
    assert phase_wire["sheet"] == epic_wire["sheet"]
    assert _lines2(phase_wire) == [
        f"  {line}"
        for line in prompt_block_binding(
            phase_wire["sheet"],
            phase_wire["decided_by"],
            phase_wire["decided_via"],
            "epic_phase",
        ).splitlines()
    ]
    assert _lines2(epic_wire) == [
        f"  {line}"
        for line in prompt_block_binding(
            epic_wire["sheet"],
            epic_wire["decided_by"],
            epic_wire["decided_via"],
            "epic_land",
        ).splitlines()
    ]


def test_bead_read_json_envelope_uses_roots_and_empty_roots_absent(
    tmp_path: Path,
) -> None:
    from sase.bead.cli_detail_json import issue_detail_wire_dict
    from sase.bead.cli_detail_resolution import IssueDetail, PlanLink
    from sase.bead.model import Issue, IssueType

    plans_root, _plan_path = _write_epic_plan(tmp_path)
    ref = "plan:202610/epic.md"
    issue = Issue(
        id="sase-1hi.10.2", title="Phase", issue_type=IssueType.PHASE, design=ref
    )
    detail = IssueDetail(
        issue=issue,
        ancestors=(),
        phases=(),
        child_epics=(),
        depends_on=(),
        blocks=(),
        plan=PlanLink(section="PLAN", source="self", path=ref, from_ref=None),
    )
    envelope = issue_detail_wire_dict(
        detail, plan_roots=(plans_root,), design_cwd=tmp_path
    )
    assert isinstance(envelope["decisions"], dict)
    assert envelope["decisions"]["audience"] == "epic_phase"
    empty = issue_detail_wire_dict(detail, plan_roots=(), design_cwd=tmp_path)
    assert empty["decisions"] is None


def test_epic_context_resolves_plan_ref_and_skips_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from sase.bead.cli_detail_context import plan_reference_roots
    from sase.sdd.plan_decision_handoff import epic_decision_context

    monkeypatch.chdir(tmp_path)
    roots = plan_reference_roots()
    assert roots, "expected default plan roots for epic ref test"
    dest = roots[0] / "202610" / "epic.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(STAMPED_EPIC, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"epic_plan_ref": "plan:202610/epic.md"}), encoding="utf-8"
    )
    context = epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"

    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"epic_plan_ref": "plan:202610/missing.md"}),
        encoding="utf-8",
    )
    assert epic_decision_context(artifacts) is None
    assert dest.is_file()


def test_epic_context_phase_bead_parent_design_and_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json
    from types import SimpleNamespace as _NS

    import sase.sdd.plan_decision_handoff as _handoff

    monkeypatch.chdir(tmp_path)
    from sase.bead.cli_detail_context import plan_reference_roots as _roots

    roots = _roots()
    assert roots
    dest = roots[0] / "202610" / "epic.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(STAMPED_EPIC, encoding="utf-8")

    phase_detail = _NS(
        issue=_NS(parent_id="sase-1hi.10"),
        plan=_NS(path="plan:202610/epic.md"),
    )

    def _fake_design(bead_id: str) -> str | None:
        assert bead_id == "sase-1hi.10"
        return "plan:202610/epic.md"

    monkeypatch.setattr(_handoff, "_bead_design_plan", _fake_design)

    import sase.bead.cli_common as _common
    import sase.bead.cli_detail_resolution as _resolution

    class _FakeView:
        def __enter__(self) -> _FakeView:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(_common, "get_read_view", lambda: _FakeView())
    monkeypatch.setattr(
        _resolution, "resolve_issue_detail", lambda view, bead_id, **kw: phase_detail
    )

    artifacts = tmp_path / "phase-artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"phase_bead_id": "sase-1hi.10.2"}), encoding="utf-8"
    )
    context = _handoff.epic_decision_context(artifacts)
    assert context is not None
    assert context.decided_by == "reviewer"

    coder = tmp_path / "coder-artifacts"
    coder.mkdir()
    (coder / "agent_meta.json").write_text(
        _json.dumps({"parent_timestamp": artifacts.name}), encoding="utf-8"
    )
    successor = _handoff.epic_decision_context(coder)
    assert successor is not None
    assert successor.decided_by == "reviewer"

    (artifacts / "agent_meta.json").write_text(
        _json.dumps({"phase_bead_id": "sase-missing"}), encoding="utf-8"
    )

    def _raise_detail(view: object, bead_id: str, **kw: object) -> object:
        raise ValueError("missing bead")

    monkeypatch.setattr(_resolution, "resolve_issue_detail", _raise_detail)
    assert _handoff.epic_decision_context(artifacts) is None
