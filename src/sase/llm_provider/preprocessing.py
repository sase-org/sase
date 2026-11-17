"""Prompt preprocessing pipeline.

A standalone pipeline that runs the shared preprocessing steps. The
preprocessing functions themselves remain in their original modules
(macro, file_references).

The pipeline is split into early and late phases so callers (macro CLI,
invoke_agent, workflow executor) can insert logic between the two phases
(e.g. embedded workflow expansion) while sharing the same canonical steps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.continuation_capture import ContinuationSegmentCapture
    from sase.artifact_ref_prompt_context import PromptRefContext
    from sase.macro._trace import ExpansionTrace

from sase.macro._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from sase.macro._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    PromptTextKind,
    execute_eligible_commands,
    resolve_provenance,
)
from sase.macro.directives import PromptDirectives, extract_prompt_directives
from sase.macro.source_render import render_source_template

# File reference processing mode:
#   "process" — expand @path refs (copy files, rewrite paths)
#   "validate" — check @path refs exist but don't modify the prompt
#   "skip" — ignore @path refs entirely
FileRefMode = Literal["process", "validate", "skip"]


def _default_result_provenance() -> CmdsubProvenance:
    """Fail-closed provenance for directly constructed results."""
    return CmdsubProvenance(kind=PromptTextKind.GENERATED, launch_authorship="agent")


@dataclass
class PreprocessResult:
    """Result of prompt preprocessing.

    Attributes:
        prompt: The preprocessed prompt text (after early phase).
        directives: Parsed prompt directives extracted during early phase.
        segment_vcs_refs: Each top-level segment's own ``#git``/``#gh`` VCS
            tag (or ``None``), captured before embedded-workflow expansion
            can consume it.
        continuation_segments: Provenance-aware local prompt fragments captured
            before transcript rendering so continuation replay never recovers
            structure from Markdown delimiters.
        provenance: Provenance of :attr:`prompt`. Early-phase output is
            rendered text (``GENERATED`` kind), so feeding it back into an
            early boundary with this provenance executes nothing.
    """

    prompt: str
    directives: PromptDirectives = field(default_factory=PromptDirectives)
    segment_vcs_refs: tuple[str | None, ...] = ()
    continuation_segments: tuple[ContinuationSegmentCapture, ...] = ()
    provenance: CmdsubProvenance = field(default_factory=_default_result_provenance)


# Keep the old name as an alias so existing internal references still work.
_PreprocessResult = PreprocessResult


def preprocess_prompt_early(
    prompt: str,
    *,
    extra_macros: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    trace: ExpansionTrace | None = None,
    provenance: CmdsubProvenance | None = None,
) -> PreprocessResult:
    """Early preprocessing phase: source commands, Jinja2, macros, directives.

    Steps:
        1. Resolve launch authorship (the source boundary). Only source-kind
           text in a human launch executes ``$(cmd)``; generated text and
           agent launches render and expand without executing.
        2. Render Jinja2 with *context* dict (for workflow variables).
           Context values are data: Jinja sees the original typed values,
           and interpolated spans are hidden from every execution pass.
           Without *context*, bare source commands still execute here.
        3. Expand ``#name`` macro references.
        4. Extract ``%id`` prompt directives (after macro expansion so
           directives embedded in macros are also discovered).

    Args:
        prompt: The raw prompt text (authorized source).
        extra_macros: Additional macros (workflow-defined) for expansion.
        scope: Variable scope for macro argument evaluation.
        context: Jinja2 template context dict.  When provided, the prompt is
            rendered as a Jinja2 template *before* macro expansion.
        trace: Optional ExpansionTrace to collect expansion records into.
        provenance: Explicit input provenance. ``None`` presents the prompt
            as human source with launch-stamp authorship.

    Returns:
        A PreprocessResult with the partially processed prompt, extracted
        directives, and ``GENERATED``-kind output provenance.
    """
    from sase.macro import process_macro_references

    authored_prompt = prompt
    provenance_in = resolve_provenance(provenance)
    guard = GeneratedTextGuard()
    trace_start_index = len(trace.records) if trace is not None else 0
    if trace is None:
        from sase.macro._trace import ExpansionTrace

        trace = ExpansionTrace()

    # 1/2. Source-aware Jinja2 rendering (workflow variables) or bare
    # source-command execution. Literal commands from authorized source
    # execute here; interpolated data never reaches an execution pass.
    if context is not None:
        prompt = render_source_template(
            prompt, context, provenance=provenance_in, guard=guard
        )
    else:
        prompt = execute_eligible_commands(
            prompt, provenance=provenance_in, guard=guard
        )

    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt = canonicalize_project_aliases_in_prompt(prompt)

    # 3. Expand macro references
    prompt = process_macro_references(
        prompt,
        extra_macros=extra_macros,
        scope=scope,
        trace=trace,
        cmdsub_provenance=provenance_in,
        cmdsub_guard=guard,
    )
    # The macro entry points unwrap what they expanded, but prompts without
    # references return through a fast path: unwrap here so generated spans
    # hidden for the source boundary never leak into the result.
    prompt = guard.unwrap(prompt)

    # 3. Directive extraction (after macro expansion so directives inside
    #    expanded macros are also discovered; fenced-block protection is
    #    built into extract_prompt_directives). Preserve disabled region
    #    markers so preprocess_prompt_late can still protect their contents
    #    from command substitution and file-reference validation.
    directive_disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, directive_disabled_regions)
    prompt, directives = extract_prompt_directives(prompt, strip_disabled_markers=False)
    prompt = unprotect_disabled_regions(prompt, directive_disabled_regions)

    from sase.artifact_ref_prompt_context import prompt_segment_vcs_refs
    from sase.continuation_capture import (
        local_authored_prompt_segment,
        macro_trace_segments,
    )

    return PreprocessResult(
        prompt=prompt,
        directives=directives,
        segment_vcs_refs=prompt_segment_vcs_refs(prompt),
        continuation_segments=(
            local_authored_prompt_segment(authored_prompt),
            *macro_trace_segments(trace, start_index=trace_start_index),
        ),
        provenance=CmdsubProvenance(
            kind=PromptTextKind.GENERATED,
            launch_authorship=provenance_in.launch_authorship,
        ),
    )


def preprocess_prompt_late(
    prompt: str,
    *,
    file_ref_mode: FileRefMode = "process",
    is_home_mode: bool = False,
    ref_contexts: Sequence[PromptRefContext] | None = None,
    materialize_missing_roots: bool = False,
    provenance: CmdsubProvenance | None = None,
) -> str:
    """Late preprocessing phase: artifact/file refs, Jinja2, formatting.

    Command substitution never runs here. Authored ``$(cmd)`` expressions
    execute exactly once at the early-phase source boundary; this phase's
    input is rendered text, so scanning it again would execute generated
    data. The remaining steps treat all prompts identically, so this phase
    takes no authorship input: provenance travels explicitly on workflow
    routes (sase-1tc.1.1.3), never as a late-phase switch.

    Steps:
        1. Protect disabled regions and fenced code blocks.
        2. ``@kind:payload`` artifact reference expansion or validation into
           portable prose (and, for explicit custom path-bound formats, path
           tokens).
        3. Ordinary authored ``@path`` file reference processing or validation.
        4. Top-level Jinja2 rendering.
        5. Literal-preserving agent-prompt formatting.
        6. HTML comment stripping.
        7. Restore fenced code blocks and disabled regions.

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
        provenance: Explicit provenance of *prompt*, carried for the
            ordinary :func:`preprocess_prompt` composition. It never enables
            execution here.

    Returns:
        The fully preprocessed prompt text.
    """
    from sase.file_references import (
        format_agent_prompt_markdown,
        process_file_references,
        strip_html_comments,
        validate_file_references,
    )
    from sase.artifact_refs import (
        ArtifactRendererJinjaProtection,
        process_artifact_references,
        validate_artifact_references,
    )
    from sase.macro import is_jinja2_template, render_toplevel_jinja2

    # NOTE: provenance is intentionally unused: no late input may enable
    # command substitution.

    # 0. Protect disabled regions (%macros_enabled:false/true pairs)
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    # 1. Protect fenced code blocks
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # 2. Artifact references first. Built-in expansions are portable prose and
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

    # 3. File references
    if file_ref_mode == "process":
        prompt = process_file_references(
            prompt,
            is_home_mode=is_home_mode,
            staged_file_paths=staged_artifact_paths,
        )
    elif file_ref_mode == "validate":
        validate_file_references(prompt)

    # 4. Top-level Jinja2
    if is_jinja2_template(prompt):
        prompt = render_toplevel_jinja2(prompt)
    prompt = artifact_jinja_protection.unprotect(prompt)

    # 5. Literal-preserving agent-prompt formatting
    prompt = format_agent_prompt_markdown(prompt)

    # 6. HTML comment stripping
    prompt = strip_html_comments(prompt)

    # 7. Restore fenced code blocks and disabled regions
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)
    prompt = unprotect_disabled_regions(prompt, disabled_regions)
    prompt = strip_disabled_region_markers(prompt)

    return prompt


def preprocess_prompt(
    prompt: str,
    *,
    is_home_mode: bool = False,
    materialize_missing_roots: bool = False,
    provenance: CmdsubProvenance | None = None,
) -> PreprocessResult:
    """Apply the full preprocessing pipeline to a raw prompt.

    Composes :func:`preprocess_prompt_early` and :func:`preprocess_prompt_late`
    for callers that need the complete pipeline in one call (e.g. invoke_agent).

    Args:
        prompt: The raw prompt text.
        is_home_mode: If True, skip file copying for ``@`` file references.
        materialize_missing_roots: If True, clone missing document sidecar
            roots cited by artifact refs before resolving them.
        provenance: Explicit input provenance for the early phase.
            ``None`` presents the prompt as human source with launch-stamp
            authorship. Command substitution is governed by *provenance* at
            the early source boundary; the late phase takes no authorship.

    Returns:
        A PreprocessResult with the cleaned prompt, extracted directives,
        and ``GENERATED``-kind output provenance.
    """
    early = preprocess_prompt_early(prompt, provenance=provenance)

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
        provenance=early.provenance,
    )
    return PreprocessResult(
        prompt=final_prompt,
        directives=early.directives,
        segment_vcs_refs=early.segment_vcs_refs,
        continuation_segments=early.continuation_segments,
        provenance=early.provenance,
    )
