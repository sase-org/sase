"""Lazy top-level command registrar registry."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from importlib import import_module
from typing import Any

_RegistrarSpec = tuple[str, str]

# Keep the command inventory and registrar routing in one lazy registry. Values are
# module/function names instead of imported callables so ``create_parser(only=...)``
# does not import unrelated command trees. Aliases share one registrar and are
# deduplicated when the full parser is built.
_COMMAND_REGISTRARS: dict[str, _RegistrarSpec] = {
    "ace": ("sase.main.parser_ace", "register_ace_parser"),
    "agent": ("sase.main.parser_agent", "register_agent_parser"),
    "agent-cli": ("sase.main.parser_agent_cli", "register_agent_cli_parser"),
    "artifact": ("sase.main.parser_artifact", "register_artifact_parser"),
    "artifact-file": ("sase.main.parser_artifact", "register_artifact_parser"),
    "axe": ("sase.main.parser_ace", "register_axe_parser"),
    "bead": ("sase.main.parser_bead", "register_bead_parser"),
    # Legacy command alias for the patch parser.
    "changespec": (
        "sase.main.parser_patch",
        "register_patch_parser",
    ),
    "chat": ("sase.main.parser_chat", "register_chat_parser"),
    "comments": ("sase.main.parser_commands", "register_comments_parser"),
    "completion": ("sase.main.parser_completion", "register_completion_parser"),
    "config": ("sase.main.parser_commands", "register_config_parser"),
    "core": ("sase.main.parser_core", "register_core_parser"),
    "doctor": ("sase.main.parser_doctor", "register_doctor_parser"),
    "editor": ("sase.main.parser_editor", "register_editor_parser"),
    "file": ("sase.main.parser_commands", "register_file_parser"),
    "file-history": ("sase.main.parser_commands", "register_file_history_parser"),
    "file-hook": ("sase.main.parser_file_hook", "register_file_hook_parser"),
    "final": ("sase.main.parser_final", "register_final_parser"),
    "flag": ("sase.main.parser_flag", "register_flag_parser"),
    "gate": ("sase.main.parser_gate", "register_gate_parser"),
    "init": ("sase.main.parser_init", "register_init_parser"),
    "launch": ("sase.main.parser_launch", "register_launch_parser"),
    "logs": ("sase.main.parser_commands", "register_logs_parser"),
    "lsp": ("sase.main.parser_commands", "register_lsp_parser"),
    "machine": ("sase.main.parser_machine", "register_machine_parser"),
    "memory": ("sase.main.parser_memory", "register_memory_parser"),
    "migrate": ("sase.main.parser_migrate", "register_migrate_parser"),
    "mobile": ("sase.main.parser_mobile", "register_mobile_parser"),
    "monitor": ("sase.main.parser_monitor", "register_monitor_parser"),
    "notify": ("sase.main.parser_commands", "register_notify_parser"),
    "pager": ("sase.main.parser_pager", "register_pager_parser"),
    "path": ("sase.main.parser_commands", "register_path_parser"),
    "patch": ("sase.main.parser_patch", "register_patch_parser"),
    "plan": ("sase.main.parser_plan", "register_plan_parser"),
    "pipe": ("sase.main.parser_pipe", "register_pipe_parser"),
    "plugin": ("sase.main.parser_plugin", "register_plugin_parser"),
    "proc": ("sase.main.parser_proc", "register_proc_parser"),
    "project": ("sase.main.parser_project", "register_project_parser"),
    "prompt": ("sase.main.parser_prompt", "register_prompt_parser"),
    "questions": ("sase.main.parser_commands", "register_questions_parser"),
    "repo": ("sase.main.parser_repo", "register_repo_parser"),
    "repro": ("sase.main.parser_repro", "register_repro_parser"),
    "restore": ("sase.main.parser_commit", "register_restore_parser"),
    "revert": ("sase.main.parser_commit", "register_revert_parser"),
    "revive-log": ("sase.main.parser_commands", "register_revive_log_parser"),
    "run": ("sase.main.parser_commands", "register_run_parser"),
    "skill": ("sase.main.parser_skills", "register_skills_parser"),
    "snippet": ("sase.main.parser_snippet", "register_snippet_parser"),
    "stitch": ("sase.main.parser_stitch", "register_stitch_parser"),
    # Legacy command alias for the proc parser.
    "task": ("sase.main.parser_proc", "register_proc_parser"),
    "telemetry": ("sase.main.parser_telemetry", "register_telemetry_parser"),
    "tmux-agent": ("sase.main.parser_tmux_agent", "register_tmux_agent_parser"),
    "update": ("sase.main.parser_update", "register_update_parser"),
    "validate": ("sase.main.parser_validate", "register_validate_parser"),
    "var": ("sase.main.parser_var", "register_var_parser"),
    # Legacy command alias for the stitch parser.
    "vcs": ("sase.main.parser_stitch", "register_stitch_parser"),
    "version": ("sase.main.parser_version", "register_version_parser"),
    "workspace": ("sase.main.parser_workspace", "register_workspace_parser"),
    "xprompt": ("sase.main.parser_xprompt", "register_xprompt_parser"),
}


def parser_only_hint(argv: Sequence[str]) -> str | None:
    """Return a safe narrow-parser hint for a complete command-line argv."""
    if len(argv) < 2:
        return None

    candidate = argv[1]
    if candidate.startswith("-") or candidate not in _COMMAND_REGISTRARS:
        return None
    return candidate


def register_command_parsers(
    subparsers: argparse._SubParsersAction,
    *,
    only: str | None,
) -> None:
    specs: Iterable[_RegistrarSpec]
    full_registrars: dict[str, Any] | None = None
    if only is None:
        from sase.main.parser_full_registrars import COMMAND_REGISTRARS_BY_NAME

        specs = _COMMAND_REGISTRARS.values()
        full_registrars = COMMAND_REGISTRARS_BY_NAME
    else:
        try:
            specs = (_COMMAND_REGISTRARS[only],)
        except KeyError:
            raise ValueError(f"unknown top-level command: {only}") from None

    registered: set[_RegistrarSpec] = set()
    for spec in specs:
        if spec in registered:
            continue
        registered.add(spec)
        module_name, registrar_name = spec
        if full_registrars is None:
            registrar = getattr(import_module(module_name), registrar_name)
        else:
            registrar = full_registrars[registrar_name]
        registrar(subparsers)
