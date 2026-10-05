"""Pure parser for Claude Code transcripts and subagent transcripts."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp


def _attachment_records(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("type") != "attachment":
            continue
        attachment = record.get("attachment")
        if isinstance(attachment, dict):
            out.append(attachment)
    return out


def instruction_files(records: list[dict[str, object]]) -> list[dict[str, str]]:
    """Return natively loaded instruction files from transcript records."""
    files: list[dict[str, str]] = []
    for attachment in _attachment_records(records):
        if attachment.get("type") != "instructions":
            continue
        raw = attachment.get("files")
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            content = entry.get("content")
            if isinstance(path, str) and isinstance(content, str):
                files.append({"path": path, "content": content})
    return files


def system_prompt_text(records: list[dict[str, object]]) -> str:
    """Return the joined ``prompt_snapshot`` system prompt text."""
    parts: list[str] = []
    for attachment in _attachment_records(records):
        if attachment.get("type") != "prompt_snapshot":
            continue
        prompt = attachment.get("systemPrompt")
        if isinstance(prompt, list):
            parts.extend(str(part) for part in prompt)
        elif isinstance(prompt, str):
            parts.append(prompt)
    return "\n".join(parts)


def _tool_uses(records: list[dict[str, object]]) -> list[dict[str, object]]:
    uses: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append(block)
    return uses


def _assistant_texts(records: list[dict[str, object]]) -> list[str]:
    """Return plain-text blocks of assistant messages."""
    texts: list[str] = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("text",):
                text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
    return texts


def _tool_result_texts(records: list[dict[str, object]]) -> list[str]:
    texts: list[str] = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            body = block.get("content")
            if isinstance(body, str):
                texts.append(body)
            elif isinstance(body, list):
                for item in body:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(str(item["text"]))
    return texts


def helper_signals(records: list[dict[str, object]]) -> dict[str, Any]:
    """Extract helper template, attempt, denial, and acceptance signals."""
    attempts = 0
    for use in _tool_uses(records):
        name = use.get("name")
        tool_input = use.get("input")
        if name == "Skill" and isinstance(tool_input, dict):
            if tool_input.get("skill") == "sase_final":
                attempts += 1
        elif name == "Bash" and isinstance(tool_input, dict):
            command = tool_input.get("command", "")
            if isinstance(command, str) and fp.FINAL_ATTEMPT_RE.search(command):
                attempts += 1
    texts = _tool_result_texts(records)
    blob = "\n".join(texts)
    full_blob = blob + "\n" + "\n".join(str(block) for block in _tool_uses(records))
    full_blob += "\n" + "\n".join(_assistant_texts(records))
    return {
        "attempts": attempts,
        "has_template": fp.HELPER_TEMPLATE_FIRST_LINE in full_blob,
        "denied": sum(fp.GUARD_DENY_REASON_PREFIX in text for text in texts),
        "accepted": sum(fp.ACCEPTED_DECLARATION_OUTPUT in text for text in texts),
    }


def observe_claude_session(
    records: list[dict[str, object]],
    *,
    home_h1: str | None,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Claude transcript records to scoreboard observation fields."""
    files = instruction_files(records)
    contents = [entry["content"] for entry in files]
    contract_count = fp.count_contract_sources(contents)
    snapshot = system_prompt_text(records)
    home_hits = [
        fp.matches_h1(content, home_h1)
        for content in contents
        if home_h1 is not None and fp.matches_h1(content, home_h1) is True
    ]
    project_hits = [
        fp.matches_h1(content, project_h1)
        for content in contents
        if project_h1 is not None and fp.matches_h1(content, project_h1) is True
    ]
    foreign: str | None = None
    if "Memory" in snapshot or any("memory/" in entry["path"] for entry in files):
        foreign = "auto-memory"
    signals = helper_signals(records)
    return {
        "contract_count": contract_count,
        "home": True if home_hits else (False if contents else None),
        "project": True if project_hits else (False if contents else None),
        "directive": fp.CLAUDE_DIRECTIVE_MARKER in snapshot,
        "native_full_count": contract_count,
        "foreign": foreign,
        "has_helper_template": bool(signals["has_template"]),
        "final_attempts": int(signals["attempts"]),
        "final_denied": int(signals["denied"]),
        "final_accepted": int(signals["accepted"]),
    }


__all__ = [
    "helper_signals",
    "instruction_files",
    "observe_claude_session",
    "system_prompt_text",
]
