"""Live-value kind classification for completable argparse slots."""

from __future__ import annotations

import argparse
from enum import StrEnum
from typing import Final


class ValueKind(StrEnum):
    """The live-value category a completable option or positional resolves to."""

    PROJECT = "project"
    BEAD = "bead"
    REPO = "repo"
    WORKSPACE = "workspace"
    PLUGIN = "plugin"
    FLAG = "flag"
    PLAN = "plan"
    PATCH = "patch"
    ARTIFACT = "artifact"
    ARTIFACT_REF = "artifact_ref"
    ARTIFACT_RELATION = "artifact_relation"
    DIRECTIVE = "directive"
    XPROMPT = "xprompt"
    SKILL = "skill"
    MEMORY = "memory"
    PROC = "proc"
    MONITOR = "monitor"
    AGENT = "agent"
    MODEL = "model"
    PROVIDER = "provider"
    SNIPPET = "snippet"
    TAG = "tag"
    PROJECT_TAG = "project_tag"
    PATH = "path"
    DIR = "dir"
    GATE = "gate"
    TOOL_RUN = "tool_run"
    TASK_TYPE = "task_type"
    PENDING_PLAN = "pending_plan"


_KIND_ATTR: Final = "_sase_completion_kind"

# Unambiguous dest/metavar strings that always resolve to the same kind,
# matched case-insensitively against an action's dest and, when set, its
# metavar. Bare, overloaded names such as "id" and "name" must never be added
# here -- resolve those one command path at a time through PATH_OVERRIDES
# instead, or a wrong kind will be offered somewhere it doesn't belong.
NAME_TABLE: Final[dict[str, ValueKind]] = {
    "agent": ValueKind.AGENT,
    "artifacts_dir": ValueKind.DIR,
    "assignee": ValueKind.AGENT,
    "author": ValueKind.AGENT,
    "bead": ValueKind.BEAD,
    "bead_id": ValueKind.BEAD,
    "bootstrap_file": ValueKind.PATH,
    "checkpoint": ValueKind.PATH,
    "cl_name": ValueKind.PATCH,
    "cwd": ValueKind.DIR,
    "depends_on": ValueKind.BEAD,
    "directory": ValueKind.DIR,
    "file": ValueKind.PATH,
    "flag_key": ValueKind.FLAG,
    "gate_ref": ValueKind.GATE,
    "home": ValueKind.DIR,
    "index_path": ValueKind.PATH,
    "inputs": ValueKind.PATH,
    "issue": ValueKind.BEAD,
    "loader_path": ValueKind.PATH,
    "manifest": ValueKind.PATH,
    "message_file": ValueKind.PATH,
    "model": ValueKind.MODEL,
    "monitor_id": ValueKind.MONITOR,
    "operation_request_path": ValueKind.PATH,
    "operation_result_path": ValueKind.PATH,
    "origin_agent": ValueKind.AGENT,
    "out_dir": ValueKind.DIR,
    "output": ValueKind.PATH,
    "patch": ValueKind.PATCH,
    "patch_name": ValueKind.PATCH,
    "path": ValueKind.PATH,
    "paths": ValueKind.PATH,
    "payload_file": ValueKind.PATH,
    "plan": ValueKind.PLAN,
    "plan_file": ValueKind.PATH,
    "plugin": ValueKind.PLUGIN,
    "plugin_name": ValueKind.PLUGIN,
    "policy": ValueKind.PATH,
    "proc_id": ValueKind.PROC,
    "project": ValueKind.PROJECT,
    "project_file": ValueKind.PATH,
    "projects_dir": ValueKind.DIR,
    "projects_root": ValueKind.DIR,
    "provider": ValueKind.PROVIDER,
    "ref": ValueKind.ARTIFACT,
    "relation": ValueKind.ARTIFACT_RELATION,
    "repo": ValueKind.REPO,
    "root": ValueKind.DIR,
    "secondary": ValueKind.DIR,
    "skill": ValueKind.SKILL,
    "slug": ValueKind.TASK_TYPE,
    "state_dir": ValueKind.DIR,
    "tag": ValueKind.TAG,
    "task_type": ValueKind.TASK_TYPE,
    "tool_show_run_id": ValueKind.TOOL_RUN,
    "value_file": ValueKind.PATH,
    "workspace": ValueKind.WORKSPACE,
    "workspace_dir": ValueKind.DIR,
    "workspace_num": ValueKind.WORKSPACE,
    "workspace_nums": ValueKind.WORKSPACE,
    "workflow_name": ValueKind.XPROMPT,
}

