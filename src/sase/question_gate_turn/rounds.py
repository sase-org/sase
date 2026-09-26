"""Rebuild a question gate shell's Q&A round chain from durable metadata.

Each round's own gate-shell bundle already holds that round's questions
(``request.json`` -> ``payload.questions``) and its answer
(``response.json`` -> ``option_results[submit].result`` plus ``feedback``).
This module adds a durable chain link between consecutive rounds
(``question_prev_artifacts_dir``, written at creation) and walks it to
rebuild the merged Q&A -- no new store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.main.qa_markdown import QARound
from sase.main.qa_prompt import build_qa_round
from sase.user_question_actions import QUESTION_OPTION_ID

_MAX_CHAIN_LINKS = 200


def _question_chain(head_artifacts_dir: str) -> tuple[str, ...]:
    """Return this chain's artifacts dirs, oldest first, walking back from the head."""
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = head_artifacts_dir
    while current is not None and current not in seen and len(chain) < _MAX_CHAIN_LINKS:
        chain.append(current)
        seen.add(current)
        prev = _read_meta(current).get("question_prev_artifacts_dir")
        current = prev if isinstance(prev, str) and prev else None
    chain.reverse()
    return tuple(chain)


def question_rounds(
    head_artifacts_dir: str,
    *,
    head_response: dict[str, Any] | None = None,
) -> list[QARound]:
    """Rebuild every round in this chain, oldest first.

    A round whose bundle is unreadable or whose gate never produced a
    ``submit`` result (a timed-out or cancelled round) contributes nothing,
    rather than failing the whole rebuild.
    """
    chain = _question_chain(head_artifacts_dir)
    rounds: list[QARound] = []
    for artifacts_dir in chain:
        is_head = artifacts_dir == chain[-1]
        round_ = _round_from_bundle(
            artifacts_dir, response=head_response if is_head else None
        )
        if round_ is not None:
            rounds.append(round_)
    return rounds


def question_base_prompt(head_artifacts_dir: str) -> str:
    """Return the chain's round-1 base prompt, or "" when unavailable."""
    chain = _question_chain(head_artifacts_dir)
    root = chain[0] if chain else head_artifacts_dir
    path = _read_meta(root).get("question_base_prompt_path")
    if not isinstance(path, str) or not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _round_from_bundle(
    artifacts_dir: str, *, response: dict[str, Any] | None
) -> QARound | None:
    meta = _read_meta(artifacts_dir)
    bundle_path = meta.get("gate_bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        return None
    request = _read_json_object(os.path.join(bundle_path, "request.json"))
    if request is None:
        return None
    payload = request.get("payload")
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list):
        return None
    if response is None:
        response = _read_json_object(os.path.join(bundle_path, "response.json"))
    if response is None:
        return None
    option_results = response.get("option_results")
    result = (
        next(
            (
                entry.get("result")
                for entry in option_results
                if isinstance(entry, dict) and entry.get("id") == QUESTION_OPTION_ID
            ),
            None,
        )
        if isinstance(option_results, list)
        else None
    )
    if not isinstance(result, dict):
        return None
    translated = dict(result)
    feedback = response.get("feedback")
    if isinstance(feedback, str) and feedback:
        translated["global_note"] = feedback
    return build_qa_round(questions, translated)


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    return _read_json_object(os.path.join(artifacts_dir, "agent_meta.json")) or {}


def _read_json_object(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


__all__ = ["question_base_prompt", "question_rounds"]
