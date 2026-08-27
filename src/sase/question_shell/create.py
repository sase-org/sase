"""Build and create the question gate shell for one Q&A round."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.gate_shell import GateShellCreation, create_gate_shell, list_gate_shells
from sase.main.qa_markdown import QARound, build_merged_qa_markdown
from sase.user_question_actions import user_question_gate_spec

_QUESTION_BASE_PROMPT_FILENAME = "question_base_prompt.md"


def _question_gate_shell_spec(
    questions: list[dict[str, Any]],
    *,
    session_id: str,
    producer: Mapping[str, Any] | None = None,
    action_data: Mapping[str, str] | None = None,
    auto: bool = False,
    base_prompt: str,
    prior_rounds: list[QARound],
) -> dict[str, Any]:
    """Build the question gate's v3 request body plus its additive shell block.

    The ``submit`` branch prompt is declared here from ``prior_rounds`` alone,
    since this round cannot include itself yet -- correct except that it is
    short exactly one round. At settlement, :func:`question_next_action`
    rebuilds it across every round including this one; the declared text is
    only the fallback when that rebuild cannot run.
    """
    request = user_question_gate_spec(
        questions,
        session_id=session_id,
        producer=producer,
        action_data=action_data,
        auto=auto,
    )
    declared_prompt = base_prompt + "\n\n" + build_merged_qa_markdown(prior_rounds)
    request["shell"] = {
        "pending_status": "QUESTION",
        "settled_status": "ANSWERED",
        "accent": "#FFAF00",
        "workspace": "inherit",
        "next": {"fork": "family", "output": ["results"], "prompt": None},
        "branches": {
            "submit": {
                "status": "ANSWERED",
                "accent": "#5FD7FF",
                "prompt": declared_prompt,
                "output": ["results"],
                "fork": "family",
            },
            "timeout": {
                "status": "QUESTION TIMED OUT",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "stopped": {
                "status": "QUESTION CANCELLED",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "failed": {
                "status": "QUESTION FAILED",
                "accent": "#FF5F5F",
                "prompt": None,
            },
        },
    }
    return request


def create_question_gate_shell(
    questions: list[dict[str, Any]],
    *,
    session_id: str,
    producer: Mapping[str, Any] | None = None,
    action_data: Mapping[str, str] | None = None,
    auto: bool = False,
    base_prompt: str,
    prior_rounds: list[QARound],
    parent_artifacts_dir: str | None,
    sdd_spec_path: str | None,
) -> GateShellCreation:
    """Create this round's question gate shell and record its chain metadata.

    The chain link is Python-side member metadata only -- no wire schema
    change. Round 1 writes ``base_prompt`` to its own artifacts dir; every
    later round inherits that same path verbatim.
    """
    spec = _question_gate_shell_spec(
        questions,
        session_id=session_id,
        producer=producer,
        action_data=action_data,
        auto=auto,
        base_prompt=base_prompt,
        prior_rounds=prior_rounds,
    )
    creation = create_gate_shell(spec)
    artifacts_dir = creation.record.artifacts_dir

    fields: dict[str, Any] = {
        "question_round_index": len(prior_rounds) + 1,
        "question_session_id": session_id,
    }
    if sdd_spec_path:
        fields["question_sdd_spec_path"] = sdd_spec_path

    if parent_artifacts_dir is None:
        base_prompt_path = str(Path(artifacts_dir) / _QUESTION_BASE_PROMPT_FILENAME)
        Path(base_prompt_path).write_text(base_prompt, encoding="utf-8")
        fields["question_base_prompt_path"] = base_prompt_path
    else:
        fields["question_prev_artifacts_dir"] = parent_artifacts_dir
        parent_base_prompt_path = _read_meta(parent_artifacts_dir).get(
            "question_base_prompt_path"
        )
        if isinstance(parent_base_prompt_path, str) and parent_base_prompt_path:
            fields["question_base_prompt_path"] = parent_base_prompt_path

    update_meta_fields(artifacts_dir, fields)
    return creation


def resolve_question_chain_parent(
    project_name: str,
    lane: str,
    creator_agent: str,
    *,
    hint: str | None,
) -> str | None:
    """Return the previous round's question gate-shell artifacts dir, if any.

    Tried in order: the in-process *hint* (covers the ``%auto`` case, where
    settlement never sets ``gate_followup_agent`` because it runs under
    ``creator_live=True``), then the newest terminal question gate shell in
    *lane* whose recorded follow-up agent is *creator_agent* -- the durable
    cross-process link -- else ``None`` for a fresh chain.
    """
    if hint:
        hint_meta = _read_meta(hint)
        if (
            hint_meta.get("gate_kind") == "question"
            and hint_meta.get("agent_family") == lane
        ):
            return hint

    candidates = sorted(
        (
            record
            for record in list_gate_shells(project=project_name)
            if record.lane == lane
            and record.kind == "question"
            and record.is_terminal
            and record.followup_agent == creator_agent
        ),
        key=lambda record: record.timestamp,
        reverse=True,
    )
    return candidates[0].artifacts_dir if candidates else None


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "create_question_gate_shell",
    "resolve_question_chain_parent",
]