# Explicit (command_path, dest) overrides for actions whose dest/metavar is
# too ambiguous to resolve from NAME_TABLE alone. Bare names such as "id"
# and "name" are listed here one command path at a time.
_BEAD_ID_SLOTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("bead", "+1"), "id"),
    (("bead", "close"), "ids"),
    (("bead", "dep", "list"), "id"),
    (("bead", "dep", "tree"), "id"),
    (("bead", "epic-symbols"), "id"),
    (("bead", "history"), "id"),
    (("bead", "note"), "id"),
    (("bead", "open"), "id"),
    (("bead", "ref", "add"), "id"),
    (("bead", "ref", "list"), "id"),
    (("bead", "ref", "rm"), "id"),
    (("bead", "read"), "ids"),
    (("bead", "rm"), "ids"),
    (("bead", "show"), "ids"),
    (("bead", "snooze"), "ids"),
    (("bead", "update"), "ids"),
)
_PATCH_NAME_COMMANDS: Final[tuple[str, ...]] = (
    "accept",
    "archive",
    "mail",
    "rebase",
    "restore",
    "revert",
    "rewind",
    "reword",
    "set-origin",
    "status",
    "submit",
    "sync",
    "tag",
)
_ARTIFACT_REF_SLOTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("artifact", "link", "add"), "source_ref"),
    (("artifact", "link", "add"), "target_ref"),
    (("artifact", "link", "list"), "reference"),
    (("artifact", "link", "rm"), "source_ref"),
    (("artifact", "link", "rm"), "target_ref"),
    (("artifact", "open"), "reference"),
    (("artifact", "path"), "reference"),
    (("artifact", "read"), "reference"),
    (("artifact", "show"), "reference"),
    (("artifact", "trash", "restore"), "reference"),
    (("bead", "ref", "add"), "refs"),
    (("bead", "ref", "rm"), "refs"),
    (("patch", "ref", "add"), "refs"),
    (("patch", "ref", "rm"), "refs"),
)


def _build_path_overrides() -> dict[tuple[tuple[str, ...], str], ValueKind]:
    overrides: dict[tuple[tuple[str, ...], str], ValueKind] = {
        (("agent", "hold", "create"), "names"): ValueKind.AGENT,
        (("agent", "hold", "run"), "names"): ValueKind.AGENT,
        (("agent", "kill"), "name"): ValueKind.AGENT,
        (("agent", "restart"), "name"): ValueKind.AGENT,
        (("agent", "revert"), "name"): ValueKind.AGENT,
        (("agent", "show"), "name"): ValueKind.AGENT,
        (("agent", "tribe", "list"), "name"): ValueKind.AGENT,
        (("agent", "tribe", "set"), "name"): ValueKind.AGENT,
        (("agent", "tribe", "unset"), "name"): ValueKind.AGENT,
        (("agent", "wait"), "names"): ValueKind.AGENT,
        (
            ("artifact", "link", "relation", "show"),
            "slug",
        ): ValueKind.ARTIFACT_RELATION,
        (("artifact", "link", "suggest"), "reference"): ValueKind.ARTIFACT,
        (("bead", "work"), "parent"): ValueKind.BEAD,
        (
            ("completion", "deploy-chezmoi"),
            "source",
        ): ValueKind.DIR,
        (("completion", "ensure"), "target"): ValueKind.DIR,
        (("completion", "install"), "target"): ValueKind.DIR,
        (("var", "list"), "agents"): ValueKind.AGENT,
        (("gate", "act"), "id"): ValueKind.GATE,
        (("gate", "answer"), "id"): ValueKind.GATE,
        (("gate", "cancel"), "id"): ValueKind.GATE,
        (("gate", "show"), "id"): ValueKind.GATE,
        (("gate", "wait"), "id"): ValueKind.GATE,
        (("memory", "read"), "selectors"): ValueKind.MEMORY,
        (("memory", "show"), "selectors"): ValueKind.MEMORY,
        (("plan", "show"), "target"): ValueKind.PLAN,
        (("plan", "approve"), "selector"): ValueKind.PENDING_PLAN,
        (("plan", "reject"), "selector"): ValueKind.PENDING_PLAN,
        (("prompt", "export"), "out"): ValueKind.PATH,
        (("restore",), "name"): ValueKind.PATCH,
        (("revert",), "name"): ValueKind.PATCH,
        (("skill", "use"), "name"): ValueKind.SKILL,
        (("snippet", "add"), "trigger"): ValueKind.SNIPPET,
        (("snippet", "delete"), "trigger"): ValueKind.SNIPPET,
        (("snippet", "show"), "trigger"): ValueKind.SNIPPET,
        (("stitch", "list"), "repos"): ValueKind.REPO,
        (("xprompt", "show"), "name"): ValueKind.XPROMPT,
    }
    for slot in _BEAD_ID_SLOTS:
        overrides[slot] = ValueKind.BEAD
    for command in _PATCH_NAME_COMMANDS:
        overrides[(("patch", command), "name")] = ValueKind.PATCH
    for slot in _ARTIFACT_REF_SLOTS:
        overrides[slot] = ValueKind.ARTIFACT
    return overrides


