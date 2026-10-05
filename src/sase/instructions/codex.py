"""Pure parser for Codex rollout records."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp

AGENTS_BLOCK_PREFIX = "# AGENTS.md instructions for"


def _payloads(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if isinstance(payload, dict):
            out.append(payload)
    return out


def developer_texts(records: list[dict[str, Any]]) -> list[str]:
    """Return developer-role message texts (directive channel)."""
    texts: list[str] = []
    for payload in _payloads(records):
        if payload.get("type") != "message" or payload.get("role") != "developer":
            continue
        for item in payload.get("content", []):
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(str(item["text"]))
    return texts


def agents_blocks(records: list[dict[str, Any]]) -> list[str]:
    """Return natively loaded ``# AGENTS.md instructions`` block texts."""
    texts: list[str] = []
    for payload in _payloads(records):
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        for item in payload.get("content", []):
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.startswith(AGENTS_BLOCK_PREFIX):
                texts.append(text)
    return texts


def _block_body(block: str) -> str:
    """Return a native block without its ``# AGENTS.md instructions`` header."""
    lines = block.splitlines(keepends=True)
    if lines and lines[0].startswith(AGENTS_BLOCK_PREFIX):
        return "".join(lines[1:])
    return block


def observe_codex_session(
    records: list[dict[str, Any]],
    *,
    home_h1: str | None,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Codex rollout records to scoreboard observation fields."""
    developers = developer_texts(records)
    blocks = agents_blocks(records)
    bodies = [_block_body(block) for block in blocks]
    contract_count = fp.count_contract_sources(blocks)
    home_hit = any(
        home_h1 is not None and fp.matches_h1(body, home_h1) is True for body in bodies
    )
    project_hit = any(
        project_h1 is not None and fp.matches_h1(body, project_h1) is True
        for body in bodies
    )
    return {
        "contract_count": contract_count,
        "home": True if home_hit else (False if blocks else None),
        "project": True if project_hit else (False if blocks else None),
        "directive": any(fp.CODEX_DIRECTIVE_MARKER in text for text in developers),
        "native_full_count": contract_count,
        "foreign": None,
        "has_helper_template": False,
        "final_attempts": 0,
        "final_denied": 0,
        "final_accepted": 0,
    }


__all__ = [
    "AGENTS_BLOCK_PREFIX",
    "agents_blocks",
    "developer_texts",
    "observe_codex_session",
]
