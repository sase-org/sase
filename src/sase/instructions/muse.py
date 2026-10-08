"""Pure parser for Muse ``session.jsonl`` records."""

from __future__ import annotations

import json
from typing import Any

from sase.instructions import fingerprints as fp


def _inner_records(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unwrap Muse's retained-frame children into inner record dicts."""
    inner: list[dict[str, Any]] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        children = envelope.get("children")
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            raw = child.get("record_json")
            if not isinstance(raw, str):
                continue
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                inner.append(decoded)
    return inner


def _context_block_texts(payload: dict[str, Any]) -> list[str]:
    """Return native ``rules_file`` context-block texts of one payload."""
    texts: list[str] = []
    if payload.get("source") == "rules_file" and isinstance(payload.get("text"), str):
        texts.append(str(payload["text"]))
    event = payload.get("event")
    if isinstance(event, dict):
        roster = event.get("run_context_messages")
        if isinstance(roster, list):
            for message in roster:
                if not isinstance(message, dict):
                    continue
                if message.get("source") != "rules_file":
                    continue
                text = message.get("text")
                if isinstance(text, str):
                    texts.append(text)
    return texts


def _payload_texts(payload: dict[str, Any]) -> list[str]:
    """Return candidate texts of one session payload."""
    texts: list[str] = []
    texts.extend(_context_block_texts(payload))
    event = payload.get("event")
    if isinstance(event, dict):
        for key in ("text", "prompt"):
            value = event.get(key)
            if isinstance(value, str) and value:
                texts.append(value)
    for message in payload.get("model_messages", []):
        if not isinstance(message, dict):
            continue
        for item in message.get("content", []):
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(str(item["text"]))
    return texts


def rules_texts(envelopes: list[dict[str, Any]]) -> list[str]:
    """Return native ``source: rules_file`` record texts."""
    texts: list[str] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            continue
        texts.extend(_context_block_texts(payload))
    for record in _inner_records(envelopes):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != "rules_file":
            continue
        text = payload.get("text")
        if isinstance(text, str):
            texts.append(text)
    # Fallback: raw lines that already carry the rules-file scope marker.
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        blob = json.dumps(envelope)
        if '<rules-file scope="project"' in blob:
            texts.append(blob)
    # Deduplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for text in texts:
        if text not in seen:
            seen.add(text)
            unique.append(text)
    return unique


def prompt_texts(envelopes: list[dict[str, Any]]) -> list[str]:
    """Return prompt-prefix texts that may carry the Muse directive."""
    texts: list[str] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("payload")
        if isinstance(payload, dict):
            texts.extend(_payload_texts(payload))
        for key in ("prompt", "text", "message"):
            value = envelope.get(key)
            if isinstance(value, str) and value:
                texts.append(value)
    for record in _inner_records(envelopes):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        texts.extend(_payload_texts(payload))
        for key in ("prompt", "text", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                texts.append(value)
    return texts


def observe_muse_session(
    envelopes: list[dict[str, Any]],
    *,
    home_h1: str | None,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Muse session records to scoreboard observation fields."""
    natives = rules_texts(envelopes)
    contract_count = fp.count_contract_sources(natives)
    prompts = prompt_texts(envelopes)
    prompt_blob = "\n".join(prompts + natives)
    home_hit = any(
        home_h1 is not None and fp.matches_h1(text, home_h1) is True for text in natives
    )
    project_hit = any(
        project_h1 is not None and fp.matches_h1(text, project_h1) is True
        for text in natives
    )
    return {
        "contract_count": contract_count,
        "home": True if home_hit else False,
        "project": True if project_hit else (False if natives else None),
        "directive": fp.MUSE_DIRECTIVE_MARKER in prompt_blob,
        "native_full_count": contract_count,
        "foreign": None,
        "has_helper_template": False,
        "final_attempts": 0,
        "final_denied": 0,
        "final_accepted": 0,
    }


__all__ = [
    "_context_block_texts",
    "observe_muse_session",
    "prompt_texts",
    "rules_texts",
]
