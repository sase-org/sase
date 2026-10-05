"""Pure parser for Grok ``prompt_context.json`` and ``system_prompt.txt``."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp

HUMAN_RULES_OPEN = "<human_rules>"
HUMAN_RULES_CLOSE = "</human_rules>"


def human_rules_block(system_prompt: str) -> str:
    """Return the ``<human_rules>`` explicit-channel block, or ``""``."""
    start = system_prompt.find(HUMAN_RULES_OPEN)
    end = system_prompt.find(HUMAN_RULES_CLOSE)
    if start < 0 or end < 0 or end <= start:
        return ""
    return system_prompt[start + len(HUMAN_RULES_OPEN) : end]


def observe_grok_session(
    prompt_context: dict[str, Any],
    system_prompt: str,
    *,
    project_h1: str | None,
) -> dict[str, Any]:
    """Reduce Grok session records to scoreboard observation fields."""
    raw_agents = prompt_context.get("agents_md_files", [])
    native_texts: list[str] = []
    if isinstance(raw_agents, list):
        for entry in raw_agents:
            if isinstance(entry, dict) and isinstance(entry.get("content"), str):
                native_texts.append(str(entry["content"]))
            elif isinstance(entry, str):
                native_texts.append(entry)
    native_contract = fp.count_contract_sources(native_texts)
    rules = human_rules_block(system_prompt)
    # The explicit ``--rules`` channel is not a native load.
    directive = fp.GROK_DIRECTIVE_OPENING in rules
    rules_contract = 1 if rules and fp.contains_contract(rules) else 0
    if rules:
        project = (
            True
            if (project_h1 is not None and fp.matches_h1(rules, project_h1))
            else False
        )
    elif native_texts:
        if project_h1 is None:
            project = None
        else:
            project = any(
                fp.matches_h1(text, project_h1) is True for text in native_texts
            )
    else:
        project = False
    memory_enabled = str(prompt_context.get("memory_enabled", "False"))
    audience = str(prompt_context.get("audience", ""))
    foreign = f"memory-v2½:{memory_enabled}" if memory_enabled else None
    return {
        "contract_count": native_contract + rules_contract,
        "home": False if not native_texts and not rules else False,
        "project": project,
        "directive": directive,
        "native_full_count": native_contract,
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
    "observe_grok_session",
]
