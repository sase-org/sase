"""Golden tests: rebuild a question gate shell's Q&A chain from durable state.

Each round is a real gate bundle plus a real gate-shell member, answered
through ``execute_gate_selection`` -- with no live process carrying
``LoopState.qa_rounds`` between rounds, this is the simulated runner death
the phase brief requires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.gate_shell.member import create_gate_shell_member
from sase.main.qa_markdown import build_merged_qa_markdown
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate
from sase.question_shell.create import _question_gate_shell_spec
from sase.question_shell.rounds import (
    _question_chain,
    question_base_prompt,
    question_rounds,
)

_BASE_PROMPT_FILENAME = "question_base_prompt.md"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _questions(round_index: int) -> list[dict[str, Any]]:
    return [
        {
            "question": f"Question {round_index}?",
            "options": [{"label": "Yes"}, {"label": "No"}],
        }
    ]


def _answer(round_index: int, *, note: str | None) -> dict[str, Any]:
    return {
        "answers": [
            {
                "question": f"Question {round_index}?",
                "selected": ["Yes"],
                "custom_feedback": None,
            }
        ],
        "global_note": note or "",
    }


def _create_and_answer_round(
    *,
    base_prompt_dir: Path,
    round_index: int,
    parent_artifacts_dir: str | None,
    note: str | None,
    unanswered: bool = False,
) -> str:
    session_id = f"round-{round_index}"
    request = _question_gate_shell_spec(
        _questions(round_index),
        session_id=session_id,
        base_prompt="the base prompt",
        prior_rounds=[],
    )
    request["request_id"] = session_id
    gate = create_gate(request)
    shell = GateShellSpec.from_mapping(request["shell"], branches=(("submit",),))
    suffix = "--gate" if round_index == 1 else f"--gate-{round_index - 2}"
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane"},
        lane="lane",
        suffix=suffix,
        prev_artifacts_timestamp="20260812120000",
        workspace_num=None,
        gate_id=session_id,
        gate_kind="question",
        label="Question",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    fields: dict[str, Any] = {
        "gate_bundle_path": str(gate.bundle_path),
        "question_round_index": round_index,
        "question_session_id": session_id,
    }
    if parent_artifacts_dir is None:
        base_prompt_path = base_prompt_dir / _BASE_PROMPT_FILENAME
        base_prompt_path.write_text("Implement the feature.", encoding="utf-8")
        fields["question_base_prompt_path"] = str(base_prompt_path)
    else:
        fields["question_prev_artifacts_dir"] = parent_artifacts_dir
        fields["question_base_prompt_path"] = str(
            base_prompt_dir / _BASE_PROMPT_FILENAME
        )
    update_meta_fields(artifacts_dir, fields)

    if not unanswered:
        answer = _answer(round_index, note=note)
        execute_gate_selection(
            gate.bundle_path,
            ["submit"],
            answer,
            feedback=answer.get("global_note") or None,
            source="test",
        )
    return artifacts_dir


def test_two_round_chain_rebuilds_oldest_first_with_continuous_numbering(
    tmp_path: Path,
) -> None:
    round1 = _create_and_answer_round(
        base_prompt_dir=tmp_path, round_index=1, parent_artifacts_dir=None, note=None
    )
    round2 = _create_and_answer_round(
        base_prompt_dir=tmp_path,
        round_index=2,
        parent_artifacts_dir=round1,
        note="second note",
    )

    chain = _question_chain(round2)
    assert chain == (round1, round2)

    rounds = question_rounds(round2)
    assert len(rounds) == 2
    assert rounds[0].questions[0]["question"] == "Question 1?"
    assert rounds[1].questions[0]["question"] == "Question 2?"

    merged = build_merged_qa_markdown(rounds)
    assert "#### Q1" in merged
    assert "#### Q2" in merged
    assert merged.index("#### Q1") < merged.index("#### Q2")
    assert "Question 1?" in merged
    assert "Question 2?" in merged
    assert "> **Global Note:** second note" in merged

    assert question_base_prompt(round2) == "Implement the feature."


def test_three_round_chain_last_nonempty_global_note_wins(tmp_path: Path) -> None:
    round1 = _create_and_answer_round(
        base_prompt_dir=tmp_path,
        round_index=1,
        parent_artifacts_dir=None,
        note="first note",
    )
    round2 = _create_and_answer_round(
        base_prompt_dir=tmp_path, round_index=2, parent_artifacts_dir=round1, note=None
    )
    round3 = _create_and_answer_round(
        base_prompt_dir=tmp_path,
        round_index=3,
        parent_artifacts_dir=round2,
        note="third note",
    )

    rounds = question_rounds(round3)
    assert len(rounds) == 3
    merged = build_merged_qa_markdown(rounds)
    assert "#### Q1" in merged and "#### Q2" in merged and "#### Q3" in merged
    assert merged.index("#### Q1") < merged.index("#### Q2") < merged.index("#### Q3")
    assert "> **Global Note:** third note" in merged
    assert "first note" not in merged.split("Global Note:")[-1]


def test_broken_link_stops_the_walk_but_does_not_raise(tmp_path: Path) -> None:
    round1 = _create_and_answer_round(
        base_prompt_dir=tmp_path, round_index=1, parent_artifacts_dir=None, note=None
    )
    round2 = _create_and_answer_round(
        base_prompt_dir=tmp_path, round_index=2, parent_artifacts_dir=round1, note=None
    )
    # Sever the chain link as if round 1's metadata were lost or corrupted.
    update_meta_fields(round2, {}, remove_keys=("question_prev_artifacts_dir",))

    chain = _question_chain(round2)
    assert chain == (round2,)
    rounds = question_rounds(round2)
    assert len(rounds) == 1
    assert rounds[0].questions[0]["question"] == "Question 2?"


def test_unanswered_middle_round_contributes_nothing(tmp_path: Path) -> None:
    round1 = _create_and_answer_round(
        base_prompt_dir=tmp_path, round_index=1, parent_artifacts_dir=None, note=None
    )
    round2 = _create_and_answer_round(
        base_prompt_dir=tmp_path,
        round_index=2,
        parent_artifacts_dir=round1,
        note=None,
        unanswered=True,
    )
    round3 = _create_and_answer_round(
        base_prompt_dir=tmp_path,
        round_index=3,
        parent_artifacts_dir=round2,
        note="final note",
    )

    rounds = question_rounds(round3)
    questions_asked = [r.questions[0]["question"] for r in rounds]
    assert questions_asked == ["Question 1?", "Question 3?"]
    merged = build_merged_qa_markdown(rounds)
    assert "#### Q1" in merged
    assert "#### Q2" in merged
    assert "Question 3?" in merged