PATH_OVERRIDES: Final[dict[tuple[tuple[str, ...], str], ValueKind]] = (
    _build_path_overrides()
)

#: Per-kind freshness windows, in seconds, for volatile candidate sets. A
#: user approving plans back-to-back must not be offered the plan they just
#: approved, or miss the one that just arrived, so ``pending_plan``
#: candidates expire quickly. This one map drives the disk-cache TTL (see
#: ``candidates_for``) and the zsh and bash in-shell cache TTLs (see the
#: emitter preambles, which read it from Python); fish relies on the disk
#: cache. Every other kind keeps its layer default.
VOLATILE_KIND_TTL_SECONDS: Final[dict[ValueKind, float]] = {
    ValueKind.PENDING_PLAN: 5,
}

# `sase run`'s PROMPT positional is not a plain kinded slot: it completes as
# native file paths *plus* stored xprompt names, a combination the ValueKind
# catalog has no single member for. Each emitter special-cases this exact
# (command_path, dest) pair directly rather than going through
# ``resolve_value_kind``. Kept here, not duplicated per emitter, so the three
# scripts cannot drift on which slot this is.
RUN_PROMPT_SLOT: Final[tuple[tuple[str, ...], str]] = (("run",), "prompt")


def set_completion_kind(action: argparse.Action, kind: ValueKind) -> None:
    """Record an explicit completion-kind override on *action*.

    Wins over both ``PATH_OVERRIDES`` and ``NAME_TABLE`` during resolution.
    """
    setattr(action, _KIND_ATTR, kind)


def resolve_value_kind(
    action: argparse.Action, command_path: tuple[str, ...]
) -> ValueKind | None:
    """Resolve the completion kind for *action* registered under *command_path*.

    Resolution order, first match wins: an explicit per-action override set by
    ``set_completion_kind``, a ``(command_path, dest)`` entry in
    ``PATH_OVERRIDES``, then a dest or metavar entry in ``NAME_TABLE``.
    """
    explicit = getattr(action, _KIND_ATTR, None)
    if explicit is not None:
        return explicit

    path_kind = PATH_OVERRIDES.get((command_path, action.dest))
    if path_kind is not None:
        return path_kind

    name_kind = NAME_TABLE.get(action.dest.lower())
    if name_kind is not None:
        return name_kind

    metavar = action.metavar
    if isinstance(metavar, str):
        return NAME_TABLE.get(metavar.lower())
    return None


