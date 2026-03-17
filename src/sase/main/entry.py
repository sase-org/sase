"""Main entry point for the SASE CLI tool."""

import os
import sys
from typing import Literal, NoReturn, cast

from sase.ace.query import QueryParseError

from .cl_handler import (
    handle_amend_command,
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

    # --- amend ---
    if args.command == "amend":
        handle_amend_command(args)

    # --- commit ---
    if args.command == "commit":
        handle_commit_command(args)

    # --- init-sbd ---
    if args.command == "init-sbd":
        from sase.main.utils import ensure_project_file_and_get_workspace_num
        from sase.sdd import init_sbd

        print("Initializing sase-beads for SDD tracking ...", flush=True)
        print("  Resolving project workspace ...", flush=True)
        _, workspace_num, _ = ensure_project_file_and_get_workspace_num()
        try:
            sdd_path = init_sbd(os.getcwd(), workspace_num or 1)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Done! SDD directory: {sdd_path}")
        sys.exit(0)

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

    # --- notify ---
    if args.command == "notify":
        from .notify_handler import handle_notify_command

        handle_notify_command(args)

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

    # --- search ---
    if args.command == "search":
        from pathlib import Path

        from sase.ace.changespec import find_all_changespecs
        from sase.ace.display import display_changespec
        from sase.ace.query import evaluate_query, parse_query
        from rich.console import Console

        try:
            parsed_query = parse_query(args.query)
        except QueryParseError as e:
            print(f"Error: Invalid query: {e}")
            sys.exit(1)

        all_changespecs = find_all_changespecs()
        matching = [
            cs
            for cs in all_changespecs
            if evaluate_query(parsed_query, cs, all_changespecs)
        ]

        if not matching:
            print("No ChangeSpecs match the query.")
            sys.exit(0)

        if args.format == "rich":
            from collections import Counter

            from sase.ace.display_helpers import get_status_color
            from rich.panel import Panel
            from rich.text import Text

            console = Console()
            for cs in matching:
                display_changespec(cs, console)

            # Print summary panel
            summary = Text()

            # Count and status breakdown
            status_counts = Counter(cs.status for cs in matching)
            breakdown = ", ".join(
                f"{count} {status}" for status, count in sorted(status_counts.items())
            )
            summary.append(
                f"Found {len(matching)} ChangeSpec(s): {breakdown}\n\n", style="bold"
            )

            # One-line per ChangeSpec
            for cs in matching:
                status_color = get_status_color(cs.status)
                summary.append(f"  {cs.name}", style="bold #00D7AF")
                summary.append(f" [{cs.status}]\n", style=f"bold {status_color}")

            summary.rstrip()
            console.print(Panel(summary, title="Summary", border_style="green"))
        else:
            # Plain format: full ChangeSpec details without colors
            from sase.ace.display_helpers import format_running_claims_aligned
            from sase.ace.hooks import format_timestamp_display
            from sase.running_field import get_claimed_workspaces

            for cs in matching:
                file_path = cs.file_path.replace(str(Path.home()), "~")
                print(f"--- {file_path}:{cs.line_number} ---")

                # BUG field (from ChangeSpec)
                if cs.bug:
                    print(f"BUG: {cs.bug}")

                # RUNNING field (from ProjectSpec)
                running_claims = get_claimed_workspaces(cs.file_path)
                if running_claims:
                    print("RUNNING:")
                    formatted_claims = format_running_claims_aligned(running_claims)
                    for ws_col, pid_col, wf_col, cl_name in formatted_claims:
                        if cl_name:
                            print(f"  {ws_col} | {pid_col} | {wf_col} | {cl_name}")
                        else:
                            print(f"  {ws_col} | {pid_col} | {wf_col}")

                print(f"NAME: {cs.name}")
                print("DESCRIPTION:")
                for line in cs.description.split("\n"):
                    print(f"  {line}")
                if cs.kickstart:
                    print("KICKSTART:")
                    for line in cs.kickstart.split("\n"):
                        print(f"  {line}")
                if cs.parent:
                    print(f"PARENT: {cs.parent}")
                if cs.cl:
                    print(f"CL: {cs.cl}")
                print(f"STATUS: {cs.status}")
                if cs.test_targets:
                    targets = [t for t in cs.test_targets if t != "None"]
                    if targets:
                        print(f"TEST TARGETS: {', '.join(targets)}")
                if cs.commits:
                    print("COMMITS:")
                    for entry in cs.commits:
                        suffix_str = f" - ({entry.suffix})" if entry.suffix else ""
                        print(f"  ({entry.display_number}) {entry.note}{suffix_str}")
                        if entry.chat:
                            chat_path = entry.chat.replace(str(Path.home()), "~")
                            print(f"      | CHAT: {chat_path}")
                        if entry.diff:
                            diff_path = entry.diff.replace(str(Path.home()), "~")
                            print(f"      | DIFF: {diff_path}")
                if cs.hooks:
                    print("HOOKS:")
                    for hook in cs.hooks:
                        print(f"  {hook.command}")
                        for sl in hook.status_lines or []:
                            suffix_str = f" - ({sl.suffix})" if sl.suffix else ""
                            duration_str = f" ({sl.duration})" if sl.duration else ""
                            ts_str = format_timestamp_display(sl.timestamp)
                            print(
                                f"      | ({sl.commit_entry_num}) [{ts_str}] {sl.status}"
                                f"{duration_str}{suffix_str}"
                            )
                if cs.comments:
                    print("COMMENTS:")
                    for comment in cs.comments:
                        suffix_str = f" - ({comment.suffix})" if comment.suffix else ""
                        comment_path = comment.file_path.replace(str(Path.home()), "~")
                        print(f"  [{comment.reviewer}] {comment_path}{suffix_str}")
                if cs.mentors:
                    print("MENTORS:")
                    for mentor in cs.mentors:
                        profiles_str = " ".join(mentor.profiles)
                        print(f"  ({mentor.entry_id}) {profiles_str}")
                        # Print status lines for each mentor entry
                        if mentor.status_lines:
                            for msl in mentor.status_lines:
                                ts_str = (
                                    f"[{format_timestamp_display(msl.timestamp)}] "
                                    if msl.timestamp
                                    else ""
                                )
                                duration_str = (
                                    f" - ({msl.duration})" if msl.duration else ""
                                )
                                suffix_str = f" - ({msl.suffix})" if msl.suffix else ""
                                print(
                                    f"      | {ts_str}{msl.profile_name}:{msl.mentor_name}"
                                    f" - {msl.status}{duration_str}{suffix_str}"
                                )
                print()  # Blank line between ChangeSpecs

        sys.exit(0)

    # --- revert ---
    if args.command == "revert":
        handle_revert_command(args)

    # --- ace ---
    if args.command == "ace":
        from sase.ace.tui import AceApp

        # Wire --vcs-provider to env var for downstream resolution
        vcs_provider = getattr(args, "vcs_provider", None)
        if vcs_provider is not None:
            os.environ["SASE_VCS_PROVIDER"] = vcs_provider

        try:
            # Resolve model tier: prefer --model-tier, fall back to --model-size
            model_tier_override = getattr(args, "model_tier", None)
            if model_tier_override is None:
                old_size = getattr(args, "model_size", None)
                if old_size is not None:
                    model_tier_override = {"big": "large", "little": "small"}[old_size]

            if getattr(args, "agent", False):
                import asyncio

                from sase.ace.agent_runner import run_agent_mode

                w, h = args.size.split("x")
                result = asyncio.run(
                    run_agent_mode(
                        query=args.query,
                        keys=args.keys,
                        size=(int(w), int(h)),
                        model_tier_override=cast(
                            Literal["large", "small"] | None,
                            model_tier_override,
                        ),
                    )
                )
                print(result)
                sys.exit(0)

            app = AceApp(
                query=args.query,
                model_tier_override=cast(
                    Literal["large", "small"] | None, model_tier_override
                ),
                refresh_interval=args.refresh_interval,
                auto_start_axe=not getattr(args, "no_axe", False),
            )
        except QueryParseError as e:
            print(f"Error: Invalid query: {e}")
            sys.exit(1)
        app.run()
        sys.exit(0)

    # --- axe ---
    if args.command == "axe":
        # Wire --vcs-provider to env var for downstream resolution
        vcs_provider = getattr(args, "vcs_provider", None)
        if vcs_provider is not None:
            os.environ["SASE_VCS_PROVIDER"] = vcs_provider

        axe_sub = getattr(args, "axe_subcommand", None)

        if axe_sub == "chop":
            from sase.axe.cli import handle_axe_chop_list, handle_axe_chop_run

            chop_sub = getattr(args, "axe_chop_subcommand", None)
            if chop_sub == "list":
                handle_axe_chop_list(args)
            elif chop_sub == "run":
                handle_axe_chop_run(args)
            else:
                print("Usage: sase axe chop {list,run}")
                sys.exit(1)

        elif axe_sub == "lumberjack":
            from sase.axe.cli import (
                handle_axe_lumberjack_list,
                handle_axe_lumberjack_run,
                handle_axe_lumberjack_status,
            )

            lumberjack_sub = getattr(args, "axe_lumberjack_subcommand", None)
            if lumberjack_sub == "list":
                handle_axe_lumberjack_list(args)
            elif lumberjack_sub == "run":
                handle_axe_lumberjack_run(args)
            elif lumberjack_sub == "status":
                handle_axe_lumberjack_status(args)
            else:
                print("Usage: sase axe lumberjack {list,run,status}")
                sys.exit(1)

        elif axe_sub == "start":
            # `sase axe start` — orchestrator mode
            from sase.axe.config import AxeConfig, load_axe_config
            from sase.axe.orchestrator import Orchestrator

            config = load_axe_config()

            # Apply CLI overrides
            max_hook_runners = (
                args.max_hook_runners
                if args.max_hook_runners is not None
                else config.max_hook_runners
            )
            max_agent_runners = (
                args.max_agent_runners
                if args.max_agent_runners is not None
                else config.max_agent_runners
            )
            zombie_timeout = (
                args.zombie_timeout
                if args.zombie_timeout is not None
                else config.zombie_timeout_seconds
            )
            query = args.query or config.query

            config = AxeConfig(
                max_hook_runners=max_hook_runners,
                max_agent_runners=max_agent_runners,
                zombie_timeout_seconds=zombie_timeout,
                query=query,
                lumberjacks=config.lumberjacks,
            )

            try:
                orchestrator = Orchestrator(config)
            except QueryParseError as e:
                print(f"Error: Invalid query: {e}")
                sys.exit(1)
            success = orchestrator.run()
            sys.exit(0 if success else 1)

        elif axe_sub == "stop":
            import time as _time

            from rich.console import Console

            from sase.axe.process import stop_axe_daemon

            console = Console()
            t0 = _time.monotonic()
            if stop_axe_daemon():
                elapsed = _time.monotonic() - t0
                console.print(
                    f"[bold green]Axe stopped[/bold green] — all lumberjacks"
                    f" terminated in [cyan]{elapsed:.1f}s[/cyan]"
                )
            else:
                console.print(
                    "[bold yellow]Axe orchestrator is not running.[/bold yellow]"
                )
            sys.exit(0)

        else:
            # Bare `sase axe` — no subcommand given
            print("Usage: sase axe {start,stop,chop,lumberjack}")
            sys.exit(1)

    # --- xprompt ---
    if args.command == "xprompt":
        subcommand = getattr(args, "xprompt_subcommand", None)

        if subcommand == "expand":
            from sase.llm_provider.preprocessing import (
                preprocess_prompt_early,
                preprocess_prompt_late,
            )
            from sase.xprompt._trace import ExpansionTrace, print_trace

            from sase.main.query_handler import expand_embedded_workflows_in_query

            prompt = args.prompt if args.prompt else sys.stdin.read()
            trace = ExpansionTrace() if args.trace else None
            early = preprocess_prompt_early(prompt, trace=trace)
            expanded, _post_workflows = expand_embedded_workflows_in_query(early.prompt)
            processed = preprocess_prompt_late(expanded, file_ref_mode="validate")
            print(processed, end="")
            if trace is not None:
                print_trace(trace)
            sys.exit(0)

        elif subcommand == "graph":
            from sase.xprompt.graph import (
                list_workflows,
                workflow_to_mermaid,
                workflow_to_text,
            )
            from sase.xprompt.workflow_loader import get_all_workflows

            workflows = get_all_workflows()
            if not args.workflow_name:
                print(list_workflows(workflows))
                sys.exit(0)

            workflow = workflows.get(args.workflow_name)
            if workflow is None:
                print(f"Unknown workflow: {args.workflow_name}")
                sys.exit(1)

            if args.format == "text":
                print(workflow_to_text(workflow))
            else:
                print(workflow_to_mermaid(workflow))
            sys.exit(0)

        elif subcommand == "explain":
            from sase.xprompt.explain import explain_workflow
            from sase.xprompt.loader import get_all_prompts

            prompts = get_all_prompts()
            workflow = prompts.get(args.workflow_name)
            if workflow is None:
                print(f"Unknown workflow: {args.workflow_name}")
                sys.exit(1)

            # Parse --arg KEY=VALUE pairs
            named: dict[str, str] = {}
            for item in args.named_args or []:
                if "=" in item:
                    k, v = item.split("=", 1)
                    named[k] = v
                else:
                    print(f"Invalid --arg format: {item!r} (expected KEY=VALUE)")
                    sys.exit(1)

            explain_workflow(workflow, args.args, named)
            sys.exit(0)

        else:
            print("Usage: sase xprompt {expand,graph,explain}")
            sys.exit(1)

    print(f"Unknown command: {args.command}")
    sys.exit(1)


if __name__ == "__main__":
    main()
