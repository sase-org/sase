"""Pure helper that decides whether a selected xprompt can be inline-expanded.

This is the ``Ctrl+I`` ("expand in place") decision logic for the ``#@``
selector, kept free of Textual so it can be unit-tested directly. Given the
selected catalog entry it either returns the fully expanded body text or a
user-facing error explaining why the entry cannot be expanded inline.

Inline expansion is a no-argument expansion: the user picks an entry and the
selector splices its rendered body into the originating prompt pane. Entries
that carry runtime side effects (standalone/embeddable workflows, environment)
cannot be rendered as plain text and are rejected so the caller can fall back
to inserting the ``#name`` reference. Simple xprompts with declared inputs are
expanded with placeholders preserved and returned to the caller for staging in
prompt frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from sase.xprompt._exceptions import XPromptError
from sase.xprompt.loader import get_all_xprompts
from sase.xprompt.models import InputArg, XPrompt, XPromptValidationError
from sase.xprompt.processor import (
    expand_single_xprompt,
    process_xprompt_references_with_catalog,
)
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowKind,
    WorkflowValidationError,
)


# pyvision: sdd/epics/202606/xprompt_expand_keymap.md
class InlineExpansionReason(Enum):
    """Classification of an inline-expansion outcome (handy for tests)."""

    EXPANDED = "expanded"
    STANDALONE_WORKFLOW = "standalone_workflow"
    WORKFLOW_STEPS = "workflow_steps"
    EXPANSION_ERROR = "expansion_error"


# pyvision: sdd/epics/202606/xprompt_expand_keymap.md
@dataclass(frozen=True, slots=True)
class InlineExpansionResult:
    """Outcome of attempting to inline-expand a selected xprompt entry.

    Exactly one of ``expanded_text`` / ``error`` is set: on success
    ``expanded_text`` holds the rendered body and ``error`` is ``None``; on
    failure ``error`` holds a user-facing message and ``expanded_text`` is
    ``None``. ``reason`` always describes the outcome.
    """

    expanded_text: str | None
    error: str | None
    reason: InlineExpansionReason
    inputs: list[InputArg] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when the entry expanded successfully."""
        return self.reason is InlineExpansionReason.EXPANDED


def expand_inline_xprompt(
    name: str,
    workflow: Workflow,
    *,
    local_xprompts: dict[str, XPrompt] | None = None,
    project: str | None = None,
) -> InlineExpansionResult:
    """Decide whether *workflow* can be inline-expanded and render it if so.

    Args:
        name: The selected catalog name (used only for messages/lookups).
        workflow: The selected catalog entry as a unified ``Workflow``.
        local_xprompts: Local xprompts from the live prompt frontmatter, made
            available as extra xprompts so a selected local helper (or a global
            xprompt that references one) expands the same way it would at
            launch.
        project: Optional project name used to load the recursive expansion
            catalog so nested references resolve with project parity.

    Returns:
        An :class:`InlineExpansionResult` carrying either the expanded body or
        a user-facing error message and a reason code.
    """
    local_xprompts = local_xprompts or {}

    # 1. Classify by xprompt reference semantics. Only simple, side-effect-free
    #    prompt-part entries can be rendered as inline text.
    kind = workflow.prompt_kind()
    if kind is WorkflowKind.STANDALONE_WORKFLOW:
        return _error(
            InlineExpansionReason.STANDALONE_WORKFLOW,
            f"Cannot inline-expand #!{name} because it is a workflow. "
            "Press Enter to insert the reference.",
        )
    if kind is WorkflowKind.EMBEDDABLE_WORKFLOW:
        return _error(
            InlineExpansionReason.WORKFLOW_STEPS,
            f"Cannot inline-expand #{name} because it has workflow steps.",
        )

    # ``kind is SIMPLE_XPROMPT``: a single prompt_part step with no pre/post
    # steps. Still reject any leftover runtime side effect such as workflow
    # environment variables, which cannot be applied during a text expansion.
    if workflow.environment:
        return _error(
            InlineExpansionReason.WORKFLOW_STEPS,
            f"Cannot inline-expand #{name} because it has workflow steps.",
        )

    # 2. Render the body by reusing the launch-time expansion primitives so the
    #    inline result matches what the same reference would produce at launch.
    xprompt = _workflow_to_xprompt(name, workflow)
    inputs = list(xprompt.inputs)
    identity_scope = _identity_input_scope(inputs)
    render_xprompt = replace(xprompt, inputs=[]) if inputs else xprompt
    try:
        rendered = expand_single_xprompt(
            render_xprompt,
            [],
            identity_scope,
            scope=identity_scope or None,
            preserve_segment_separators=True,
        )
        rendered = _expand_nested_references(
            rendered,
            local_xprompts=local_xprompts,
            project=project,
            scope=identity_scope or None,
        )
    except (XPromptError, XPromptValidationError, WorkflowValidationError) as exc:
        return _error(
            InlineExpansionReason.EXPANSION_ERROR,
            f"Cannot inline-expand #{name}: {exc}",
        )
    except SystemExit:
        # Legacy catalog expansion (``process_xprompt_references_with_catalog``)
        # calls ``sys.exit()`` on circular or otherwise invalid references
        # instead of raising. Convert that into a clean, recoverable error so a
        # bad reference never tears down the TUI.
        return _error(
            InlineExpansionReason.EXPANSION_ERROR,
            f"Cannot inline-expand #{name} because its expansion failed "
            "(possible circular or invalid reference).",
        )

    return InlineExpansionResult(
        expanded_text=rendered,
        error=None,
        reason=InlineExpansionReason.EXPANDED,
        inputs=inputs,
    )


