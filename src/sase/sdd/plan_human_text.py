"""Human-authored text evidence for memory-consent quote checks.

A memory decision's ``requested:`` quote counts only against text a human
wrote in the planner's chain:

- the chain root's ``submitted_prompt.md`` (the launch-boundary text
  before alias or macro expansion), only when that root's ``prompt_origin``
  is ``typed``;
- plan-gate feedback bullets from responses whose ``caller`` is ``human``
  and whose ``source`` is not ``auto_resolution``;
- ``/sase_questions`` free text (``custom_feedback``, ``global_note``)
  under the same caller/source rule. Selected option labels are
  agent-written and never count.

Everything here fails closed: unknown provenance, a missing quote
source, or an unresolvable context yields nothing for that source.
Missing files, missing fields, or legacy runs (no ``prompt_origin`` /
``caller`` recorded) yield nothing at all.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

#: Friendly names for where one human text came from. The quote matcher
#: treats them opaquely; keep them stable and human-readable.
ROOT_PROMPT_SOURCE = "root_prompt"
PLAN_FEEDBACK_SOURCE = "plan_feedback"
QUESTION_ANSWER_SOURCE = "question_answer"
QUESTION_NOTE_SOURCE = "question_note"

#: Gate ``source`` value that never counts as human authorship, even when
#: the submitting process classifies as human.
_AUTO_RESOLUTION_SOURCE = "auto_resolution"

_MAX_CHAIN_LINKS = 200
_MAX_SESSION_LINKS = 50

_PREV_ARTIFACTS_DIR_KEY = "plan_gate_turn_prev_artifacts_dir"
_GATE_BUNDLE_PATH_KEY = "gate_bundle_path"
_QUESTION_RESPONSE_PATH_KEY = "question_response_path"
_QUESTION_GATE_ARTIFACTS_DIR_KEY = "question_gate_artifacts_dir"
_QUESTION_PREV_ARTIFACTS_DIR_KEY = "question_prev_artifacts_dir"
_MAX_QUESTION_LINKS = 200

_PARENT_TIMESTAMP_KEYS = (
    "parent_timestamp",
    "plan_chain_parent_timestamp",
)


@dataclass(frozen=True)
class _HumanText:
    """One human-written text with its provenance pointer."""

    source: str
    ref: str
    text: str


def human_authored_texts(artifacts_dir: str) -> tuple[_HumanText, ...]:
    """Return every human-written text reachable from *artifacts_dir*.

    Walks the planner's own metadata and its plan-gate-turn chain
    (``plan_gate_turn_prev_artifacts_dir`` links, with a session-parent
    fallback for the root), plus each link's question-round bundle.
    Never raises: any unreadable file, unexpected shape, or legacy
    (provenance-less) record contributes nothing.
    """
    head_meta = _read_meta(artifacts_dir)
    if not head_meta:
        return ()
    chain = _plan_gate_turn_chain(artifacts_dir, head_meta)
    root_dir = _chain_root(artifacts_dir, head_meta, chain)
    texts: list[_HumanText] = []
    root_text = _root_prompt_text(root_dir)
    if root_text is not None:
        texts.append(root_text)
    for link_dir in chain:
        texts.extend(_plan_feedback_texts(link_dir))
        texts.extend(_question_texts(link_dir))
    return tuple(texts)


def _plan_gate_turn_chain(
    head_artifacts_dir: str, head_meta: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return the plan-gate-turn chain, oldest first, walking back."""
    chain: list[str] = [head_artifacts_dir]
    seen = {os.path.abspath(head_artifacts_dir)}
    meta: Mapping[str, Any] = head_meta
    while len(chain) < _MAX_CHAIN_LINKS:
        prev = meta.get(_PREV_ARTIFACTS_DIR_KEY)
        if not isinstance(prev, str) or not prev:
            break
        sibling = _existing_artifacts_dir(prev)
        if sibling is None or sibling in seen:
            break
        chain.append(sibling)
        seen.add(sibling)
        meta = _read_meta(sibling)
        if not meta:
            break
    chain.reverse()
    return tuple(chain)


