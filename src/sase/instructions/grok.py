"""Pure parser for Grok ``prompt_context.json`` and ``system_prompt.txt``."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp

HUMAN_RULES_OPEN = "<human_rules>"
HUMAN_RULES_CLOSE = "</human_rules>"


def human_rules_block(system_prompt: str) -> str:
    """Return the ``<human_rules>`` explicit-channel block, or ``""``."""
    blocks = human_rules_blocks(system_prompt)
    return blocks[0] if blocks else ""


def human_rules_blocks(system_prompt: str) -> list[str]:
    """Return every explicit ``<human_rules>`` block in source order."""
    blocks: list[str] = []
    offset = 0
    while True:
        start = system_prompt.find(HUMAN_RULES_OPEN, offset)
        if start < 0:
            break
        content_start = start + len(HUMAN_RULES_OPEN)
        end = system_prompt.find(HUMAN_RULES_CLOSE, content_start)
        if end < 0:
            break
        blocks.append(system_prompt[content_start:end])
        offset = end + len(HUMAN_RULES_CLOSE)
    return blocks


def instruction_sources(
    prompt_context: dict[str, Any], system_prompt: str
) -> tuple[list[str], list[str]]:
    """Return native agent files and the explicit ``<human_rules>`` channel."""
    raw_agents = prompt_context.get("agents_md_files", [])
    native: list[str] = []
    if isinstance(raw_agents, list):
        for entry in raw_agents:
            if isinstance(entry, dict) and isinstance(entry.get("content"), str):
                native.append(str(entry["content"]))
            elif isinstance(entry, str):
                native.append(entry)
    return native, human_rules_blocks(system_prompt)


def observe_grok_session(
    prompt_context: dict[str, Any],
    system_prompt: str,
    *,
    home_h1: str | None = None,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Grok session records to scoreboard observation fields."""
    native_texts, explicit_texts = instruction_sources(prompt_context, system_prompt)
    native_contract = fp.count_contract_occurrences(native_texts)
    explicit_contract = fp.count_contract_occurrences(explicit_texts)
    rules = "\n".join(explicit_texts)
    # The explicit ``--rules`` channel is not a native load.
    directive = fp.GROK_DIRECTIVE_OPENING in rules
    home_native = any(fp.matches_h1(text, home_h1) is True for text in native_texts)
    project_native = any(
        fp.matches_h1(text, project_h1) is True for text in native_texts
    )
    home_explicit = any(fp.contains_heading(text, home_h1) for text in explicit_texts)
    project_explicit = any(
        fp.contains_heading(text, project_h1) for text in explicit_texts
    )
    home = home_native or home_explicit
    project = project_native or project_explicit
    memory_enabled = str(
        prompt_context.get(
            "memory_v2_enabled", prompt_context.get("memory_enabled", "False")
        )
    )
    audience = str(prompt_context.get("audience", ""))
    foreign = f"memory-v2½:{memory_enabled}" if memory_enabled else None
    return {
        "contract_count": native_contract + explicit_contract,
        "contract_native": native_contract,
        "contract_explicit": explicit_contract,
        "home": True if home else False,
        "project": True if project else False,
        "home_native": True if home_native else (False if native_texts else None),
        "home_explicit": True if home_explicit else (False if explicit_texts else None),
        "project_native": True if project_native else (False if native_texts else None),
        "project_explicit": True
        if project_explicit
        else (False if explicit_texts else None),
        "directive": directive,
        "directive_native": any(
            fp.GROK_DIRECTIVE_OPENING in text for text in native_texts
        ),
        "directive_explicit": any(
            fp.GROK_DIRECTIVE_OPENING in text for text in explicit_texts
        ),
        "native_full_count": native_contract,
        "native_contract_count": native_contract,
        "foreign": foreign,
        "audience": audience,
        "has_helper_template": False,
        "final_attempts": 0,
        "final_denied": 0,
        "final_accepted": 0,
    }


__all__ = [
    "HUMAN_RULES_CLOSE",
    "HUMAN_RULES_OPEN",
    "human_rules_block",
    "human_rules_blocks",
    "instruction_sources",
    "observe_grok_session",
]
