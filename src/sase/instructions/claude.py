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


def _use_id(block: dict[str, object]) -> str | None:
    """Return the tool-use id carried by an assistant ``tool_use`` block."""
    raw = block.get("id")
    if isinstance(raw, str) and raw:
        return raw
    fallback = block.get("tool_use_id")
    return str(fallback) if isinstance(fallback, str) and fallback else None


def _is_attempt(name: object, tool_input: object) -> bool:
    """Return whether a ``tool_use`` is a helper final-declaration attempt."""
    if name == "Skill" and isinstance(tool_input, dict):
        return tool_input.get("skill") == "sase_final"
    if name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command", "")
        return (
            isinstance(command, str) and fp.FINAL_ATTEMPT_RE.search(command) is not None
        )
    return False


def _use_kinds(records: list[dict[str, object]]) -> dict[str, dict[str, bool]]:
    """Map tool-use id to attempt and Bash/Skill flags."""
    kinds: dict[str, dict[str, bool]] = {}
    for use in _tool_uses(records):
        use_id = _use_id(use)
        if not use_id:
            continue
        name = use.get("name")
        kinds[use_id] = {
            "attempt": _is_attempt(name, use.get("input")),
            "bash_or_skill": name in ("Bash", "Skill"),
        }
    return kinds


def _tool_result_blocks(
    records: list[dict[str, object]],
) -> list[tuple[str | None, bool, list[str]]]:
    """Return ``(tool_use_id, is_error, texts)`` for each tool result."""
    out: list[tuple[str | None, bool, list[str]]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            out.append((None, False, [content]))
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            raw_id = block.get("tool_use_id")
            use_id = str(raw_id) if isinstance(raw_id, str) and raw_id else None
            if use_id is None:
                raw_alt = block.get("id")
                if isinstance(raw_alt, str) and raw_alt:
                    use_id = raw_alt
            is_error = block.get("is_error") is True
            body = block.get("content")
            texts: list[str] = []
            if isinstance(body, str):
                texts.append(body)
            elif isinstance(body, list):
                for item in body:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(str(item["text"]))
            out.append((use_id, is_error, texts))
    return out


def has_guard_denial(records: list[dict[str, object]]) -> bool:
    """Return whether a Bash/Skill result carries an error guard denial."""
    kinds = _use_kinds(records)
    for use_id, is_error, texts in _tool_result_blocks(records):
        if use_id is None or not is_error:
            continue
        kind = kinds.get(use_id)
        if kind is None or not kind["bash_or_skill"]:
            continue
        if any(fp.GUARD_DENY_REASON_PREFIX in text for text in texts):
            return True
    return False


def helper_signals(records: list[dict[str, object]]) -> dict[str, Any]:
    """Extract helper template, attempt, denial, and acceptance signals."""
    attempts = 0
    for use in _tool_uses(records):
        if _is_attempt(use.get("name"), use.get("input")):
            attempts += 1
    kinds = _use_kinds(records)
    accepted = 0
    denied = 0
    guard_denials = 0
    for use_id, is_error, texts in _tool_result_blocks(records):
        if use_id is None:
            continue
        kind = kinds.get(use_id)
        if kind is None:
            continue
        for text in texts:
            if kind["attempt"] and fp.ACCEPTED_DECLARATION_OUTPUT in text:
                accepted += 1
            if kind["attempt"] and is_error and fp.GUARD_DENY_REASON_PREFIX in text:
                denied += 1
            if (
                kind["bash_or_skill"]
                and is_error
                and fp.GUARD_DENY_REASON_PREFIX in text
            ):
                guard_denials += 1
    # The template marker lands in the helper prompt snapshot, not in tool
    # traffic: read it only from the system prompt snapshot.
    has_template = fp.HELPER_TEMPLATE_FIRST_LINE in system_prompt_text(records)
    return {
        "attempts": attempts,
        "has_template": has_template,
        "denied": denied,
        "accepted": accepted,
        "guard_denials": guard_denials,
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
    "has_guard_denial",
    "helper_signals",
    "instruction_files",
    "observe_claude_session",
    "system_prompt_text",
]
