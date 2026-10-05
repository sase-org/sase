"""PreToolUse guard denying root-only operations to Claude native helpers.

This script is intentionally **stdlib-only** with no ``sase`` imports so the
Claude hook can run it as ``<sys.executable> -I <path>`` quickly on every
``Bash``/``Skill`` call.

It reads one PreToolUse JSON payload on stdin and denies only when the
payload carries a non-empty ``agent_id`` (which Claude sets only for calls
made inside a native subagent) *and* the call is a root-only operation:

- a ``Bash`` command invoking a root-only CLI form (see decision
  ``helpers-return-roots-declare``: ``sase final context|defer|prepare|submit``
  plus the turn-ending CLI forms the root-only skills run), or
- a ``Skill`` call naming a root-only skill (the ``skill`` input field).

A deny prints the hook JSON block with a ``SASE helper guard:`` reason and
exits 0. Every other input — a missing ``agent_id`` (the root's own calls),
other tools, or malformed stdin — exits 0 silently.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

GUARD_DENY_REASON_PREFIX = "SASE helper guard:"

# Root-only skills (epic plan decision 6). A helper invoking one of these
# through the Skill tool would act for the turn it does not own.
ROOT_ONLY_SKILLS = frozenset(
    {
        "sase_final",
        "sase_gate",
        "sase_git_commit",
        "sase_handoff",
        "sase_monitor",
        "sase_plan",
        "sase_questions",
        "sase_run",
        "sase_sudo",
    }
)

# Root-only ``sase final`` subcommands. Read-only forms (list, show, status,
# doctor) stay allowed so helpers can inspect turn state.
ROOT_ONLY_FINAL_SUBCOMMANDS = frozenset({"context", "defer", "prepare", "submit"})

# Turn-ending CLI forms the root-only skills run, derived from the skill
# sources in ``src/sase/macros/skills/``. Each entry maps a ``sase <sub>``
# command to the denied sub-subcommands, or ``None`` when any use is denied:
# - sase_final -> sase final context|defer|prepare|submit
# - sase_gate -> sase gate create / sase gate wait
# - sase_git_commit -> sase stitch create
# - sase_handoff -> sase pipe
# - sase_monitor -> sase monitor start
# - sase_plan -> sase plan propose
# - sase_questions -> sase questions
# - sase_run -> sase run / sase launch request
# - sase_sudo -> sase sudo request
ROOT_ONLY_ARGV_RULES: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("final", ROOT_ONLY_FINAL_SUBCOMMANDS),
    ("gate", frozenset({"create", "wait"})),
    ("launch", frozenset({"request"})),
    ("monitor", frozenset({"start"})),
    ("pipe", None),
    ("plan", frozenset({"propose"})),
    ("questions", None),
    ("run", None),
    ("stitch", frozenset({"create"})),
    ("sudo", frozenset({"request"})),
)

_SHELL_SEPARATORS = ("&&", "||", ";", "|", "&", "\n", "(", ")")


def _split_segments(command: str) -> list[str]:
    """Split a shell command into segments on shell separators."""
    segments = [command]
    for separator in _SHELL_SEPARATORS:
        split: list[str] = []
        for segment in segments:
            split.extend(segment.split(separator))
        segments = split
    return segments


def _strip_env_assignments(tokens: list[str]) -> list[str]:
    """Drop leading ``VAR=value`` assignments from a token list."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        name, separator, _ = token.partition("=")
        if separator and name.isidentifier():
            index += 1
            continue
        break
    return tokens[index:]


def _match_denied_argv(tokens: list[str]) -> str | None:
    """Return a describe-what-was-blocked string, or ``None`` if allowed."""
    argv = _strip_env_assignments(tokens)
    if not argv:
        return None
    if os.path.basename(argv[0]) != "sase":
        return None
    if len(argv) < 2:
        return None
    sub = argv[1]
    rest = argv[2:]
    for denied_sub, denied_rest in ROOT_ONLY_ARGV_RULES:
        if sub != denied_sub:
            continue
        if denied_rest is None:
            return f"sase {sub}"
        if rest and rest[0] in denied_rest:
            return f"sase {sub} {rest[0]}"
        return None
    return None


def _denied_bash_command(command: object) -> str | None:
    """Return a blocked-command description, or ``None`` when allowed."""
    if not isinstance(command, str) or not command.strip():
        return None
    for segment in _split_segments(command):
        if not segment.strip():
            continue
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            # Unbalanced quotes or other lex failures: fall back to a plain
            # whitespace split so one malformed segment cannot hide a denial.
            tokens = segment.split()
        blocked = _match_denied_argv(tokens)
        if blocked is not None:
            return blocked
    return None


def _denied_skill_name(tool_input: object) -> str | None:
    """Return a blocked-skill description, or ``None`` when allowed."""
    if not isinstance(tool_input, dict):
        return None
    skill = tool_input.get("skill")
    if not isinstance(skill, str):
        return None
    if skill.strip() in ROOT_ONLY_SKILLS:
        return f"Skill '{skill.strip()}'"
    return None


def _deny(reason: str) -> int:
    """Print the hook deny block and return the process exit code."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{GUARD_DENY_REASON_PREFIX} {reason}; "
                "return your result to the parent instead"
            ),
        }
    }
    sys.stdout.write(json.dumps(payload))
    return 0


def main() -> int:
    """Read the PreToolUse payload on stdin and allow or deny it."""
    try:
        raw = sys.stdin.read()
    except OSError:
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return 0
    tool_name = payload.get("tool_name")
    if tool_name == "Bash":
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        blocked = _denied_bash_command(command)
        if blocked is not None:
            return _deny(
                f"blocked '{blocked}' - only the root SASE agent runs "
                "turn-ending operations"
            )
        return 0
    if tool_name == "Skill":
        blocked = _denied_skill_name(payload.get("tool_input"))
        if blocked is not None:
            return _deny(
                f"blocked {blocked} - only the root SASE agent runs root-only skills"
            )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
