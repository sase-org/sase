"""Dispatch the first group of parsed SASE CLI commands."""

from __future__ import annotations

import sys
from typing import Any


def dispatch_initial_commands(args: Any, parser: Any) -> None:
    # --- tui ---
    if args.command == "tui":
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

    # --- autonomy ---
    if args.command == "autonomy":
        from .autonomy_handler import handle_autonomy_group

        handle_autonomy_group(args)

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
            handle_bead_attach,
            handle_bead_attachment,
            handle_bead_blocked,
            handle_bead_close,
            handle_bead_create,
            handle_bead_dep,
            handle_bead_doctor,
            handle_bead_epic_symbols,
            handle_bead_export,
            handle_bead_history,
            handle_bead_init,
            handle_bead_list,
            handle_bead_note,
            handle_bead_onboard,
            handle_bead_open,
            handle_bead_pages,
            handle_bead_read,
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
            handle_bead_task_type,
            handle_bead_touched,
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
            "attach": handle_bead_attach,
            "attachment": handle_bead_attachment,
            "blocked": handle_bead_blocked,
            "close": handle_bead_close,
            "create": handle_bead_create,
            "dep": handle_bead_dep,
            "doctor": handle_bead_doctor,
            "epic-symbols": handle_bead_epic_symbols,
            "export": handle_bead_export,
            "history": handle_bead_history,
            "init": handle_bead_init,
            "list": handle_bead_list,
            "note": handle_bead_note,
            "onboard": handle_bead_onboard,
            "open": handle_bead_open,
            "pages": handle_bead_pages,
            "read": handle_bead_read,
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
            "task-type": handle_bead_task_type,
            "touched": handle_bead_touched,
            "update": handle_bead_update,
            "work": handle_bead_work,
        }
        handler = _BEAD_HANDLERS.get(bead_sub)  # type: ignore[arg-type]
        if handler is None:
            print(
                "Usage: sase bead"
                " {+1,apply-status,attach,attachment,blocked,close,create,dep,doctor,epic-symbols,export,history,init,list,note,onboard,open,pages,read,ready,ref,resolve-conflicts,rm,search,show,snooze,stats,sync,sync-external,task-type,touched,update,work}"
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

    # --- completion ---
    if args.command == "completion":
        from .completion_handler import handle_completion_command

        sys.exit(handle_completion_command(args))

    # --- config ---
    if args.command == "config":
        from .config_handler import handle_config_command

        handle_config_command(args)

    # --- core ---
    if args.command == "core":
        from .core_handler import handle_core_command

        handle_core_command(args)

    # --- disk ---
    if args.command == "disk":
        from .disk_handler import handle_disk_command

        handle_disk_command(args)

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

    # --- final ---
    if args.command == "final":
        from .final_handler import handle_final_command

        handle_final_command(args)

    # --- flag ---
    if args.command == "flag":
        from .flag_handler import handle_flag_group

        handle_flag_group(args)

    # --- footprint ---
    if args.command == "footprint":
        from .footprint_handler import handle_footprint_command

        sys.exit(handle_footprint_command(args))

    # --- gate ---
    if args.command == "gate":
        from .gate_handler import handle_gate_command

        handle_gate_command(args)

    # --- goal ---
    if args.command == "goal":
        from .goal_handler import handle_goal_group

        handle_goal_group(args)

    # --- init ---
    if args.command == "init":
        selected_projects = getattr(args, "project", None) or []
        if getattr(args, "all", False) and args.init_subcommand is not None:
            parser.error(
                "sase init --all cannot be combined with an explicit init subcommand"
            )
        if selected_projects and args.init_subcommand is not None:
            parser.error(
                "sase init --project cannot be combined with an explicit init "
                "subcommand"
            )
        if args.init_subcommand is None:
            from .init_onboarding import (
                run_init_onboarding,
                run_init_onboarding_all,
            )

            if getattr(args, "all", False) or selected_projects:
                sys.exit(run_init_onboarding_all(args))
            sys.exit(run_init_onboarding(args))

        if args.init_subcommand == "config":
            from .config_init_handler import run_config_init

            sys.exit(run_config_init(args))

        if args.init_subcommand == "machine":
            from .init_machine_handler import handle_init_machine_command

            handle_init_machine_command(args)

        if args.init_subcommand == "memory":
            from .init_memory_handler import handle_init_memory_command

            handle_init_memory_command(args)

        if args.init_subcommand == "repo":
            from .repo_init_handler import handle_repo_init_command

            handle_repo_init_command(args)

        if args.init_subcommand == "service":
            from .init_service_handler import handle_init_service_command

            handle_init_service_command(args)

        if args.init_subcommand == "skills":
            from .init_skills_handler import handle_init_skills_command

            handle_init_skills_command(args)

        parser.error(f"unknown init subcommand: {args.init_subcommand}")