#: Free-form value hints for slots that name no completable entity. Keyed by
#: lowercased action dest, mirroring ``NAME_TABLE``. Allowed values are the
#: spec wire's ``"text" | "int" | "number" | "duration"``; ``"path"`` is never
#: listed here because it is derived from the ``PATH``/``DIR`` kinds instead.
#: Dests too ambiguous for one global hint (or needing a kind on some paths)
#: stay here with the common hint while the exceptional paths take a
#: ``PATH_OVERRIDES`` kind, which wins during coverage.
_VALUE_HINT_TABLE: Final[dict[str, str]] = dict.fromkeys(
    (
        "after",
        "agents",
        "alias",
        "aliases",
        "answer",
        "approval",
        "args",
        "armer_key",
        "assignments",
        "attestation",
        "audit_id",
        "authors",
        "backup_id",
        "basename",
        "before",
        "bind_address",
        "bug_id",
        "candidate",
        "check",
        "checkout_target",
        "chop_name",
        "completion",
        "daterange",
        "dedup_key",
        "description",
        "design",
        "endpoint",
        "entry",
        "exclude",
        "explain",
        "external_ref",
        "fcm_credential_env",
        "fcm_project_id",
        "fcm_service_account_json",
        "feedback",
        "field",
        "gateway_command",
        "host",
        "id",
        "input",
        "instance",
        "instruction",
        "key",
        "keys",
        "kind",
        "label",
        "lumberjack_name",
        "machine",
        "message",
        "month",
        "name",
        "names",
        "named_args",
        "new_alias",
        "next",
        "next_model",
        "note",
        "notification_id",
        "old_alias",
        "operation",
        "option",
        "option_input",
        "options",
        "origin",
        "pane_id",
        "panel",
        "panel_icon",
        "parent",
        "pattern",
        "payload",
        "phases",
        "plus_one_note",
        "prefix",
        "profile",
        "prompt",
        "query",
        "questions_json",
        "raw_range",
        "reason",
        "remote_ref",
        "remove_by",
        "remove_when",
        "repo_id",
        "request",
        "routine",
        "run_id",
        "runtime",
        "scope",
        "script",
        "selector",
        "selectors",
        "sender",
        "session",
        "set",
        "shell",
        "shell_status",
        "shell_stop_status",
        "since",
        "size",
        "source",
        "ssh_target",
        "start_status",
        "state",
        "status",
        "stop_status",
        "subsystem",
        "sudo_command",
        "supersedes",
        "syntax",
        "target",
        "targets",
        "template",
        "text",
        "title",
        "token",
        "tool_runs_cursor",
        "tool_runs_tool",
        "tribe",
        "tribes",
        "hoods",
        "type",
        "until",
        "value",
        "values",
        "value_json",
        "verb",
        "wait",
        "web",
        "when_disabled",
        "when_enabled",
        "why",
        "window",
        "wrap",
        "write_artifacts",
    ),
    "text",
)
_VALUE_HINT_TABLE.update(
    dict.fromkeys(
        (
            "capacity",
            "context",
            "depth",
            "edit",
            "keep",
            "keep_generations",
            "keep_recent_months",
            "levels",
            "limit",
            "lines",
            "lock_timeout_ms",
            "log_lines",
            "max_agent_runners",
            "max_bytes",
            "max_history_scan",
            "max_hook_runners",
            "max_slots",
            "min_size",
            "plus_ones",
            "port",
            "push_retry_limit",
            "remove",
            "settle_ms",
            "tail_lines",
            "tool_runs_limit",
            "top",
        ),
        "int",
    )
)
_VALUE_HINT_TABLE.update(
    dict.fromkeys(
        (
            "expires",
            "idle_timeout",
            "interval",
            "startup_timeout",
            "timeout",
            "ttl",
            "zombie_timeout",
        ),
        "duration",
    )
)
_VALUE_HINT_TABLE.update(
    dict.fromkeys(
        ("push_timeout_seconds", "refresh_interval", "sanity_refresh_interval"),
        "number",
    )
)

#: Per-path free-form hint overrides, for the rare dest whose hint differs by
#: command. Empty today: every ambiguous dest is covered by a global hint
#: plus ``PATH_OVERRIDES`` kinds on the exceptional paths. Kept beside
#: ``PATH_OVERRIDES`` so a future split has a home that
#: ``resolve_value_hint`` already consults.
HINT_PATH_OVERRIDES: Final[dict[tuple[tuple[str, ...], str], str]] = {}


def resolve_value_hint(
    action: argparse.Action, command_path: tuple[str, ...]
) -> str | None:
    """Resolve the free-form value hint for *action* under *command_path*.

    Resolution order, first match wins: a ``(command_path, dest)`` entry in
    ``HINT_PATH_OVERRIDES``, then a dest entry in ``_VALUE_HINT_TABLE``.
    ``PATH``/``DIR`` kinds never reach this table: the spec builder derives
    their ``"path"`` hint from the kind directly.
    """
    path_hint = HINT_PATH_OVERRIDES.get((command_path, action.dest))
    if path_hint is not None:
        return path_hint
    return _VALUE_HINT_TABLE.get(action.dest.lower())


__all__ = [
    "HINT_PATH_OVERRIDES",
    "NAME_TABLE",
    "PATH_OVERRIDES",
    "RUN_PROMPT_SLOT",
    "ValueKind",
    "resolve_value_hint",
    "resolve_value_kind",
    "set_completion_kind",
]
