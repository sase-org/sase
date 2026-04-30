"""Handler for the 'sase xprompt' command."""

import argparse
import sys


def handle_xprompt_command(args: argparse.Namespace) -> None:
    """Handle the 'sase xprompt' command."""
    subcommand = getattr(args, "xprompt_subcommand", None)

    if subcommand == "expand":
        _handle_expand(args)
    elif subcommand == "explain":
        _handle_explain(args)
    elif subcommand == "graph":
        _handle_graph(args)
    elif subcommand == "list":
        _handle_list()
    elif subcommand == "catalog":
        _handle_catalog(args)
    else:
        print("Usage: sase xprompt {expand,explain,graph,list,catalog}")
        sys.exit(1)


def _handle_expand(args: argparse.Namespace) -> None:
    """Handle 'sase xprompt expand'."""
    from sase.llm_provider.preprocessing import (
        preprocess_prompt_early,
        preprocess_prompt_late,
    )
    from sase.xprompt._trace import ExpansionTrace, print_trace

    from sase.main.query_handler import expand_embedded_workflows_in_query
    from sase.agent.multi_prompt import parse_multi_prompt

    prompt = args.prompt if args.prompt else sys.stdin.read()

    # Parse frontmatter for local xprompt definitions so that
    # references like #_docs:telegram are expanded correctly.
    multi = parse_multi_prompt(prompt)
    local_xprompts = multi.local_xprompts or None
    prompt_body = "\n---\n".join(multi.segments)

    trace = ExpansionTrace() if args.trace else None
    early = preprocess_prompt_early(
        prompt_body, extra_xprompts=local_xprompts, trace=trace
    )
    expanded, _post_workflows = expand_embedded_workflows_in_query(early.prompt)
    processed = preprocess_prompt_late(expanded, file_ref_mode="validate")
    print(processed, end="")
    if trace is not None:
        print_trace(trace)
    sys.exit(0)


def _handle_list() -> None:
    """Handle 'sase xprompt list'."""
    import json

    from sase.xprompt.loader import get_all_prompts
    from sase.xprompt.reference_display import (
        workflow_kind_value,
        workflow_reference_insertion,
        workflow_reference_prefix,
    )

    prompts = get_all_prompts()
    items = []
    for name, wf in sorted(prompts.items()):
        is_simple = wf.is_simple_xprompt()
        user_inputs = [inp for inp in wf.inputs if not inp.is_step_input]
        inputs_json = []
        for inp in user_inputs:
            from sase.xprompt.models import UNSET

            required = inp.default is UNSET
            inputs_json.append(
                {
                    "name": inp.name,
                    "type": inp.type.value,
                    "required": required,
                    "default": (
                        None
                        if required
                        else str(inp.default)
                        if inp.default is not None
                        else None
                    ),
                }
            )
        if is_simple:
            preview = wf.get_prompt_part_content()
        else:
            lines: list[str] = [f"# Workflow: {name}", ""]
            if user_inputs:
                lines.append("## Inputs")
                for inp in user_inputs:
                    default_str = f" (default: {inp.default})" if inp.default else ""
                    lines.append(f"- {inp.name}: {inp.type.value}{default_str}")
                lines.append("")
            lines.append("## Steps")
            for i, step in enumerate(wf.steps, 1):
                if step.agent:
                    stype, label = "agent", step.agent.split("\n")[0][:50]
                elif step.bash:
                    stype, label = "bash", step.bash
                elif step.python:
                    stype, label = "python", step.python
                elif step.prompt_part:
                    stype, label = (
                        "prompt_part",
                        step.prompt_part.split("\n")[0][:50],
                    )
                else:
                    stype, label = "unknown", "?"
                lines.append(f"{i}. [{stype}] {step.name}: {label}")
            preview = "\n".join(lines)
        items.append(
            {
                "name": name,
                "type": "xprompt" if is_simple else "workflow",
                "kind": workflow_kind_value(wf),
                "prefix": workflow_reference_prefix(wf),
                "insertion": workflow_reference_insertion(name, wf),
                "source": wf.source_path,
                "inputs": inputs_json,
                "tags": [t.value for t in wf.tags],
                "preview": preview,
            }
        )
    print(json.dumps(items))
    sys.exit(0)


def _handle_graph(args: argparse.Namespace) -> None:
    """Handle 'sase xprompt graph'."""
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


def _handle_catalog(args: argparse.Namespace) -> None:
    """Handle 'sase xprompt catalog'."""
    import json
    from pathlib import Path

    from sase.xprompt.catalog import (
        NoXpromptsFound,
        PdfEngineUnavailable,
        build_xprompts_catalog,
    )

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None

    try:
        artifact = build_xprompts_catalog(output_dir=out_dir)
    except NoXpromptsFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except PdfEngineUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(3)

    stats = artifact.stats
    stats_blob = {
        "total": stats.total,
        "by_source": stats.by_source,
        "by_project": stats.by_project,
        "by_tag": stats.by_tag,
        "with_description": stats.with_description,
        "with_inputs": stats.with_inputs,
        "skills": stats.skills,
        "generated_at": stats.generated_at.isoformat(),
    }
    print(str(artifact.pdf_path))
    print(json.dumps(stats_blob), file=sys.stderr)
    sys.exit(0)


def _handle_explain(args: argparse.Namespace) -> None:
    """Handle 'sase xprompt explain'."""
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
