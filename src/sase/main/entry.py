"""Main entry point for the SASE CLI tool."""

import sys
from typing import NoReturn


def main() -> NoReturn:
    """Main entry point for the SASE CLI tool."""
    if len(sys.argv) >= 2 and sys.argv[1] == "bead":
        from .bead_fast_path import try_handle_bead_fast_path

        exit_code = try_handle_bead_fast_path(sys.argv[2:])
        if exit_code is not None:
            sys.exit(exit_code)

    # Check for 'sase run' special cases before argparse processes it
    # This allows us to handle queries that contain spaces
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        from .query_handler import handle_run_special_cases

        args_after_run = sys.argv[2:]
        handle_run_special_cases(args_after_run)
        # If we get here, no special case was handled, continue to argparse

    from .parser import (
        create_parser,
        default_list_delegation_notice,
        parser_only_hint,
    )

    parser = create_parser(only=parser_only_hint(sys.argv))
    args = parser.parse_args()

    # Announce when a bare command group was implicitly delegated to its `list`
    # child, so the delegation starts the command output.
    delegation_notice = default_list_delegation_notice(args)
    if delegation_notice is not None:
        print(delegation_notice)

    # =========================================================================
    # COMMAND HANDLERS (keep sorted alphabetically to match parser order)
    # =========================================================================

    # --- ace ---
    if args.command == "ace":
        from .ace_handler import handle_ace_command

        handle_ace_command(args)

    # --- agent ---
    if args.command == "agent":
        from .agent_handler import handle_agent_command

        handle_agent_command(args)

    # --- agent-cli ---
    if args.command == "agent-cli":
        from .agent_cli_handler import handle_agent_cli_command

        handle_agent_cli_command(args)

    # --- artifact ---
    if args.command in {"artifact", "artifact-file"}:
        from .artifact_handler import handle_artifact_command

        handle_artifact_command(args)

    # --- axe ---
    if args.command == "axe":
        from .axe_handler import handle_axe_command

        handle_axe_command(args)

    # --- bead ---
    if args.command == "bead":
        from sase.bead.cli_common import BeadPublicationError
        from sase.sdd._store_types import SddMaterializationError
        from sase.bead.cli import (
            handle_bead_plus_one,
            handle_bead_blocked,
            handle_bead_close,
            handle_bead_create,
            handle_bead_dep,
            handle_bead_doctor,
            handle_bead_history,
            handle_bead_init,
            handle_bead_list,
            handle_bead_note,
            handle_bead_onboard,
            handle_bead_open,
            handle_bead_pages,
            handle_bead_ready,
            handle_bead_ref,
            handle_bead_resolve_conflicts,
            handle_bead_rm,
            handle_bead_search,
            handle_bead_show,
            handle_bead_snooze,
            handle_bead_stats,
            handle_bead_sync,
            handle_bead_sync_external,
            handle_bead_update,
            handle_bead_work,
        )

        bead_sub = getattr(args, "bead_subcommand", None)

        def _handle_bead_apply_status(bead_args: object) -> None:
            from sase.ops.commands.bead import handle_bead_operation

            sys.exit(handle_bead_operation(bead_args))  # type: ignore[arg-type]

        _BEAD_HANDLERS = {
            "+1": handle_bead_plus_one,
            "apply-status": _handle_bead_apply_status,
            "blocked": handle_bead_blocked,
            "close": handle_bead_close,
            "create": handle_bead_create,
            "dep": handle_bead_dep,
            "doctor": handle_bead_doctor,
            "history": handle_bead_history,
            "init": handle_bead_init,
            "list": handle_bead_list,
            "note": handle_bead_note,
            "onboard": handle_bead_onboard,
            "open": handle_bead_open,
            "pages": handle_bead_pages,
            "ready": handle_bead_ready,
            "ref": handle_bead_ref,
            "resolve-conflicts": handle_bead_resolve_conflicts,
            "rm": handle_bead_rm,
            "search": handle_bead_search,
            "show": handle_bead_show,
            "snooze": handle_bead_snooze,
            "stats": handle_bead_stats,
            "sync": handle_bead_sync,
            "sync-external": handle_bead_sync_external,
            "update": handle_bead_update,
            "work": handle_bead_work,
        }
        handler = _BEAD_HANDLERS.get(bead_sub)  # type: ignore[arg-type]
        if handler is None:
            print(
                "Usage: sase bead"
                " {+1,apply-status,blocked,close,create,dep,doctor,history,init,list,note,onboard,open,pages,ready,ref,resolve-conflicts,rm,search,show,snooze,stats,sync,sync-external,update,work}"
            )
            sys.exit(1)
        try:
            handler(args)
        except BeadPublicationError:
            # The mutation lane already printed its diagnostic; the command
            # must not report success for a mutation nobody else can see.
            sys.exit(1)
        except SddMaterializationError as exc:
            # A read-only bead command must fail with one actionable line,
            # not a raw traceback, when it cannot reach a store.
            print(f"sase bead {bead_sub}: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            from sase.bead.sync import schedule_current_bead_refresh

            schedule_current_bead_refresh()
        sys.exit(0)

    # --- patch / changespec ---
    if args.command in {"patch", "changespec"}:  # legacy command alias
        from .patch_handler import handle_patch_command

        handle_patch_command(args)

    # --- chat ---
    if args.command == "chat":
        from .chat_handler import handle_chat_command

        handle_chat_command(args)

    # --- comments ---
    if args.command == "comments":
        from .comments_handler import handle_comments_command

        handle_comments_command(args)

    # --- commit ---
    if args.command == "commit":  # legacy command alias for `sase stitch create`
        from .commit_handler import handle_commit_command

        handle_commit_command(args)

    # --- config ---
    if args.command == "config":
        from .config_handler import handle_config_command

        handle_config_command(args)

    # --- core ---
    if args.command == "core":
        from .core_handler import handle_core_command

        handle_core_command(args)

    # --- doctor ---
    if args.command == "doctor":
        from .doctor_handler import handle_doctor_command

        sys.exit(handle_doctor_command(args))

    # --- editor ---
    if args.command == "editor":
        from .editor_handler import handle_editor_command

        handle_editor_command(args)

    # --- file ---
    if args.command == "file":
        from .file_handler import handle_file_command

        handle_file_command(args)

    # --- file-history ---
    if args.command == "file-history":
        from .file_history_handler import handle_file_history_command

        handle_file_history_command(args)

    # --- file-hook ---
    if args.command == "file-hook":
        from .file_hook_handler import handle_file_hook_command

        handle_file_hook_command(args)

    # --- flag ---
    if args.command == "flag":
        from .flag_handler import handle_flag_group

        handle_flag_group(args)

    # --- gate ---
    if args.command == "gate":
        from .gate_handler import handle_gate_command

        handle_gate_command(args)

    # --- init ---
    if args.command == "init":
        if getattr(args, "all", False) and args.init_subcommand is not None:
            parser.error(
                "sase init --all cannot be combined with an explicit init subcommand"
            )
        if args.init_subcommand is None:
            from .init_onboarding import (
                run_init_onboarding,
                run_init_onboarding_all,
            )

            if getattr(args, "all", False):
                sys.exit(run_init_onboarding_all(args))
            sys.exit(run_init_onboarding(args))

        if args.init_subcommand == "config":
            from .config_init_handler import run_config_init

            sys.exit(run_config_init(args))

        if args.init_subcommand == "memory":
            from .init_memory_handler import handle_init_memory_command

            handle_init_memory_command(args)

        if args.init_subcommand == "repo":
            from .repo_init_handler import handle_repo_init_command

            handle_repo_init_command(args)

        if args.init_subcommand == "skills":
            from .init_skills_handler import handle_init_skills_command

            handle_init_skills_command(args)

        parser.error(f"unknown init subcommand: {args.init_subcommand}")

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
        from sase.integrations.xprompt_lsp import handle_xprompt_lsp_command

        handle_xprompt_lsp_command(args)

    # --- memory ---
    if args.command == "memory":
        from .memory_handler import handle_memory_command

        handle_memory_command(args)

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

        from sase.xprompt.loader import get_sase_package_xprompts_dir

        xprompts_dir = get_sase_package_xprompts_dir()
        if args.name == "xprompts-dir":
            print(xprompts_dir)
        elif args.name == "xprompts-schema":
            print(xprompts_dir / "workflow.schema.json")
        elif args.name == "xprompts-collection-schema":
            print(xprompts_dir / "xprompts.schema.json")
        sys.exit(0)

    # --- plan ---
    if args.command == "plan":
        from .plan_command_handler import handle_plan_command

        handle_plan_command(args)

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

    # --- skill ---
    if args.command == "skill":
        from .skills_handler import handle_skills_command

        handle_skills_command(args)

    # --- proc / task ---
    if args.command in {"proc", "task"}:  # legacy command alias
        from .proc_handler import handle_proc_command

        handle_proc_command(args)

    # --- telemetry ---
    if args.command == "telemetry":
        from .telemetry_handler import handle_telemetry_command

        handle_telemetry_command(args)

    # --- update ---
    if args.command == "update":
        from .update_handler import handle_update_command

        sys.exit(handle_update_command(args))

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

    # --- xprompt ---
    if args.command == "xprompt":
        from .xprompt_handler import handle_xprompt_command

        handle_xprompt_command(args)

    print(f"Unknown command: {args.command}")
    sys.exit(1)


if __name__ == "__main__":
    main()
