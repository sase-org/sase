"""Special case handling for sase run command."""

import sys
from pathlib import Path

from sase.history.chat import list_chat_histories
from sase.shared_utils import create_artifacts_directory

from ._daemon import run_query_daemon
from ._editor import open_editor_for_prompt, show_prompt_history_picker
from ._query import run_query
from ._resume import handle_run_with_resume


def handle_run_special_cases(args_after_run: list[str]) -> bool:
    """Handle special cases for 'sase run' before argparse processes it.

    This handles queries that contain spaces and special flags like -l, -r, -d.

    Args:
        args_after_run: Arguments after 'run' command.

    Returns:
        True if a special case was handled (and sys.exit was called), False otherwise.
    """
    # Detect and strip -d/--daemon flag
    daemon_mode = False
    if "-d" in args_after_run or "--daemon" in args_after_run:
        args_after_run = [a for a in args_after_run if a not in ("-d", "--daemon")]
        daemon_mode = True

    def _run_query(prompt: str) -> None:
        """Run a query, auto-routing multi-prompts through daemon mode."""
        if daemon_mode:
            run_query_daemon(prompt)
            return
        from sase.multi_prompt import is_multi_prompt

        if is_multi_prompt(prompt):
            from sase.multi_prompt import parse_multi_prompt

            n = len(parse_multi_prompt(prompt).segments)
            print(f"Multi-prompt detected — launching {n} agents in daemon mode")
            run_query_daemon(prompt)
            return
        run_query(prompt)

    # Handle -l/--list flag (incompatible with daemon)
    if args_after_run and args_after_run[0] in ("-l", "--list"):
        if daemon_mode:
            print("Error: -d/--daemon is incompatible with -l/--list")
            sys.exit(1)
        histories = list_chat_histories()
        if not histories:
            print("No chat histories found.")
        else:
            print("Available chat histories:")
            for history in histories:
                print(f"  {history}")
        sys.exit(0)

    # Handle VCS workflow prefix + '.' (e.g., "#gh(sase) ." or "#hg:my_cl .")
    # Opens prompt history picker with the specified project's prompts sorted to top,
    # then runs the selected prompt wrapped in the VCS workflow.
    # Handles both split args (['#gh:sase', '.']) and single arg (['#gh:sase .'])
    # since shell may or may not split depending on quoting.
    vcs_prefix: str | None = None
    if len(args_after_run) >= 2 and args_after_run[-1] == ".":
        vcs_prefix = " ".join(args_after_run[:-1])
    elif len(args_after_run) == 1 and args_after_run[0].endswith(" ."):
        vcs_prefix = args_after_run[0][:-2]
    if vcs_prefix is not None:
        if vcs_prefix.startswith("#"):
            from sase.xprompt import parse_workflow_reference, strip_hitl_suffix

            workflow_ref = vcs_prefix[1:]  # Strip leading "#"
            workflow_ref, _ = strip_hitl_suffix(workflow_ref)
            workflow_name, positional_args, _ = parse_workflow_reference(workflow_ref)

            from sase.workspace_provider import get_workflow_names

            if workflow_name in get_workflow_names() and positional_args:
                ref = positional_args[0]
                sort_by, workspace = _resolve_vcs_project_info(ref)
                prompt = show_prompt_history_picker(
                    sort_by=sort_by, workspace=workspace
                )
                if prompt is None:
                    print("No prompt selected. Aborting.")
                    sys.exit(1)
                # Replace all embedded VCS workflow tags with the
                # current prefix to handle cross-VCS reuse and
                # multi-prompt segments.
                from sase.xprompt import replace_vcs_workflow_tags

                _run_query(replace_vcs_workflow_tags(prompt, vcs_prefix))
                sys.exit(0)

    # Handle '.' - show prompt history picker
    if args_after_run == ["."]:
        prompt = show_prompt_history_picker()
        if prompt is None:
            print("No prompt selected. Aborting.")
            sys.exit(1)
        _run_query(prompt)
        sys.exit(0)

    # Handle no arguments - open editor for prompt
    if not args_after_run:
        prompt = open_editor_for_prompt()
        if prompt is None:
            print("No prompt provided. Aborting.")
            sys.exit(1)
        _run_query(prompt)
        sys.exit(0)

    # Handle -r/--resume flag (incompatible with daemon)
    if args_after_run and args_after_run[0] in ("-r", "--resume"):
        if daemon_mode:
            print("Error: -d/--daemon is incompatible with -r/--resume")
            sys.exit(1)
        handle_run_with_resume(args_after_run)
        # handle_run_with_resume calls sys.exit, but just in case:
        sys.exit(0)

    # Handle #workflow_name syntax (e.g., sase run "#split" or sase run "#explain")
    # All xprompts and workflows are treated uniformly through execute_workflow
    if args_after_run:
        potential_query = args_after_run[0]
        if potential_query.startswith("#"):
            workflow_ref = potential_query[1:]  # Strip the #

            from sase.xprompt import (
                execute_workflow,
                get_all_prompts,
                parse_workflow_reference,
                strip_hitl_suffix,
            )

            workflow_ref, hitl_override = strip_hitl_suffix(workflow_ref)
            workflow_name, positional_args, named_args = parse_workflow_reference(
                workflow_ref
            )

            # Extract project from workflow_name if it contains a slash
            project = None
            if "/" in workflow_name:
                project = workflow_name.split("/")[0]

            # get_all_prompts() returns both workflows and converted xprompts
            prompts = get_all_prompts(project=project)
            if workflow_name in prompts:
                workflow = prompts[workflow_name]
                # Multi-step prompt_part workflows (like #gh, #hg) need to go
                # through run_query so their embedded pre/post steps and
                # prompt_part expansion work correctly.
                if workflow.has_prompt_part() and not workflow.is_simple_xprompt():
                    _run_query(potential_query)
                    sys.exit(0)

                # In daemon mode, pass the full #workflow_name as the prompt
                # — the runner script handles xprompt expansion.
                if daemon_mode:
                    run_query_daemon(potential_query)
                    sys.exit(0)

                # Create artifacts directory in ~/.sase/projects/ so TUI can find it
                # Extract base workflow name (without project prefix) to avoid slashes in path
                base_workflow = (
                    workflow_name.split("/")[-1]
                    if "/" in workflow_name
                    else workflow_name
                )
                artifacts_dir = create_artifacts_directory(f"workflow-{base_workflow}")
                try:
                    execute_workflow(
                        workflow_name,
                        positional_args,
                        named_args,
                        artifacts_dir=artifacts_dir,
                        project=project,
                        hitl_override=hitl_override,
                    )
                    sys.exit(0)
                except Exception as e:
                    print(f"Workflow error: {e}")
                    sys.exit(1)

    # Handle direct query (not a known prompt, contains spaces)
    if args_after_run:
        potential_query = args_after_run[0]
        # Get known prompts dynamically (includes both xprompts and workflows)
        from sase.xprompt import get_all_prompts

        known_prompts = set(get_all_prompts().keys())
        if potential_query not in known_prompts and " " in potential_query:
            _run_query(potential_query)
            sys.exit(0)

    # No special case handled
    return False


def _resolve_vcs_project_info(ref: str) -> tuple[str, str]:
    """Resolve a VCS ref to sorting parameters for prompt history.

    Returns:
        Tuple of (sort_by, workspace) where sort_by is the branch/CL name
        for '*' marker sorting and workspace is the project name for '~'
        marker sorting.
    """
    # Repo path like user/project → project name is the last component
    if "/" in ref:
        project_name = ref.strip("/").split("/")[-1]
        return ref, project_name

    # Check if ref matches a known project shorthand
    projects_base = Path.home() / ".sase" / "projects"
    project_dir = projects_base / ref
    if project_dir.is_dir():
        return ref, ref

    # Check ChangeSpec names for the project association
    from sase.ace.changespec import find_all_changespecs

    for cs in find_all_changespecs():
        if cs.name == ref:
            return ref, cs.project_basename

    # Fallback: use ref as both sort_by and workspace
    return ref, ref
