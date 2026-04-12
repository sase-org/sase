"""Prompt preprocessing pipeline.

Extracts the preprocessing steps from the old GeminiCommandWrapper.invoke()
into a standalone function. The preprocessing functions themselves remain in
their original modules (xprompt, gemini_wrapper.file_references).

The pipeline is split into early and late phases so callers (xprompt CLI,
invoke_agent, workflow executor) can insert logic between the two phases
(e.g. embedded workflow expansion) while sharing the same canonical steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.xprompt._trace import ExpansionTrace

from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives

# File reference processing mode:
#   "process" — expand @path refs (copy files, rewrite paths)
#   "validate" — check @path refs exist but don't modify the prompt
#   "skip" — ignore @path refs entirely
FileRefMode = Literal["process", "validate", "skip"]


@dataclass
class PreprocessResult:
    """Result of prompt preprocessing.

    Attributes:
        prompt: The preprocessed prompt text (after early phase).
        directives: Parsed prompt directives extracted during early phase.
    """

    prompt: str
    directives: PromptDirectives = field(default_factory=PromptDirectives)


# Keep the old name as an alias so existing internal references still work.
_PreprocessResult = PreprocessResult


def preprocess_prompt_early(
    prompt: str,
    *,
    extra_xprompts: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    trace: ExpansionTrace | None = None,
) -> PreprocessResult:
    """Early preprocessing phase: Jinja2 context, xprompt expansion, directives.

    Steps:
        1. Render Jinja2 with *context* dict (for workflow variables).
        2. Expand ``#name`` xprompt references.
        3. Extract ``%name`` prompt directives (after xprompt expansion so
           directives embedded in xprompts are also discovered).

    Args:
        prompt: The raw prompt text.
        extra_xprompts: Additional xprompts (workflow-defined) for expansion.
        scope: Variable scope for xprompt argument evaluation.
        context: Jinja2 template context dict.  When provided, the prompt is
            rendered as a Jinja2 template *before* xprompt expansion.
        trace: Optional ExpansionTrace to collect expansion records into.

    Returns:
        A PreprocessResult with the partially processed prompt and extracted
        directives.
    """
    from sase.xprompt import process_xprompt_references

    # 1. Optional Jinja2 rendering (workflow variables)
    if context is not None:
        from sase.xprompt.workflow_executor_utils import render_template

        fenced_blocks: list[str] = []
        prompt = protect_fenced_blocks(prompt, fenced_blocks)
        prompt = render_template(prompt, context)
        prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    # 2. Expand xprompt references
    prompt = process_xprompt_references(
        prompt, extra_xprompts=extra_xprompts, scope=scope, trace=trace
    )

    # 3. Directive extraction (after xprompt expansion so directives inside
    #    expanded xprompts are also discovered; fenced-block protection is
    #    built into extract_prompt_directives)
    prompt, directives = extract_prompt_directives(prompt)

    return PreprocessResult(prompt=prompt, directives=directives)


def preprocess_prompt_late(
    prompt: str,
    *,
    file_ref_mode: FileRefMode = "process",
    is_home_mode: bool = False,
) -> str:
    """Late preprocessing phase: command sub, file refs, Jinja2, prettier, HTML strip.

    Steps:
        1. Protect fenced code blocks.
        2. ``$(cmd)`` command substitution.
        3. ``@path`` file reference processing or validation.
        4. Top-level Jinja2 rendering.
        5. Prettier formatting.
        6. HTML comment stripping.
        7. Restore fenced code blocks.

    Args:
        prompt: The prompt text (output of early phase or embedded-workflow
            expansion).
        file_ref_mode: How to handle ``@path`` references.
        is_home_mode: If True, skip file copying for ``@`` file references.

    Returns:
        The fully preprocessed prompt text.
    """
    from sase.gemini_wrapper.file_references import (
        format_with_prettier,
        process_command_substitution,
        process_file_references,
        strip_html_comments,
        validate_file_references,
    )
    from sase.xprompt import is_jinja2_template, render_toplevel_jinja2

    # 0. Protect disabled regions (%xprompts_enabled:false/true pairs)
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    # 1. Protect fenced code blocks
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # 2. Command substitution
    prompt = process_command_substitution(prompt)

    # 3. File references
    if file_ref_mode == "process":
        prompt = process_file_references(prompt, is_home_mode=is_home_mode)
    elif file_ref_mode == "validate":
        validate_file_references(prompt)

    # 4. Top-level Jinja2
    if is_jinja2_template(prompt):
        prompt = render_toplevel_jinja2(prompt)

    # 5. Prettier formatting
    prompt = format_with_prettier(prompt)

    # 6. HTML comment stripping
    prompt = strip_html_comments(prompt)

    # 7. Restore fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    # 8. Restore disabled regions and strip markers
    prompt = unprotect_disabled_regions(prompt, disabled_regions)
    prompt = strip_disabled_region_markers(prompt)

    return prompt


def preprocess_prompt(prompt: str, *, is_home_mode: bool = False) -> PreprocessResult:
    """Apply the full preprocessing pipeline to a raw prompt.

    Composes :func:`preprocess_prompt_early` and :func:`preprocess_prompt_late`
    for callers that need the complete pipeline in one call (e.g. invoke_agent).

    Args:
        prompt: The raw prompt text.
        is_home_mode: If True, skip file copying for ``@`` file references.

    Returns:
        A PreprocessResult with the cleaned prompt and extracted directives.
    """
    early = preprocess_prompt_early(prompt)
    final_prompt = preprocess_prompt_late(early.prompt, is_home_mode=is_home_mode)
    return PreprocessResult(prompt=final_prompt, directives=early.directives)
