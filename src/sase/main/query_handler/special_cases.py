"""Special case handling for sase run command."""

import sys

from ._editor import open_editor_for_prompt, show_prompt_history_picker
from ._launch import launch_query


def _print_standalone_deprecation(name: str) -> None:
    from sase.xprompt.workflow_runner import standalone_deprecation_message

    print(f"Warning: {standalone_deprecation_message(name)}", file=sys.stderr)


def _print_invalid_standalone_marker(name: str) -> None:
    from sase.xprompt.workflow_runner import invalid_explicit_standalone_message

    print(f"Error: {invalid_explicit_standalone_message(name)}", file=sys.stderr)


def handle_run_special_cases(args_after_run: list[str]) -> bool:
    """Handle special cases for 'sase run' before argparse processes it.

    This handles queries that contain spaces and the deprecated -d/--daemon shim.

    Args:
        args_after_run: Arguments after 'run' command.

    Returns:
        True if a special case was handled (and sys.exit was called), False otherwise.
    """
    # Back-compat shim: detached launch is now the only run behavior, but older
    # automation may still pass the former daemon flag.
    if "-d" in args_after_run or "--daemon" in args_after_run:
        args_after_run = [a for a in args_after_run if a not in ("-d", "--daemon")]
        print(
            "Warning: -d/--daemon is deprecated; detached launch is now the default.",
            file=sys.stderr,
        )

    # Handle workspace workflow prefix + '.' (e.g. "#gh:sase .").
    # Opens the recency-ordered prompt history picker, then runs the selected
    # prompt wrapped in the current VCS workflow.
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
                prompt = show_prompt_history_picker()
                if prompt is None:
                    print("No prompt selected. Aborting.")
                    sys.exit(1)
                # Replace all embedded VCS workflow tags with the
                # current prefix to handle cross-VCS reuse and
                # multi-prompt segments.
                from sase.xprompt import replace_vcs_workflow_tags

                launch_query(replace_vcs_workflow_tags(prompt, vcs_prefix))
                sys.exit(0)

    # Handle '.' - show prompt history picker
    if args_after_run == ["."]:
        prompt = show_prompt_history_picker()
        if prompt is None:
            print("No prompt selected. Aborting.")
            sys.exit(1)
        launch_query(prompt)
        sys.exit(0)

    # Handle no arguments - use a durable request sidecar prompt when
    # present, otherwise open an editor.
    if not args_after_run:
        from sase.ops.cli import load_request
        from sase.ops.names import RUN_LAUNCH

        sidecar_prompt = load_request(RUN_LAUNCH).payload.get("prompt")
        if isinstance(sidecar_prompt, str) and sidecar_prompt:
            launch_query(sidecar_prompt)
            sys.exit(0)
        prompt = open_editor_for_prompt()
        if prompt is None:
            print("No prompt provided. Aborting.")
            sys.exit(1)
        launch_query(prompt)
        sys.exit(0)

    # Handle #workflow_name syntax (e.g., sase run "#split" or sase run "#explain")
    # and explicit standalone workflow syntax (e.g., sase run "#!sync").
    # All xprompts and workflows launch through the same detached path.
    if args_after_run:
        potential_query = args_after_run[0]
        if potential_query.startswith("#"):
            from sase.xprompt import (
                get_all_prompts,
                iter_xprompt_references,
                parse_workflow_reference,
                strip_hitl_suffix,
            )

            refs = iter_xprompt_references(potential_query)
            leading_ref = refs[0] if refs and refs[0].start == 0 else None
            exact_ref = (
                leading_ref
                if leading_ref is not None
                and leading_ref.end == len(potential_query.strip())
                else None
            )

            if leading_ref is not None:
                workflow_name = leading_ref.name
                explicit_standalone_marker = leading_ref.is_standalone_marker
            else:
                workflow_ref = potential_query[1:]  # Strip the #
                workflow_ref, _ = strip_hitl_suffix(workflow_ref)
                workflow_name, _, _ = parse_workflow_reference(workflow_ref)
                explicit_standalone_marker = False

            # Extract project from workflow_name if it contains a slash
            project = None
            if "/" in workflow_name:
                project = workflow_name.split("/")[0]

            # get_all_prompts() returns both workflows and converted xprompts
            prompts = get_all_prompts(project=project)
            if workflow_name in prompts:
                workflow = prompts[workflow_name]
                if explicit_standalone_marker and workflow.has_prompt_part():
                    _print_invalid_standalone_marker(workflow_name)
                    sys.exit(1)

                # Multi-step prompt_part workspace workflows (like #gh) need to go
                # through the detached launch path so their embedded pre/post
                # steps and prompt_part expansion work correctly.
                if workflow.has_prompt_part() and not workflow.is_simple_xprompt():
                    launch_query(potential_query)
                    sys.exit(0)

                # Avoid treating "#!sync do more" or "#sync do more" as a direct
                # workflow invocation. Let the normal prompt path handle it.
                if exact_ref is None:
                    pass
                else:
                    if (
                        not workflow.has_prompt_part()
                        and not explicit_standalone_marker
                    ):
                        _print_standalone_deprecation(workflow_name)

                    launch_query(potential_query)
                    sys.exit(0)

    # Handle direct query (not a known prompt): a quoted multi-word prompt,
    # or a sole non-flag token (the PROMPT positional advertised by
    # `sase run --help`). Without the single-token case, such prompts would
    # parse into argparse's `run` namespace and never dispatch.
    if args_after_run:
        potential_query = args_after_run[0]
        # Get known prompts dynamically (includes both xprompts and workflows)
        from sase.xprompt import get_all_prompts

        known_prompts = set(get_all_prompts().keys())
        single_prompt_token = len(
            args_after_run
        ) == 1 and not potential_query.startswith("-")
        if potential_query not in known_prompts and (
            " " in potential_query or single_prompt_token
        ):
            launch_query(potential_query)
            sys.exit(0)

    # No special case handled
    return False


def run_parsed_prompt(args: object) -> None:
    """Dispatch a `sase run` invocation that fell through to argparse.

    :func:`handle_run_special_cases` declines a few shapes (e.g. a sole
    PROMPT token that matches a known xprompt/workflow name); route them
    through the standard query path so the documented PROMPT positional
    always dispatches instead of dead-ending on "Unknown command: run".
    """
    prompt = getattr(args, "prompt", None)
    if prompt is None:
        prompt = open_editor_for_prompt()
        if prompt is None:
            print("No prompt provided. Aborting.")
            sys.exit(1)
    launch_query(prompt)
    sys.exit(0)
