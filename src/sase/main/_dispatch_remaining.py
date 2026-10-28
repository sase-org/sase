"""Dispatch the remaining parsed SASE CLI commands."""

from __future__ import annotations

import sys
from typing import Any


def dispatch_remaining_commands(args: Any) -> None:
    # --- instructions ---
    if args.command == "instructions":
        from .instructions_handler import handle_instructions_command

        handle_instructions_command(args)

    # --- launch ---
    if args.command == "launch":
        from .launch_handler import handle_launch_command

        handle_launch_command(args)

    # --- logs ---
    if args.command == "logs":
        from sase.logs.cli import handle_logs_command

        handle_logs_command(args)

    # --- revive-log ---
    if args.command == "revive-log":
        from sase.logs.revive_log_cli import handle_revive_log_command

        handle_revive_log_command(args)

    # --- lsp ---
    if args.command == "lsp":
        from sase.integrations.macro_lsp import handle_macro_lsp_command

        handle_macro_lsp_command(args)

    # --- machine ---
    if args.command == "machine":
        from .machine_handler import handle_machine_command

        sys.exit(handle_machine_command(args))

    # --- memory ---
    if args.command == "memory":
        from .memory_handler import handle_memory_command

        handle_memory_command(args)

    # --- migrate ---
    if args.command == "migrate":
        from .migrate_handler import handle_migrate_command

        handle_migrate_command(args)

    # --- mobile ---
    if args.command == "mobile":
        from .mobile_handler import handle_mobile_command

        handle_mobile_command(args)

    # --- monitor ---
    if args.command == "monitor":
        from .monitor_handler import handle_monitor_command

        handle_monitor_command(args)

    # --- notify ---
    if args.command == "notify":
        from .notify_handler import handle_notify_command

        handle_notify_command(args)

    # --- pager ---
    if args.command == "pager":
        from .pager_handler import handle_pager_command

        sys.exit(handle_pager_command(args))

    # --- path ---
    if args.command == "path":
        if args.name == "config-schema":
            from sase.config.inventory import config_schema_path

            schema = config_schema_path()
            if schema.is_file():
                print(schema)
            else:
                print(f"config-schema not found at {schema}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)

        from sase.macro.loader import get_sase_package_macros_dir

        macros_dir = get_sase_package_macros_dir()
        if args.name == "macros-dir":
            print(macros_dir)
        elif args.name == "macros-schema":
            print(macros_dir / "workflow.schema.json")
        elif args.name == "macros-collection-schema":
            print(macros_dir / "macros-collection.schema.json")
        sys.exit(0)

    # --- plan ---
    if args.command == "plan":
        from .plan_command_handler import handle_plan_command

        handle_plan_command(args)

    # --- pipe ---
    if args.command == "pipe":
        from .pipe_handler import handle_pipe_command

        handle_pipe_command(
            args.prompt,
            fresh=bool(getattr(args, "fresh", False)),
            json_output=bool(getattr(args, "json", False)),
            model=getattr(args, "model", None),
            name=getattr(args, "name", None),
            reason=getattr(args, "reason", None),
        )

    # --- plugin ---
    if args.command == "plugin":
        from .plugin_handler import handle_plugin_command

        handle_plugin_command(args)

    # --- project ---
    if args.command == "project":
        from .project_handler import handle_project_command

        handle_project_command(args)

    # --- prompt ---
    if args.command == "prompt":
        from .prompt_handler import handle_prompt_command

        handle_prompt_command(args)

    # --- questions ---
    if args.command == "questions":
        from .questions_command_handler import handle_questions_command

        handle_questions_command(args.questions_json)

    # --- repo ---
    if args.command == "repo":
        from .repo_handler import handle_repo_command

        handle_repo_command(args)

    # --- repro ---
    if args.command == "repro":
        from .repro_handler import handle_repro_command

        handle_repro_command(args)

    # --- restore ---
    if args.command == "restore":
        from .commit_handler import handle_restore_command

        handle_restore_command(args)

    # --- revert ---
    if args.command == "revert":
        from .commit_handler import handle_revert_command

        handle_revert_command(args)

    # --- run ---
    if args.command == "run":
        from .query_handler.special_cases import run_parsed_prompt

        run_parsed_prompt(args)

    # --- scheduler ---
    if args.command == "scheduler":
        from .scheduler_handler import handle_scheduler_command

        handle_scheduler_command(args)

    # --- screenshot ---
    if args.command == "screenshot":
        from .screenshot_handler import handle_screenshot_command

        handle_screenshot_command(args)
        sys.exit(0)

    # --- service ---
    if args.command == "service":
        from .service_handler import handle_service_command

        handle_service_command(args)

    # --- skill ---
    if args.command == "skill":
        from .skills_handler import handle_skills_command

        handle_skills_command(args)

    # --- snippet ---
    if args.command == "snippet":
        from .snippet_handler import handle_snippet_command

        handle_snippet_command(args)

    # --- stats ---
    if args.command == "stats":
        from .stats_handler import handle_stats_command

        sys.exit(handle_stats_command(args))

    # --- sudo ---
    if args.command == "sudo":
        from .sudo_handler import handle_sudo_command

        handle_sudo_command(args)

    # --- proc / task ---
    if args.command in {"proc", "task"}:  # legacy command alias
        from .proc_handler import handle_proc_command

        handle_proc_command(args)

    # --- telemetry ---
    if args.command == "telemetry":
        from .telemetry_handler import handle_telemetry_command

        handle_telemetry_command(args)

    # --- tmux-agent ---
    if args.command == "tmux-agent":
        from .tmux_agent_handler import handle_tmux_agent_command

        handle_tmux_agent_command(args)

    # --- tool ---
    if args.command == "tool":
        from .tool_handler import handle_tool_command

        handle_tool_command(args)

    # --- update ---
    if args.command == "update":
        from .update_handler import handle_update_command

        sys.exit(handle_update_command(args))

    # --- usage ---
    if args.command == "usage":
        from .usage_handler import handle_usage_command

        sys.exit(handle_usage_command(args))

    # --- validate ---
    if args.command == "validate":
        from .validate_handler import handle_validate_command

        handle_validate_command(args)

    # --- var ---
    if args.command == "var":
        from .var_handler import handle_var_command

        handle_var_command(args)

    # --- stitch ---
    if args.command in {"stitch", "vcs"}:  # legacy command alias
        from .stitch_handler import handle_stitch_command

        handle_stitch_command(args)

    # --- version ---
    if args.command == "version":
        from .version_handler import handle_version_command

        sys.exit(handle_version_command(args))

    # --- workspace ---
    if args.command == "workspace":
        from .workspace_handler import handle_workspace_command

        handle_workspace_command(args)

    # --- macro ---
    if args.command == "macro":
        from .macro_handler import handle_macro_command

        handle_macro_command(args)
