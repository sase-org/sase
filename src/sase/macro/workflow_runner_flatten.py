"""Anonymous workflow flattening and standalone reference resolution."""

import logging
import os
import warnings
from typing import TYPE_CHECKING

from ._parsing import (
    MacroReference,
    parse_workflow_reference,
)
from ._parsing_references import iter_macro_references
from ._workflow_runner_args import (
    WORKFLOW_HITL_OVERRIDE_ARG,
    WORKFLOW_MODEL_OVERRIDE_ARG,
)
from .loader import get_all_workflows
from .workflow_models import (
    WorkflowExecutionError,
    WorkflowValidationError,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .workflow_models import Workflow

__all__ = [
    "flatten_anonymous_workflow",
    "invalid_explicit_standalone_message",
    "is_workflow_reference",
    "standalone_deprecation_message",
]


def standalone_deprecation_message(name: str) -> str:
    return f"Standalone workflow '#{name}' is deprecated; use '#!{name}' instead."


def _warn_legacy_standalone_reference(name: str) -> None:
    msg = standalone_deprecation_message(name)
    logger.warning(msg)
    warnings.warn(msg, UserWarning, stacklevel=3)


def invalid_explicit_standalone_message(name: str) -> str:
    return (
        f"Only standalone workflows use '#!'; '{name}' has a prompt_part. "
        f"Use '#{name}' for inline or embeddable references."
    )


def _ambiguous_standalone_message(names: list[str]) -> str:
    refs = ", ".join(names)
    return (
        "Ambiguous standalone workflow references: "
        f"{refs}. Use exactly one standalone workflow reference."
    )


def is_workflow_reference(name: str) -> bool:
    """Check if a name refers to a workflow.

    Args:
        name: The macro/workflow name to check.

    Returns:
        True if the name matches a workflow, False otherwise.
    """
    workflows = get_all_workflows()
    return name in workflows


def _parse_standalone_ref(
    ref: MacroReference,
) -> tuple[list[str], dict[str, str]]:
    positional_args, named_args = ref.parse_arguments()
    if ref.hitl_override is not None:
        named_args = dict(named_args)
        named_args[WORKFLOW_HITL_OVERRIDE_ARG] = "1" if ref.hitl_override else "0"
    return positional_args, named_args


def _find_standalone_workflow_ref(
    prompt_text: str,
    prompts: "dict[str, Workflow]",
) -> "tuple[Workflow, list[str], dict[str, str]] | None":
    """Scan prompt text for exactly one standalone (no prompt_part) workflow ref.

    Used as a fallback when the fast-path single-reference check in
    ``flatten_anonymous_workflow`` fails. The prompt may contain multiple
    ``#name`` references — some macro parts, some workflows with
    ``prompt_part`` — but if exactly one is a pure multi-step workflow
    (no ``prompt_part``), return it with its parsed arguments.

    Args:
        prompt_text: The full prompt text to scan.
        prompts: The combined prompts dict (macros + workflows).

    Returns:
        Tuple of (workflow, positional_args, named_args) if exactly one
        standalone workflow was found, None otherwise.
    """
    from ._fenced_blocks import protect_fenced_blocks

    # Protect fenced code blocks so that references inside triple-backtick
    # blocks are not mistaken for real workflow references.
    fenced_blocks: list[str] = []
    protected_text = protect_fenced_blocks(prompt_text, fenced_blocks)

    explicit_refs: list[MacroReference] = []
    legacy_refs: list[MacroReference] = []
    for ref in iter_macro_references(protected_text):
        if ref.name not in prompts:
            continue
        referenced = prompts[ref.name]
        if ref.is_standalone_marker:
            if referenced.has_prompt_part():
                raise WorkflowValidationError(
                    invalid_explicit_standalone_message(ref.name)
                )
            explicit_refs.append(ref)
        elif not referenced.has_prompt_part():
            legacy_refs.append(ref)

    if explicit_refs:
        if len(explicit_refs) != 1:
            raise WorkflowValidationError(
                _ambiguous_standalone_message([ref.raw for ref in explicit_refs])
            )
        ref = explicit_refs[0]
        positional_args, named_args = _parse_standalone_ref(ref)
        return prompts[ref.name], positional_args, named_args

    if len(legacy_refs) > 1:
        raise WorkflowValidationError(
            _ambiguous_standalone_message([ref.raw for ref in legacy_refs])
        )
    if len(legacy_refs) != 1:
        return None

    ref = legacy_refs[0]
    _warn_legacy_standalone_reference(ref.name)
    positional_args, named_args = _parse_standalone_ref(ref)
    return prompts[ref.name], positional_args, named_args


def flatten_anonymous_workflow(
    workflow: "Workflow",
    project: str | None = None,
) -> "tuple[Workflow, list[str], dict[str, str]] | None":
    """Flatten an anonymous workflow that wraps a single workflow reference.

    If the anonymous workflow's single prompt step is entirely a ``#name(args)``
    reference to a pure multi-step workflow (one without a prompt_part), return
    that referenced workflow with the parsed args. Otherwise return None.

    Also handles the case where the prompt contains multiple references (e.g.,
    ``#gh:sase #!batch_split``) where some are macro parts and exactly one
    is a standalone workflow (no prompt_part). In that case, the standalone
    workflow is extracted and flattened.

    Args:
        workflow: The anonymous workflow to check.
        project: Optional project name for loading prompts.

    Returns:
        Tuple of (referenced_workflow, positional_args, named_args) if
        flattening is appropriate, None otherwise.
    """
    from .loader import get_all_prompts

    # Only flatten single-step agent workflows
    if len(workflow.steps) != 1 or not workflow.steps[0].is_agent_step():
        return None

    prompt_text = (workflow.steps[0].agent or "").strip()

    # Must contain at least one #reference
    if "#" not in prompt_text:
        return None

    # Extract directives from the wrapper prompt first so syntax like
    # "#split %model:..." can still flatten to #split while preserving
    # the user model override for nested workflow steps.
    from .directives import extract_prompt_directives

    prompt_text, wrapper_directives = extract_prompt_directives(prompt_text)
    prompt_text = prompt_text.strip()
    if not prompt_text.startswith("#"):
        return None

    prompts = get_all_prompts(project=project)
    logger.debug(
        "_flatten_anonymous_workflow: project=%r, cwd=%r, prompt=%r, "
        "prompt_keys_sample=%r, sase_prefix_keys=%r",
        project,
        os.getcwd(),
        prompt_text[:120],
        list(prompts.keys())[:20],
        [k for k in prompts if k.startswith("sase/")],
    )

    def _attach_wrapper_model(named: dict[str, str]) -> dict[str, str]:
        if not wrapper_directives.model:
            return named
        updated = dict(named)
        updated[WORKFLOW_MODEL_OVERRIDE_ARG] = wrapper_directives.model
        return updated

    # ── Fast path: entire prompt is a single #name/#!name reference ──
    refs = iter_macro_references(prompt_text)
    exact_ref = (
        refs[0]
        if len(refs) == 1 and refs[0].start == 0 and refs[0].end == len(prompt_text)
        else None
    )
    if exact_ref is not None:
        wf_name = exact_ref.name
        positional_args, named_args = _parse_standalone_ref(exact_ref)
    else:
        ref_text = prompt_text[1:]  # Strip leading # for legacy fallback behavior
        wf_name, positional_args, named_args = parse_workflow_reference(ref_text)

    if wf_name not in prompts:
        from sase.macro.local_trust import blocked_local_macro_message

        blocked = blocked_local_macro_message(wf_name, project=project)
        if blocked:
            raise WorkflowExecutionError(blocked)
    if wf_name in prompts:
        from sase.macro.local_trust import blocked_local_macro_message

        blocked = blocked_local_macro_message(
            wf_name,
            catalog_item=prompts[wf_name],
            project=project,
        )
        if blocked:
            raise WorkflowExecutionError(blocked)
        referenced = prompts[wf_name]
        if exact_ref is not None and exact_ref.is_standalone_marker:
            if referenced.has_prompt_part():
                raise WorkflowValidationError(
                    invalid_explicit_standalone_message(wf_name)
                )
            return referenced, positional_args, _attach_wrapper_model(named_args)

        # Only flatten pure multi-step workflows (no prompt_part)
        # Workflows with prompt_part are handled by embedded workflow expansion
        if referenced.has_prompt_part():
            # Rename so workflow_state.json shows the real workflow name
            # instead of the anonymous "tmp_*" name (e.g., "resume" not
            # "tmp_260223_115114"). But don't rename if the args contain
            # additional # references, indicating a multi-reference prompt
            # (e.g., "#gh:sase #bd/next ...") rather than a single workflow
            # reference.
            has_extra_refs = any("#" in arg for arg in positional_args)
            if has_extra_refs:
                # Multi-reference prompt — fall through to slow path which
                # scans for a standalone workflow among the references.
                pass
            else:
                # Also check: the prompt may contain a standalone workflow
                # reference beyond the first (e.g., "#gh:sase #!batch_split").
                # The fast path only parsed the first reference, so scan the
                # full prompt text for a standalone workflow to flatten to.
                standalone = _find_standalone_workflow_ref(prompt_text, prompts)
                if standalone is not None:
                    ref_wf, pos, named = standalone
                    return ref_wf, pos, _attach_wrapper_model(named)
                logger.warning(
                    "_flatten_anonymous_workflow: fast-path has_prompt_part branch "
                    "returning None (workflow NOT flattened). prompt=%r, "
                    "first_ref=%r (has_prompt_part=True), standalone_scan=no match, "
                    "sase_prefix_keys=%r, all_keys_count=%d",
                    prompt_text[:200],
                    wf_name,
                    [k for k in prompts if k.startswith("sase/")],
                    len(prompts),
                )
                workflow.name = wf_name
                return None
        else:
            if exact_ref is not None:
                _warn_legacy_standalone_reference(wf_name)
            return referenced, positional_args, _attach_wrapper_model(named_args)

    # ── Slow path: multiple references, extract standalone workflow ──
    # The prompt may mix macro parts (e.g., #gh:sase) with a single
    # standalone workflow (no prompt_part). Scan for exactly one standalone
    # workflow reference and flatten to it.
    logger.debug(
        "_flatten_anonymous_workflow: fast path miss for %r, trying slow path",
        wf_name,
    )
    standalone = _find_standalone_workflow_ref(prompt_text, prompts)
    if standalone is None:
        logger.debug(
            "_flatten_anonymous_workflow: no standalone ref found, returning None"
        )
        return None
    ref_wf, pos, named = standalone
    logger.debug("_flatten_anonymous_workflow: flattened to %r", ref_wf.name)
    return ref_wf, pos, _attach_wrapper_model(named)
