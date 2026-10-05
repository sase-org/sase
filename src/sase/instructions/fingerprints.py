"""Shared literal markers and fingerprint helpers.

Phase workers must use these exact strings (epic plan decision 5). Tests tie
the scoreboard fingerprints to the shipped adapter constants.
"""

from __future__ import annotations

import re

# Heading text of the contract section in memory-sase.template.md.
CONTRACT_HEADING = "SASE Final Declaration"
# Opening of the Grok single-turn directive (owned by grok-root).
GROK_DIRECTIVE_OPENING = "SASE single-turn instructions for Grok:"
# First line of the packaged Claude helper template (owned by claude-helpers).
HELPER_TEMPLATE_FIRST_LINE = "# SASE Helper Instructions"
# Prefix of the PreToolUse guard deny reason (owned by claude-helpers).
GUARD_DENY_REASON_PREFIX = "SASE helper guard:"
# Stdout fragment of an accepted ``sase final submit``.
ACCEPTED_DECLARATION_OUTPUT = "Accepted final declaration"

# Existing per-provider directive markers.
CLAUDE_DIRECTIVE_MARKER = "SASE single-turn print mode"
CODEX_DIRECTIVE_MARKER = "SASE single-turn instructions for Codex"
MUSE_DIRECTIVE_MARKER = "SASE single-turn instructions for Muse Code"
AGY_DIRECTIVE_MARKER = "SASE Antigravity print-mode instructions"

# A helper's attempt at a root-only ``sase final`` operation: a Bash tool_use
# whose command matches this, or a Skill tool_use of ``sase_final``.
FINAL_ATTEMPT_RE = re.compile(r"\bsase\s+final\s+(context|defer|prepare|submit)\b")

# Root-only skills denied to native helpers (owned by claude-helpers).
ROOT_ONLY_SKILLS: tuple[str, ...] = (
    "sase_final",
    "sase_gate",
    "sase_git_commit",
    "sase_handoff",
    "sase_monitor",
    "sase_plan",
    "sase_questions",
    "sase_run",
    "sase_sudo",
)


def flatten_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return re.sub(r"\s+", " ", text)


def contains_contract(text: str) -> bool:
    """Return whether flattened *text* carries the contract heading."""
    return CONTRACT_HEADING in flatten_ws(text)


def count_contract_sources(texts: list[str]) -> int:
    """Count loaded sources whose text carries the contract heading."""
    return sum(1 for text in texts if contains_contract(text))


def first_h1(text: str) -> str | None:
    """Return the first Markdown H1 of *text*, or ``None``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    return None


def matches_h1(text: str, expected_h1: str | None) -> bool | None:
    """Match the first H1 of *text* against *expected_h1*.

    Returns ``None`` when either side is unknown (unverifiable).
    """
    if not text or expected_h1 is None:
        return None
    actual = first_h1(text)
    if actual is None:
        return False
    return actual == expected_h1


__all__ = [
    "ACCEPTED_DECLARATION_OUTPUT",
    "AGY_DIRECTIVE_MARKER",
    "CLAUDE_DIRECTIVE_MARKER",
    "CODEX_DIRECTIVE_MARKER",
    "CONTRACT_HEADING",
    "FINAL_ATTEMPT_RE",
    "GROK_DIRECTIVE_OPENING",
    "GUARD_DENY_REASON_PREFIX",
    "HELPER_TEMPLATE_FIRST_LINE",
    "MUSE_DIRECTIVE_MARKER",
    "ROOT_ONLY_SKILLS",
    "contains_contract",
    "count_contract_sources",
    "first_h1",
    "flatten_ws",
    "matches_h1",
]
