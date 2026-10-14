"""Pure parser for Codex rollout records."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp

AGENTS_BLOCK_PREFIX = "# AGENTS.md instructions for"
PROJECT_DOC_SEPARATOR = "--- project-doc ---"


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


def _split_sources(body: str) -> list[str]:
    """Split one native block body into loaded sources.

    Codex 0.160.1 joins the home and project docs inside one
    ``# AGENTS.md instructions`` block as ``<INSTRUCTIONS>`` home text,
    a ``--- project-doc ---`` separator line, then project text, and
    ``</INSTRUCTIONS>``. Older rollouts carry one block per file.
    """
    cleaned = body.replace("<INSTRUCTIONS>", "").replace("</INSTRUCTIONS>", "")
    parts: list[str] = []
    current: list[str] = []
    for line in cleaned.splitlines(keepends=True):
        if line.strip() == PROJECT_DOC_SEPARATOR:
            parts.append("".join(current))
            current = []
            continue
        current.append(line)
    parts.append("".join(current))
    return [part for part in parts if part.strip()]


def block_sources(blocks: list[str]) -> list[str]:
    """Return one loaded source per home/project doc across *blocks*."""
    sources: list[str] = []
    for block in blocks:
        sources.extend(_split_sources(_block_body(block)))
    return sources


def instruction_sources(
    records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return native AGENTS sources and explicit developer-channel texts."""
    return block_sources(agents_blocks(records)), developer_texts(records)


def observe_codex_session(
    records: list[dict[str, Any]],
    *,
    home_h1: str | None,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Codex rollout records to scoreboard observation fields."""
    sources, developers = instruction_sources(records)
    blocks = agents_blocks(records)
    contract_native = fp.count_contract_occurrences(sources)
    contract_explicit = fp.count_contract_occurrences(developers)
    contract_count = contract_native + contract_explicit
    home_hit = any(
        home_h1 is not None and fp.matches_h1(source, home_h1) is True
        for source in sources
    )
    project_hit = any(
        project_h1 is not None and fp.matches_h1(source, project_h1) is True
        for source in sources
    )
    home_source = next(
        (
            source
            for source in sources
            if home_h1 is not None and fp.matches_h1(source, home_h1) is True
        ),
        None,
    )
    foreign = (
        "codex-agents"
        if home_source and fp.count_contract_occurrences([home_source]) == 0
        else None
    )
    home_explicit = any(fp.contains_heading(text, home_h1) for text in developers)
    project_explicit = any(fp.contains_heading(text, project_h1) for text in developers)
    return {
        "contract_count": contract_count,
        "contract_native": contract_native,
        "contract_explicit": contract_explicit,
        "home": True
        if home_hit or home_explicit
        else (False if blocks or developers else None),
        "project": True
        if project_hit or project_explicit
        else (False if blocks or developers else None),
        "home_native": True if home_hit else (False if blocks else None),
        "home_explicit": True if home_explicit else (False if developers else None),
        "project_native": True if project_hit else (False if blocks else None),
        "project_explicit": True
        if project_explicit
        else (False if developers else None),
        "directive": any(fp.CODEX_DIRECTIVE_MARKER in text for text in developers),
        "directive_native": any(fp.CODEX_DIRECTIVE_MARKER in text for text in sources),
        "directive_explicit": any(
            fp.CODEX_DIRECTIVE_MARKER in text for text in developers
        ),
        "native_full_count": contract_native,
        "native_contract_count": contract_native,
        "foreign": foreign,
        "has_helper_template": False,
        "final_attempts": 0,
        "final_denied": 0,
        "final_accepted": 0,
    }


__all__ = [
    "AGENTS_BLOCK_PREFIX",
    "PROJECT_DOC_SEPARATOR",
    "agents_blocks",
    "block_sources",
    "developer_texts",
    "instruction_sources",
    "observe_codex_session",
]
