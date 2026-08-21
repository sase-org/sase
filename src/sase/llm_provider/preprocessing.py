"""Prompt preprocessing pipeline.

A standalone pipeline that runs the shared preprocessing steps. The
preprocessing functions themselves remain in their original modules
(xprompt, file_references).

The pipeline is split into early and late phases so callers (xprompt CLI,
invoke_agent, workflow executor) can insert logic between the two phases
(e.g. embedded workflow expansion) while sharing the same canonical steps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.artifact_ref_prompt_context import PromptRefContext
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
        segment_vcs_refs: Each top-level segment's own ``#git``/``#gh`` VCS
            tag (or ``None``), captured before embedded-workflow expansion
            can consume it.
    """

    prompt: str
    directives: PromptDirectives = field(default_factory=PromptDirectives)
    segment_vcs_refs: tuple[str | None, ...] = ()


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
        3. Extract ``%id`` prompt directives (after xprompt expansion so
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
        disabled_regions: list[str] = []
        prompt = protect_disabled_regions(prompt, disabled_regions)
        prompt = render_template(prompt, context)
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt = canonicalize_project_aliases_in_prompt(prompt)

    # 2. Expand xprompt references
    prompt = process_xprompt_references(
        prompt, extra_xprompts=extra_xprompts, scope=scope, trace=trace
    )

    # 3. Directive extraction (after xprompt expansion so directives inside
    #    expanded xprompts are also discovered; fenced-block protection is
    #    built into extract_prompt_directives). Preserve disabled region
    #    markers so preprocess_prompt_late can still protect their contents
    #    from command substitution and file-reference validation.
    prompt, directives = extract_prompt_directives(prompt, strip_disabled_markers=False)

    from sase.artifact_ref_prompt_context import prompt_segment_vcs_refs

    return PreprocessResult(
        prompt=prompt,
        directives=directives,
        segment_vcs_refs=prompt_segment_vcs_refs(prompt),
    )


def preprocess_prompt_late(
    prompt: str,
    *,
    file_ref_mode: FileRefMode = "process",
    is_home_mode: bool = False,
    ref_contexts: Sequence[PromptRefContext] | None = None,
    materialize_missing_roots: bool = False,
) -> str:
    """Late preprocessing phase: command sub, artifact/file refs, Jinja2, formatting.

    Steps:
        1. Protect fenced code blocks.
        2. ``$(cmd)`` command substitution.
        3. ``@kind:payload`` artifact reference expansion or validation into
           portable prose (and, for explicit custom path-bound formats, path
           tokens).
        4. Ordinary authored ``@path`` file reference processing or validation.
        5. Top-level Jinja2 rendering.
        6. Prettier formatting.
        7. HTML comment stripping.
        8. Restore fenced code blocks.

    Args:
        prompt: The prompt text (output of early phase or embedded-workflow
            expansion).
        file_ref_mode: How to handle ``@path`` references.
        is_home_mode: If True, skip file copying for ``@`` file references.
        ref_contexts: Per-segment builtin artifact-ref resolution contexts,
            usually built from :attr:`PreprocessResult.segment_vcs_refs`.
            Each candidate still prefers its own segment's live VCS tag over
            this sequence; see ``artifact_ref_prompt``'s resolution order.
        materialize_missing_roots: If True, clone missing document sidecar
            roots cited by artifact refs before resolving them.

    Returns:
        The fully preprocessed prompt text.
    """
    from sase.file_references import (
        format_agent_prompt_markdown,
        process_command_substitution,
        process_file_references,
        strip_html_comments,
        validate_file_references,
    )
    from sase.artifact_refs import (
        ArtifactRendererJinjaProtection,
        process_artifact_references,
        validate_artifact_references,
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

    # 3. Artifact references first. Built-in expansions are portable prose and
    #    are not re-parsed as ``@path`` tokens; staged_artifact_paths still
    #    suppresses explicit custom path-bound formats that emit ``@path``.
    staged_artifact_paths: set[str] = set()
    artifact_jinja_protection = ArtifactRendererJinjaProtection()
    if file_ref_mode == "process":
        prompt = process_artifact_references(
            prompt,
            is_home_mode=is_home_mode,
            ref_contexts=ref_contexts,
            staged_file_paths=staged_artifact_paths,
            jinja_protection=artifact_jinja_protection,
            materialize_missing_roots=materialize_missing_roots,
        )
    elif file_ref_mode == "validate":
        validate_artifact_references(
            prompt, is_home_mode=is_home_mode, ref_contexts=ref_contexts
        )

    # 4. File references
    if file_ref_mode == "process":
        prompt = process_file_references(
            prompt,
            is_home_mode=is_home_mode,
            staged_file_paths=staged_artifact_paths,
        )
    elif file_ref_mode == "validate":
        validate_file_references(prompt)

    # 5. Top-level Jinja2
    if is_jinja2_template(prompt):
        prompt = render_toplevel_jinja2(prompt)
    prompt = artifact_jinja_protection.unprotect(prompt)

    # 6. Prettier formatting (shared agent-prompt Markdown policy)
    prompt = format_agent_prompt_markdown(prompt)

    # 7. HTML comment stripping
    prompt = strip_html_comments(prompt)

    # 8. Restore fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    # 9. Restore disabled regions and strip markers
    prompt = unprotect_disabled_regions(prompt, disabled_regions)
    prompt = strip_disabled_region_markers(prompt)

    return prompt


def preprocess_prompt(
    prompt: str,
    *,
    is_home_mode: bool = False,
    materialize_missing_roots: bool = False,
) -> PreprocessResult:
    """Apply the full preprocessing pipeline to a raw prompt.

    Composes :func:`preprocess_prompt_early` and :func:`preprocess_prompt_late`
    for callers that need the complete pipeline in one call (e.g. invoke_agent).

    Args:
        prompt: The raw prompt text.
        is_home_mode: If True, skip file copying for ``@`` file references.
        materialize_missing_roots: If True, clone missing document sidecar
            roots cited by artifact refs before resolving them.

    Returns:
        A PreprocessResult with the cleaned prompt and extracted directives.
    """
    early = preprocess_prompt_early(prompt)

    from sase.artifact_ref_prompt_context import (
        prompt_ref_contexts_for_segment_vcs_refs,
    )

    ref_contexts = prompt_ref_contexts_for_segment_vcs_refs(
        early.segment_vcs_refs, is_home_mode=is_home_mode
    )
    final_prompt = preprocess_prompt_late(
        early.prompt,
        is_home_mode=is_home_mode,
        ref_contexts=ref_contexts,
        materialize_missing_roots=materialize_missing_roots,
    )
    return PreprocessResult(prompt=final_prompt, directives=early.directives)
