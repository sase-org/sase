"""Handler for the 'sase macro' command."""

import argparse
import sys

from sase.macro.models import UNSET, InputArg


def handle_macro_command(args: argparse.Namespace) -> None:
    """Handle the 'sase macro' command."""
    subcommand = getattr(args, "macro_subcommand", None)
    if subcommand is None:
        # Narrowed-parser compat: ``create_parser(only="xprompt")`` still
        # parses into the retired dest.
        subcommand = getattr(args, "xprompt_subcommand", None)

    if subcommand == "expand":
        _handle_expand(args)
    elif subcommand == "explain":
        _handle_explain(args)
    elif subcommand == "graph":
        _handle_graph(args)
    elif subcommand == "list":
        _handle_list()
    elif subcommand == "show":
        _handle_show(args)
    elif subcommand == "catalog":
        _handle_catalog(args)
    else:
        print("Usage: sase macro {catalog,expand,explain,graph,list,show}")
        sys.exit(1)


def _handle_expand(args: argparse.Namespace) -> None:
    """Handle 'sase macro expand'."""
    from sase.llm_provider.preprocessing import (
        preprocess_prompt_early,
        preprocess_prompt_late,
    )
    from sase.macro._trace import ExpansionTrace, print_trace

    from sase.main.query_handler import expand_embedded_workflows_in_query
    from sase.agent.multi_prompt import parse_multi_prompt

    prompt = args.prompt if args.prompt else sys.stdin.read()

    # Parse frontmatter for local macro definitions so that
    # references like #_docs:telegram are expanded correctly.
    multi = parse_multi_prompt(prompt)
    local_macros = multi.local_macros or None
    prompt_body = "\n---\n".join(multi.segments)
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt_body = canonicalize_project_aliases_in_prompt(prompt_body)

    trace = ExpansionTrace() if args.trace else None
    early = preprocess_prompt_early(prompt_body, extra_macros=local_macros, trace=trace)
    expanded, _post_workflows = expand_embedded_workflows_in_query(early.prompt)

    from sase.artifact_ref_prompt_context import (
        prompt_ref_contexts_for_segment_vcs_refs,
    )

    ref_contexts = prompt_ref_contexts_for_segment_vcs_refs(
        early.segment_vcs_refs, is_home_mode=False
    )
    processed = preprocess_prompt_late(
        expanded, file_ref_mode="validate", ref_contexts=ref_contexts
    )
    print(processed, end="")
    from sase.macro.unresolved import (
        find_unresolved_reference_names,
        format_unresolved_reference_warning,
    )

    for name in find_unresolved_reference_names(
        processed,
        extra_macros=local_macros,
    ):
        print(format_unresolved_reference_warning(name), file=sys.stderr)
    if trace is not None:
        print_trace(trace)
    sys.exit(0)


def _handle_list() -> None:
    """Handle 'sase macro list'."""
    import json

    from sase.macro.loader import (
        get_all_prompts,
        get_all_workflows,
        get_all_macros,
    )
    from sase.macro.load_issues import collect_macro_load_issues
    from sase.macro.reference_display import (
        workflow_kind_value,
        workflow_reference_insertion,
        workflow_reference_prefix,
    )
    from sase.macro.workflow_step_display import workflow_step_type_label

    with collect_macro_load_issues() as load_issues:
        prompts = get_all_prompts()
        macros = get_all_macros()
        workflow_names = set(get_all_workflows())
    items = []
    for name, wf in sorted(prompts.items()):
        is_simple = wf.is_simple_macro()
        skill_macro = (
            macros[name] if name in macros and name not in workflow_names else None
        )
        user_inputs = [inp for inp in wf.inputs if not inp.is_step_input]
        inputs_json = []
        for inp in user_inputs:
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
                    "description": inp.description,
                }
            )
        if is_simple:
            preview = wf.get_prompt_part_content()
        else:
            lines: list[str] = [f"# Workflow: {name}", ""]
            if wf.description:
                lines.extend([wf.description, ""])
            if user_inputs:
                lines.append("## Inputs")
                for inp in user_inputs:
                    default_str = _macro_list_default_suffix(inp)
                    description_str = f" - {inp.description}" if inp.description else ""
                    lines.append(
                        f"- {inp.name}: {inp.type.value}{default_str}{description_str}"
                    )
                lines.append("")
            lines.append("## Steps")
            for i, step in enumerate(wf.steps, 1):
                stype, label = workflow_step_type_label(step)
                lines.append(f"{i}. [{stype}] {step.name}: {label}")
            preview = "\n".join(lines)
        items.append(
            {
                "name": name,
                "type": "macro" if is_simple else "workflow",
                "kind": workflow_kind_value(wf),
                "prefix": workflow_reference_prefix(wf),
                "insertion": workflow_reference_insertion(name, wf),
                "memory_type": wf.memory_type,
                "is_skill": bool(skill_macro and skill_macro.skill),
                # The provider-visible ``/`` name; ``name`` above stays the
                # ``#skill/<name>`` macro reference.
                "skill_name": skill_macro.skill_name if skill_macro else None,
                "description": wf.description,
                "source": wf.source_path,
                "inputs": inputs_json,
                "tags": [t.value for t in wf.tags],
                "preview": preview,
            }
        )
    print(json.dumps(items))
    for issue in load_issues:
        print(f"skipped: {issue.source}: {issue.error}", file=sys.stderr)
    sys.exit(0)


def _macro_list_default_suffix(inp: InputArg) -> str:
    """Return a stable default suffix for list-preview input rows."""
    if inp.default is UNSET:
        return ""
    if inp.default is None:
        return " (default: null)"
    return f" (default: {inp.default})"


def _handle_graph(args: argparse.Namespace) -> None:
    """Handle 'sase macro graph'."""
    from sase.macro.graph import (
        list_workflows,
        workflow_to_mermaid,
        workflow_to_text,
    )
    from sase.macro.workflow_loader import get_all_workflows

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
    """Handle 'sase macro catalog'."""
    import json
    from pathlib import Path

    from sase.macro.catalog import (
        NoMacrosFound,
        PdfEngineUnavailable,
        build_macros_catalog,
    )

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None

    try:
        artifact = build_macros_catalog(output_dir=out_dir)
    except NoMacrosFound as exc:
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
        "memory": stats.memory,
        "generated_at": stats.generated_at.isoformat(),
    }
    print(str(artifact.pdf_path))
    print(json.dumps(stats_blob), file=sys.stderr)
    sys.exit(0)


def _handle_show(args: argparse.Namespace) -> None:
    """Handle 'sase macro show'."""
    from sase.macro.cli_show import handle_show

    sys.exit(handle_show(args))


def _handle_explain(args: argparse.Namespace) -> None:
    """Handle 'sase macro explain'."""
    from sase.macro.explain import explain_workflow
    from sase.macro.loader import get_all_prompts

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
