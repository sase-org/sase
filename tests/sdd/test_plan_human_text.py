"""Human-authorship provenance gatherer tests.

Fixture artifact trees cover typed roots, generated roots, feedback
replans with human and auto responses, Q&A with human free text versus
selected labels, and legacy metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.sdd.plan_human_text import human_authored_texts
from tests.plan_validation_helpers import VALID_TALE_PLAN


def _write_meta(artifacts: Path, meta: dict[str, Any]) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_plan_bundle(
    root: Path,
    name: str,
    *,
    feedback: str | None,
    caller: str | None = None,
    source: str | None = None,
    action: str = "feedback",
) -> Path:
    bundle = root / f"{name}-bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    plan = root / f"{name}.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "plan",
                "payload": {
                    "original_plan_file": str(plan),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
    )
    option_id = "feedback" if action == "feedback" else "approve"
    response: dict[str, Any] = {
        "selected_option_ids": [option_id],
        "feedback": feedback,
        "option_results": [
            {"id": option_id, "result": {"action": "reject", "feedback": feedback}}
        ],
    }
    if caller is not None:
        response["caller"] = caller
    if source is not None:
        response["source"] = source
    (bundle / "response.json").write_text(json.dumps(response), encoding="utf-8")
    return bundle


def _write_question_bundle(
    root: Path,
    name: str,
    *,
    answers: list[dict[str, Any]],
    feedback: str | None = None,
    caller: str | None = "human",
    source: str | None = "tui",
) -> Path:
    bundle = root / f"{name}-qbundle"
    bundle.mkdir(parents=True, exist_ok=True)
    response: dict[str, Any] = {
        "selected_option_ids": ["submit"],
        "feedback": feedback,
        "option_results": [
            {"id": "submit", "result": {"answers": answers}},
        ],
    }
    if caller is not None:
        response["caller"] = caller
    if source is not None:
        response["source"] = source
    (bundle / "response.json").write_text(json.dumps(response), encoding="utf-8")
    (bundle / "request.json").write_text(
        json.dumps({"kind": "question", "payload": {"questions": []}}),
        encoding="utf-8",
    )
    return bundle


def _write_planner(
    root: Path,
    name: str,
    *,
    prompt_origin: str | None = "typed",
    submitted_prompt: str | None = "please edit tui.md",
    prev: Path | None = None,
    bundle: Path | None = None,
    question_bundle: Path | None = None,
    parent_timestamp: str | None = None,
) -> Path:
    artifacts = root / f"{name}-artifacts"
    meta: dict[str, Any] = {}
    if prompt_origin is not None:
        meta["prompt_origin"] = prompt_origin
    if prev is not None:
        meta["plan_gate_turn_prev_artifacts_dir"] = str(prev)
    if bundle is not None:
        meta["gate_bundle_path"] = str(bundle)
    if question_bundle is not None:
        meta["question_response_path"] = str(question_bundle / "response.json")
    if parent_timestamp is not None:
        meta["parent_timestamp"] = parent_timestamp
    _write_meta(artifacts, meta)
    if submitted_prompt is not None:
        (artifacts / "submitted_prompt.md").write_text(
            submitted_prompt, encoding="utf-8"
        )
    return artifacts


def _sources(artifacts: Path) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in human_authored_texts(str(artifacts)):
        grouped.setdefault(item.source, []).append(item.text)
    return grouped


def test_typed_root_prompt_counts(tmp_path: Path) -> None:
    head = _write_planner(tmp_path, "plan", submitted_prompt="please edit tui.md")
    assert _sources(head) == {"root_prompt": ["please edit tui.md"]}


def test_generated_root_prompt_yields_nothing(tmp_path: Path) -> None:
    head = _write_planner(
        tmp_path, "plan", prompt_origin="generated", submitted_prompt="do the thing"
    )
    assert human_authored_texts(str(head)) == ()


def test_unknown_root_prompt_yields_nothing(tmp_path: Path) -> None:
    head = _write_planner(
        tmp_path, "plan", prompt_origin="unknown", submitted_prompt="do the thing"
    )
    assert human_authored_texts(str(head)) == ()


def test_legacy_run_without_provenance_yields_nothing(tmp_path: Path) -> None:
    head = _write_planner(
        tmp_path, "plan", prompt_origin=None, submitted_prompt="do the thing"
    )
    bundle = _write_plan_bundle(
        tmp_path, "legacy", feedback="fix it", caller=None, source=None
    )
    _write_meta(
        head,
        {
            "gate_bundle_path": str(bundle),
            "plan_gate_turn_prev_artifacts_dir": str(head),
        },
    )
    assert human_authored_texts(str(head)) == ()


def test_missing_artifacts_dir_yields_nothing(tmp_path: Path) -> None:
    assert human_authored_texts(str(tmp_path / "nope")) == ()


def test_feedback_replan_chain_with_human_response(tmp_path: Path) -> None:
    first = _write_planner(tmp_path, "first", submitted_prompt="please edit tui.md")
    bundle = _write_plan_bundle(
        tmp_path, "round1", feedback="use tabs", caller="human", source="tui"
    )
    head = _write_planner(
        tmp_path,
        "second",
        prompt_origin="generated",
        submitted_prompt="revised agent-written prompt",
        prev=first,
        bundle=bundle,
    )
    grouped = _sources(head)
    assert grouped["root_prompt"] == ["please edit tui.md"]
    assert grouped["plan_feedback"] == ["use tabs"]


def test_feedback_from_agent_caller_yields_no_feedback(tmp_path: Path) -> None:
    first = _write_planner(tmp_path, "first", submitted_prompt="please edit tui.md")
    bundle = _write_plan_bundle(
        tmp_path, "round1", feedback="agent note", caller="agent", source="cli"
    )
    head = _write_planner(
        tmp_path,
        "second",
        prompt_origin="generated",
        submitted_prompt="revised agent-written prompt",
        prev=first,
        bundle=bundle,
    )
    grouped = _sources(head)
    assert grouped["root_prompt"] == ["please edit tui.md"]
    assert "plan_feedback" not in grouped


def test_feedback_from_auto_resolution_yields_no_feedback(tmp_path: Path) -> None:
    first = _write_planner(tmp_path, "first", submitted_prompt="please edit tui.md")
    bundle = _write_plan_bundle(
        tmp_path,
        "round1",
        feedback="auto note",
        caller="human",
        source="auto_resolution",
    )
    head = _write_planner(
        tmp_path,
        "second",
        prompt_origin="generated",
        submitted_prompt="revised agent-written prompt",
        prev=first,
        bundle=bundle,
    )
    assert "plan_feedback" not in _sources(head)


def test_session_parent_fallback_finds_typed_root(tmp_path: Path) -> None:
    # A feedback-replan planner with no prev pointer still resolves its
    # root through the session parent link.
    root = _write_planner(tmp_path, "root", submitted_prompt="please edit tui.md")
    head = _write_planner(
        tmp_path,
        "replan",
        prompt_origin="generated",
        submitted_prompt="agent-written replan",
        parent_timestamp=root.name,
    )
    assert _sources(head)["root_prompt"] == ["please edit tui.md"]


def test_question_free_text_counts_but_selected_labels_do_not(
    tmp_path: Path,
) -> None:
    qbundle = _write_question_bundle(
        tmp_path,
        "q1",
        answers=[
            {"selected": ["pane"], "custom_feedback": "use the footer order please"},
            {"selected": ["mode"], "custom_feedback": ""},
        ],
        feedback="overall note from human",
        caller="human",
        source="tui",
    )
    head = _write_planner(
        tmp_path, "plan", submitted_prompt=None, question_bundle=qbundle
    )
    grouped = _sources(head)
    assert "root_prompt" not in grouped
    assert grouped["question_answer"] == ["use the footer order please"]
    assert grouped["question_note"] == ["overall note from human"]
    for texts in grouped.values():
        for text in texts:
            assert "pane" not in text or "footer" in text


def test_question_response_from_agent_caller_yields_nothing(
    tmp_path: Path,
) -> None:
    qbundle = _write_question_bundle(
        tmp_path,
        "q1",
        answers=[{"selected": ["pane"], "custom_feedback": "agent words"}],
        caller="agent",
        source="cli",
    )
    head = _write_planner(
        tmp_path, "plan", submitted_prompt=None, question_bundle=qbundle
    )
    assert human_authored_texts(str(head)) == ()


def test_question_response_from_auto_resolution_yields_nothing(
    tmp_path: Path,
) -> None:
    qbundle = _write_question_bundle(
        tmp_path,
        "q1",
        answers=[{"selected": ["pane"], "custom_feedback": "auto words"}],
        caller="human",
        source="auto_resolution",
    )
    head = _write_planner(
        tmp_path, "plan", submitted_prompt=None, question_bundle=qbundle
    )
    assert human_authored_texts(str(head)) == ()


def test_approve_action_response_contributes_no_feedback(tmp_path: Path) -> None:
    head = _write_planner(tmp_path, "plan", submitted_prompt="please edit tui.md")
    bundle = _write_plan_bundle(
        tmp_path,
        "approved",
        feedback=None,
        caller="human",
        source="tui",
        action="approve",
    )
    _write_meta(
        head,
        {"prompt_origin": "typed", "gate_bundle_path": str(bundle)},
    )
    grouped = _sources(head)
    assert grouped["root_prompt"] == ["please edit tui.md"]
    assert "plan_feedback" not in grouped


def test_three_round_question_chain_returns_first_round_quote_only(
    tmp_path: Path,
) -> None:
    round1 = _write_question_bundle(
        tmp_path,
        "r1",
        answers=[{"selected": ["pane"], "custom_feedback": "quote the footer order"}],
        feedback=None,
        caller="human",
        source="tui",
    )
    round2 = _write_question_bundle(
        tmp_path,
        "r2",
        answers=[{"selected": ["mode"], "custom_feedback": ""}],
        feedback=None,
        caller="human",
        source="tui",
    )
    round3 = _write_question_bundle(
        tmp_path,
        "r3",
        answers=[{"selected": ["pane"], "custom_feedback": "   "}],
        feedback=None,
        caller="human",
        source="tui",
    )
    member1 = tmp_path / "qmember1"
    member2 = tmp_path / "qmember2"
    member3 = tmp_path / "qmember3"
    _write_meta(member1, {"gate_bundle_path": str(round1)})
    _write_meta(
        member2,
        {
            "gate_bundle_path": str(round2),
            "question_prev_artifacts_dir": str(member1),
        },
    )
    _write_meta(
        member3,
        {
            "gate_bundle_path": str(round3),
            "question_prev_artifacts_dir": str(member2),
        },
    )
    head = _write_planner(tmp_path, "plan", submitted_prompt=None)
    _write_meta(
        head,
        {"question_gate_artifacts_dir": str(member3)},
    )
    texts = list(human_authored_texts(str(head)))
    assert [item.text for item in texts] == ["quote the footer order"]
    assert all("mode" not in item.text for item in texts)