def _error(reason: InlineExpansionReason, message: str) -> InlineExpansionResult:
    """Build a failed :class:`InlineExpansionResult`."""
    return InlineExpansionResult(expanded_text=None, error=message, reason=reason)


def _workflow_to_xprompt(name: str, workflow: Workflow) -> XPrompt:
    """Project a simple prompt-part workflow back into an ``XPrompt``.

    The inverse of :func:`sase.xprompt.models.xprompt_to_workflow`, scoped to
    the single prompt-part body so it can be rendered through the same helper
    as a hand-authored xprompt.
    """
    return XPrompt(
        name=name,
        content=workflow.get_prompt_part_content(),
        inputs=[inp for inp in workflow.inputs if not inp.is_step_input],
        source_path=workflow.source_path,
        tags=workflow.tags,
        description=workflow.description,
        local_xprompts=dict(workflow.xprompts),
    )


def _identity_input_scope(inputs: list[InputArg]) -> dict[str, str]:
    """Return values that render declared inputs back to ``{{ name }}``.

    Rendering through an inputs-cleared copy bypasses type conversion, so typed
    placeholders like ``int`` / ``bool`` can still round-trip as literal Jinja.
    The same identity values are passed as scope so local helpers and nested
    references that use a top-level input surface it into the final body for
    launch-time substitution.
    """
    return {inp.name: "{{ " + inp.name + " }}" for inp in inputs}


def _expand_nested_references(
    rendered: str,
    *,
    local_xprompts: dict[str, XPrompt],
    project: str | None,
    scope: dict[str, str] | None,
) -> str:
    """Recursively expand global/frontmatter references left in *rendered*.

    The first render pass (``expand_single_xprompt``) only resolves the entry's
    own local helpers. This pass resolves any remaining references against the
    global catalog plus the live frontmatter locals, matching launch behavior.
    """
    if "#" not in rendered:
        return rendered

    catalog: dict[str, XPrompt] = dict(get_all_xprompts(project))
    if local_xprompts:
        catalog.update(local_xprompts)

    return process_xprompt_references_with_catalog(
        rendered,
        catalog,
        extra_xprompts=local_xprompts or None,
        scope=scope,
        aliases_resolved=True,
        preserve_segment_separators=True,
    )


__all__ = [
    "InlineExpansionReason",
    "InlineExpansionResult",
    "expand_inline_xprompt",
]