def _chain_root(
    head_artifacts_dir: str,
    head_meta: Mapping[str, Any],
    chain: tuple[str, ...],
) -> str:
    """Return the chain root's planner artifacts dir.

    A linked chain already names its root. Otherwise the root is the
    furthest ancestor reachable through the agent session's parent
    links — the first-draft planner when this run planned plan-first,
    or the run itself when it has no parents. Anything unresolvable
    stays at the head, failing closed downstream.
    """
    if len(chain) > 1:
        return chain[0]
    if not isinstance(head_meta.get(_PREV_ARTIFACTS_DIR_KEY), str):
        return _session_root(head_artifacts_dir, head_meta)
    # A prev pointer that resolves nowhere: still try the session walk
    # before giving up on the root.
    return _session_root(head_artifacts_dir, head_meta)


def _session_root(head_artifacts_dir: str, head_meta: Mapping[str, Any]) -> str:
    """Walk session parent links to the earliest reachable ancestor."""
    current = os.path.abspath(head_artifacts_dir)
    seen = {current}
    meta: Mapping[str, Any] = head_meta
    for _ in range(_MAX_SESSION_LINKS):
        parent: str | None = None
        for key in _PARENT_TIMESTAMP_KEYS:
            raw = meta.get(key)
            if isinstance(raw, str) and raw.strip():
                candidate = _sibling_artifacts_dir(current, raw.strip())
                if candidate is not None and candidate not in seen:
                    parent = candidate
                    break
        if parent is None:
            break
        seen.add(parent)
        current = parent
        meta = _read_meta(current)
        if not meta:
            break
    return current


def _root_prompt_text(root_dir: str) -> _HumanText | None:
    """Return the root's launch-boundary prompt when it is human-typed."""
    meta = _read_meta(root_dir)
    if meta.get("prompt_origin") != "typed":
        return None
    try:
        from sase.legacy_xprompt_names import SUBMITTED_PROMPT_FILENAME
    except Exception:
        return None
    path = os.path.join(root_dir, SUBMITTED_PROMPT_FILENAME)
    text = _read_text(path)
    if not text:
        return None
    return _HumanText(source=ROOT_PROMPT_SOURCE, ref=path, text=text)


def _plan_feedback_texts(link_dir: str) -> list[_HumanText]:
    """Return human-caller feedback bullets for one plan-turn link."""
    meta = _read_meta(link_dir)
    bundle = meta.get(_GATE_BUNDLE_PATH_KEY)
    if not isinstance(bundle, str) or not bundle:
        return []
    response_path = os.path.join(bundle, "response.json")
    response = _read_json_object(response_path)
    if response is None or not _is_human_response(response):
        return []
    try:
        from sase.llm_provider._plan_utils import (
            plan_approval_result_from_gate_response,
        )

        result = plan_approval_result_from_gate_response(Path(bundle), response)
    except Exception:
        return []
    if result is None:
        return []
    if getattr(result, "action", None) != "feedback":
        return []
    feedback = getattr(result, "feedback", None)
    if not isinstance(feedback, str) or not feedback.strip():
        return []
    return [
        _HumanText(
            source=PLAN_FEEDBACK_SOURCE,
            ref=response_path,
            text=feedback.strip(),
        )
    ]


def _question_chain_members(head: str) -> tuple[str, ...]:
    """Return question-round members oldest first, walking back from *head*."""
    chain: list[str] = [head]
    seen = {os.path.abspath(head)}
    current = head
    while len(chain) < _MAX_QUESTION_LINKS:
        meta = _read_meta(current)
        prev = meta.get(_QUESTION_PREV_ARTIFACTS_DIR_KEY)
        if not isinstance(prev, str) or not prev:
            break
        sibling = _existing_artifacts_dir(prev)
        if sibling is None or sibling in seen:
            break
        chain.append(sibling)
        seen.add(sibling)
        current = sibling
    chain.reverse()
    return tuple(chain)


