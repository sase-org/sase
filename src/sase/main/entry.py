"""Main entry point for the SASE CLI tool."""

import sys
from typing import NoReturn

from .cl_handler import (
    handle_commit_command,
    handle_restore_command,
    handle_revert_command,
)
from .parser import create_parser
from .query_handler import handle_run_special_cases


def main() -> NoReturn:
    """Main entry point for the SASE CLI tool."""
    # Check for 'sase run' special cases before argparse processes it
    # This allows us to handle queries that contain spaces
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        args_after_run = sys.argv[2:]
        handle_run_special_cases(args_after_run)
        # If we get here, no special case was handled, continue to argparse

    parser = create_parser()
    args = parser.parse_args()

    # =========================================================================
    # COMMAND HANDLERS (keep sorted alphabetically to match parser order)
    # =========================================================================

    # --- ace ---
    if args.command == "ace":
        from .ace_handler import handle_ace_command

        handle_ace_command(args)

    # --- agents ---
    if args.command == "agents":
        from .agents_handler import handle_agents_command

        handle_agents_command(args)

    # --- axe ---
    if args.command == "axe":
        from .axe_handler import handle_axe_command

        handle_axe_command(args)

    # --- bead ---
    if args.command == "bead":
        from sase.bead.cli import (
            handle_bead_blocked,
            handle_bead_close,
            handle_bead_create,
            handle_bead_dep,
            handle_bead_doctor,
            handle_bead_init,
            handle_bead_list,
            handle_bead_onboard,
            handle_bead_ready,
            handle_bead_rm,
            handle_bead_show,
            handle_bead_stats,
            handle_bead_sync,
            handle_bead_update,
            handle_bead_work,
        )

        bead_sub = getattr(args, "bead_subcommand", None)
        _BEAD_HANDLERS = {
            "init": handle_bead_init,
            "create": handle_bead_create,
            "list": handle_bead_list,
            "show": handle_bead_show,
            "ready": handle_bead_ready,
            "update": handle_bead_update,
            "close": handle_bead_close,
            "rm": handle_bead_rm,
            "dep": handle_bead_dep,
            "blocked": handle_bead_blocked,
            "sync": handle_bead_sync,
            "stats": handle_bead_stats,
            "doctor": handle_bead_doctor,
            "onboard": handle_bead_onboard,
            "work": handle_bead_work,
        }
        handler = _BEAD_HANDLERS.get(bead_sub)  # type: ignore[arg-type]
        if handler is None:
            print(
                "Usage: sase bead"
                " {init,create,list,show,ready,update,close,rm,dep,blocked,sync,stats,doctor,onboard,work}"
            )
            sys.exit(1)
        handler(args)
        sys.exit(0)

    # --- changespec ---
    if args.command == "changespec":
        from .changespec_handler import handle_changespec_command

        handle_changespec_command(args)

    # --- chats ---
    if args.command == "chats":
        from .chats_handler import handle_chats_command

        handle_chats_command(args)

    # --- comments ---
    if args.command == "comments":
        from .comments_handler import handle_comments_command

        handle_comments_command(args)

    # --- commit ---
    if args.command == "commit":
        handle_commit_command(args)

    # --- config ---
    if args.command == "config":
        from .config_handler import handle_config_command

        handle_config_command(args)

    # --- file ---
    if args.command == "file":
        from .file_handler import handle_file_command

        handle_file_command(args)

    # --- file-history ---
    if args.command == "file-history":
        from .file_history_handler import handle_file_history_command

        handle_file_history_command(args)

    # --- init-git ---
    if args.command == "init-git":
        from sase.workspace_provider.plugins.bare_git_workspace import (
            init_bare_git_project,
        )

        project_file = init_bare_git_project(
            project_name=args.project_name,
            bare_dir=args.bare_dir,
            clone_dir=args.clone_dir,
            existing_bare=args.existing,
        )
        print(f"Initialized git project: {project_file}")
        sys.exit(0)

    # --- init-skills ---
    if args.command == "init-skills":
        from .init_skills_handler import handle_init_skills_command

        handle_init_skills_command(args)

    # --- logs ---
    if args.command == "logs":
        from sase.logs.cli import handle_logs_command

        handle_logs_command(args)

    # --- notify ---
    if args.command == "notify":
        from .notify_handler import handle_notify_command

        handle_notify_command(args)

    # --- path ---
    if args.command == "path":
        if args.name == "config-schema":
            from pathlib import Path
            import importlib.resources

            sase_pkg = Path(str(importlib.resources.files("sase")))
            schema = (sase_pkg / ".." / ".." / "config" / "sase.schema.json").resolve()
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

        handle_plan_command(args.plan_file)

    # --- questions ---
    if args.command == "questions":
        from .questions_command_handler import handle_questions_command

        handle_questions_command(args.questions_json)

    # --- restore ---
    if args.command == "restore":
        handle_restore_command(args)

    # --- revert ---
    if args.command == "revert":
        handle_revert_command(args)

    # --- search ---
    if args.command == "search":
        from .search_handler import handle_search_command

        handle_search_command(args)

    # --- telemetry ---
    if args.command == "telemetry":
        from .telemetry_handler import handle_telemetry_command

        handle_telemetry_command(args)

    # --- xprompt ---
    if args.command == "xprompt":
        from .xprompt_handler import handle_xprompt_command

        handle_xprompt_command(args)

    print(f"Unknown command: {args.command}")
    sys.exit(1)


if __name__ == "__main__":
    main()
