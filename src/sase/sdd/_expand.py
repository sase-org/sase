"""Prompt expansion helpers for SDD prompt snapshots."""

import logging

_logger = logging.getLogger(__name__)


def expand_prompt_for_spec(prompt: str) -> str:
    """Expand xprompt references and strip directives for prompt storage.

    Performs a "dry" expansion: xprompts are resolved, directives are stripped,
    and embedded workflow ``prompt_part`` content is inlined, but no pre/post
    steps are executed.
    """
    from sase.llm_provider.preprocessing import preprocess_prompt_early

    result = preprocess_prompt_early(prompt)
    expanded = result.prompt
    return dry_expand_embedded_workflows(expanded)


def dry_expand_embedded_workflows(prompt: str) -> str:
    """Replace embedded workflow references with rendered prompt_part content.

    Explicit standalone workflow references (``#!name`` for workflows without a
    ``prompt_part`` step) are preserved as compact markers for spec storage.
    Legacy inline standalone references (``#name``) are rejected so prompt
    snapshots do not capture ambiguous syntax.
    """
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import (
        iter_xprompt_references,
        normalize_vcs_underscore_refs,
    )
    from sase.xprompt.loader import get_all_workflows
    from sase.xprompt.input_binding import bind_input_args
    from sase.xprompt.workflow_executor_steps_embedded_types import (
        format_inline_workflow_reference_error,
        parse_workflow_reference_args,
    )
    from sase.xprompt.workflow_executor_utils import render_template

    workflows = get_all_workflows()

    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)
    prompt = normalize_vcs_underscore_refs(prompt)

    refs = iter_xprompt_references(prompt)
    replacements: list[tuple[int, int, str]] = []

    for ref in refs:
        name = ref.name
        if name not in workflows:
            continue

        workflow = workflows[name]

        if not workflow.has_prompt_part():
            if ref.is_standalone_marker:
                continue
            raise ValueError(
                format_inline_workflow_reference_error(
                    name=name,
                    raw=ref.raw,
                    has_prompt_part=False,
                )
            )

        if ref.is_standalone_marker:
            raise ValueError(
                format_inline_workflow_reference_error(
                    name=name,
                    raw=ref.raw,
                    has_prompt_part=True,
                )
            )

        positional_args, named_args = parse_workflow_reference_args(ref)
        args = bind_input_args(workflow.inputs, positional_args, named_args).values

        prompt_part_content = workflow.get_prompt_part_content()
        if prompt_part_content:
            try:
                prompt_part_content = render_template(prompt_part_content, args)
            except Exception:
                _logger.debug(
                    "Failed to render prompt_part for workflow %r, leaving as-is",
                    name,
                )
                continue

        replacements.append((ref.start, ref.end, prompt_part_content))

    for start, end, replacement in sorted(
        replacements, key=lambda r: r[0], reverse=True
    ):
        prompt = prompt[:start] + replacement + prompt[end:]

    return unprotect_fenced_blocks(prompt, fenced_blocks)
