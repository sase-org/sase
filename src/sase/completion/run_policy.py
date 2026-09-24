"""Run-policy, writes, and stdin classification for the Command Line spec.

Kept beside ``kinds.PATH_OVERRIDES`` so the next phase (value-kind coverage)
can share the same ``(command_path, dest)`` addressing style. Every table path
is validated against the live parser by the drift test; its failure message
tells the author exactly where and how to classify a new command.
"""

from __future__ import annotations

from typing import Any, Final

from sase.completion.model import RunPolicyRule

_FOREGROUND_SERVER_NOTE: Final = "Foreground server; use `sase service start`"

# (path) -> [rules]. Each rule is {"policy", "when", "note"} where "when" is
# {"absent": [dest...]} | {"equals": {dest: value}} | None. The first matching
# rule wins; a leaf with no rules is "proc".
_RUN_POLICY_TABLE: Final[dict[tuple[str, ...], tuple[dict[str, Any], ...]]] = {
    ("run",): (
        {"policy": "foreground", "when": {"absent": ["prompt"]}, "note": None},
        {"policy": "foreground", "when": {"equals": {"prompt": "."}}, "note": None},
    ),
    ("prompt", "edit"): ({"policy": "foreground", "when": None, "note": None},),
    ("prompt", "run"): ({"policy": "foreground", "when": None, "note": None},),
    ("artifact", "open"): ({"policy": "foreground", "when": None, "note": None},),
    ("pager",): ({"policy": "foreground", "when": None, "note": None},),
    ("tmux-agent",): ({"policy": "foreground", "when": None, "note": None},),
    # `sudo answer` prompts interactively when no decision flag is given.
    # `--run` implies approval, but the plan's sweep names --approve/--deny,
    # so the rule keys on those two dests.
    ("sudo", "answer"): (
        {
            "policy": "foreground",
            "when": {"absent": ["approve", "deny"]},
            "note": None,
        },
    ),
    ("tui",): (
        {
            "policy": "deny",
            "when": None,
            "note": "You're already in the TUI",
        },
    ),
    ("service", "run"): (
        {"policy": "deny", "when": None, "note": _FOREGROUND_SERVER_NOTE},
    ),
    ("scheduler", "run"): (
        {"policy": "deny", "when": None, "note": _FOREGROUND_SERVER_NOTE},
    ),
    ("mobile", "gateway", "start"): (
        {"policy": "deny", "when": None, "note": _FOREGROUND_SERVER_NOTE},
    ),
    ("lsp",): ({"policy": "deny", "when": None, "note": _FOREGROUND_SERVER_NOTE},),
}

# NOTE: `gate act` editor actions (edit_file kind) need a terminal, but the
# kind is a runtime property of the gate bundle, not a static CLI dest value
# the {"absent"/"equals"} wire format can match. The resolver phase must
# evaluate the operation kind at runtime instead of reading a static table
# entry here.

# Heuristic for the advisory `writes` chip: exact match on the leaf name.
# Explicit per-path overrides win both ways (True set, then False set).
_WRITES_VERBS: Final[frozenset[str]] = frozenset(
    {
        "close",
        "create",
        "delete",
        "kill",
        "prune",
        "remove",
        "restart",
        "update",
        "archive",
        "rebase",
        "restore",
        "revert",
        "rewind",
        "reword",
        "submit",
        "sync",
        "tag",
        "enable",
        "disable",
        "add",
        "rm",
        "set",
    }
)

# Leaves that write but are not in _WRITES_VERBS (leaf name -> paths).
_WRITES_TRUE_OVERRIDES: Final[frozenset[tuple[str, ...]]] = frozenset(
    {
        ("bead", "note"),
        ("bead", "snooze"),
        ("bead", "work"),
        ("bead", "dep", "add"),
        ("gate", "act"),
        ("gate", "answer"),
        ("gate", "cancel"),
        ("gate", "create"),
        ("sudo", "answer"),
        ("sudo", "request"),
        ("notify", "create"),
        ("patch", "accept"),
        ("patch", "mail"),
        ("var", "set"),
    }
)

# Leaves in _WRITES_VERBS (or otherwise heuristic-True) that are read-only.
_WRITES_FALSE_OVERRIDES: Final[frozenset[tuple[str, ...]]] = frozenset(
    {
        ("artifact", "open"),
    }
)

# Commands that read stdin, so the signature notes
# "reads stdin; pass input via flags or files".
_STDIN_PATHS: Final[frozenset[tuple[str, ...]]] = frozenset(
    {
        ("notify", "create"),
        ("comments",),
        ("gate", "create"),
        ("sudo", "request"),
        ("pager",),
        ("var", "set"),
        ("xprompt", "expand"),
    }
)


def run_policy_for(path: tuple[str, ...]) -> tuple[RunPolicyRule, ...]:
    """Return the run-policy rules for *path* (empty tuple means proc)."""
    rules = _RUN_POLICY_TABLE.get(path, ())
    return tuple(
        RunPolicyRule(
            policy=str(rule["policy"]),
            when=rule.get("when"),
            note=rule.get("note"),
        )
        for rule in rules
    )


def writes_for(path: tuple[str, ...]) -> bool:
    """Return True when *path* should carry the advisory writes chip."""
    if path in _WRITES_FALSE_OVERRIDES:
        return False
    if path in _WRITES_TRUE_OVERRIDES:
        return True
    return bool(path) and path[-1] in _WRITES_VERBS


def stdin_for(path: tuple[str, ...]) -> bool:
    """Return True when *path* reads stdin."""
    return path in _STDIN_PATHS


def policy_table_paths() -> tuple[tuple[str, ...], ...]:
    """Return every path mentioned in the policy/writes/stdin tables."""
    paths: set[tuple[str, ...]] = set(_RUN_POLICY_TABLE)
    paths |= set(_WRITES_TRUE_OVERRIDES)
    paths |= set(_WRITES_FALSE_OVERRIDES)
    paths |= set(_STDIN_PATHS)
    return tuple(sorted(paths))


__all__ = [
    "policy_table_paths",
    "run_policy_for",
    "stdin_for",
    "writes_for",
]