def _question_member_texts(member_dir: str) -> list[_HumanText]:
    """Return human-caller Q&A free text for one question-round member."""
    meta = _read_meta(member_dir)
    bundle = meta.get(_GATE_BUNDLE_PATH_KEY)
    if not isinstance(bundle, str) or not bundle:
        return []
    response_path = os.path.join(bundle, "response.json")
    response = _read_json_object(response_path)
    if response is None or not _is_human_response(response):
        return []
    try:
        from sase.user_question_actions import QUESTION_OPTION_ID
    except Exception:
        return []
    result = _submit_result(response, QUESTION_OPTION_ID)
    if result is None:
        return []
    texts: list[_HumanText] = []
    answers = result.get("answers")
    if isinstance(answers, list):
        for index, answer in enumerate(answers):
            if not isinstance(answer, dict):
                continue
            free = answer.get("custom_feedback")
            if isinstance(free, str) and free.strip():
                texts.append(
                    _HumanText(
                        source=QUESTION_ANSWER_SOURCE,
                        ref=f"{response_path}#answer-{index}",
                        text=free.strip(),
                    )
                )
    note = response.get("feedback")
    if isinstance(note, str) and note.strip():
        texts.append(
            _HumanText(
                source=QUESTION_NOTE_SOURCE,
                ref=response_path,
                text=note.strip(),
            )
        )
    return texts


def _question_texts(link_dir: str) -> list[_HumanText]:
    """Return human-caller Q&A free text for one plan-turn link."""
    meta = _read_meta(link_dir)
    head = meta.get(_QUESTION_GATE_ARTIFACTS_DIR_KEY)
    if isinstance(head, str) and head:
        live = _existing_artifacts_dir(head)
        if live is not None:
            texts: list[_HumanText] = []
            for member in _question_chain_members(live):
                texts.extend(_question_member_texts(member))
            return texts
    response_path = meta.get(_QUESTION_RESPONSE_PATH_KEY)
    if not isinstance(response_path, str) or not response_path:
        return []
    response = _read_json_object(response_path)
    if response is None or not _is_human_response(response):
        return []
    try:
        from sase.user_question_actions import QUESTION_OPTION_ID
    except Exception:
        return []
    result = _submit_result(response, QUESTION_OPTION_ID)
    if result is None:
        return []
    texts = []
    answers = result.get("answers")
    if isinstance(answers, list):
        for index, answer in enumerate(answers):
            if not isinstance(answer, dict):
                continue
            free = answer.get("custom_feedback")
            if isinstance(free, str) and free.strip():
                texts.append(
                    _HumanText(
                        source=QUESTION_ANSWER_SOURCE,
                        ref=f"{response_path}#answer-{index}",
                        text=free.strip(),
                    )
                )
    # The executor-facing free-text note lands on the response itself;
    # the question rounds layer copies it into each round as global_note.
    note = response.get("feedback")
    if isinstance(note, str) and note.strip():
        texts.append(
            _HumanText(
                source=QUESTION_NOTE_SOURCE,
                ref=response_path,
                text=note.strip(),
            )
        )
    return texts


def _is_human_response(response: Mapping[str, Any]) -> bool:
    """Return whether *response* counts as human-authored evidence."""
    if response.get("caller") != "human":
        return False
    return response.get("source") != _AUTO_RESOLUTION_SOURCE


def _submit_result(
    response: Mapping[str, Any], option_id: str
) -> dict[str, Any] | None:
    """Return the ``submit`` option's result dict, if it is one."""
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        return None
    for entry in option_results:
        if not isinstance(entry, dict) or entry.get("id") != option_id:
            continue
        result = entry.get("result")
        return result if isinstance(result, dict) else None
    return None


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    """Return an artifacts dir's agent metadata, or ``{}``."""
    return _read_json_object(os.path.join(artifacts_dir, "agent_meta.json")) or {}


def _read_json_object(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as stream:
            text = stream.read()
    except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError):
        return ""
    return text if text.strip() else ""


def _existing_artifacts_dir(path: str) -> str | None:
    """Return *path* when it is a live artifacts dir, else ``None``."""
    candidate = os.path.abspath(path)
    if not os.path.isdir(candidate):
        return None
    if not os.path.isfile(os.path.join(candidate, "agent_meta.json")):
        return None
    return candidate


def _sibling_artifacts_dir(current_dir: str, timestamp: str) -> str | None:
    """Resolve a parent timestamp to a sibling artifacts dir, if live."""
    if not timestamp or "/" in timestamp or "\\" in timestamp:
        return None
    if timestamp in (".", ".."):
        return None
    return _existing_artifacts_dir(
        os.path.join(os.path.dirname(os.path.abspath(current_dir)), timestamp)
    )


__all__ = [
    "human_authored_texts",
]
