"""Extraction utilities for workflow validation.

Extracts template references, xprompt calls, and step content
for use by validation checks.
"""

import re
from dataclasses import dataclass

from sase.xprompt._parsing import find_matching_paren_for_args, parse_args
from sase.xprompt.models import UNSET, XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep

# Pattern to match xprompt references (based on processor.py, extended for templates)
# The colon-arg group adds \{\{[^}]*\}\} to handle Jinja2 template vars like {{ file_path }}
# and \{[^}]*\} for Python f-string placeholders like {path}; both stand in for runtime
# values so the validator counts them as a single positional arg.  Jinja `{{...}}` is
# listed first so it wins over the single-brace alternative.
_XPROMPT_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\}|[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-])|(\+))?"
)

# Pattern to find {{ ... }} and {% ... %} blocks (variable references)
_JINJA_BLOCK_PATTERN = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.DOTALL)

# Pattern to find dotted identifiers within a Jinja2 block
_IDENT_PATTERN = re.compile(r"\b([a-zA-Z_]\w*(?:\.\w+)*)\b")

# Jinja2 keywords that appear in {% %} blocks but are not variable references
_JINJA_KEYWORDS = frozenset(
    {
        "if",
        "elif",
        "else",
        "endif",
        "for",
        "endfor",
        "in",
        "set",
        "block",
        "endblock",
        "macro",
        "endmacro",
        "not",
        "and",
        "or",
        "is",
        "true",
        "false",
        "none",
    }
)


def extract_template_refs(content: str) -> list[str]:
    """Extract all dotted identifier references from ``{{ }}`` and ``{% %}`` blocks.

    Handles compound expressions like ``{{ a.valid and b.valid }}``
    by scanning each block for all dotted identifiers.  Jinja2 keywords
    (``if``, ``for``, ``not``, etc.) are excluded from ``{% %}`` results.

    Args:
        content: Template content string to scan.

    Returns:
        List of dotted identifier strings found in template blocks.
    """
    refs: list[str] = []
    for block_match in _JINJA_BLOCK_PATTERN.finditer(content):
        block_text = block_match.group(1) or block_match.group(2)
        is_statement = block_match.group(2) is not None
        for ident_match in _IDENT_PATTERN.finditer(block_text):
            ident = ident_match.group(1)
            if is_statement and ident in _JINJA_KEYWORDS:
                continue
            refs.append(ident)
    return refs


@dataclass
class _XPromptCall:
    """Parsed xprompt call from a template."""

    name: str
    positional_args: list[str]
    named_args: dict[str, str]
    raw_match: str


_FENCED_CODE_BLOCK_PATTERN = re.compile(r"(`{3,})[^\n]*\n[\s\S]*?\1")


def extract_xprompt_calls(content: str) -> list[_XPromptCall]:
    """Extract all xprompt references from template string.

    Fenced code blocks are stripped before scanning so that hashtag
    references inside triple-backtick blocks are not treated as xprompt
    calls.

    Args:
        content: The template content to scan.

    Returns:
        List of parsed xprompt calls.
    """
    # Strip fenced code blocks so their content is never matched
    content = _FENCED_CODE_BLOCK_PATTERN.sub("", content)

    calls: list[_XPromptCall] = []
    matches = list(re.finditer(_XPROMPT_PATTERN, content, re.MULTILINE))

    for match in matches:
        name = match.group(1)
        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        positional_args: list[str] = []
        named_args: dict[str, str] = {}
        raw_match = match.group(0)

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(content, paren_start)
            if paren_end is not None:
                paren_content = content[paren_start + 1 : paren_end]
                positional_args, named_args = parse_args(paren_content)
                raw_match = content[match.start() : paren_end + 1]
        elif colon_arg is not None:
            positional_args = colon_arg.split(",")
        elif plus_suffix is not None:
            positional_args = ["true"]

        calls.append(
            _XPromptCall(
                name=name,
                positional_args=positional_args,
                named_args=named_args,
                raw_match=raw_match,
            )
        )

    return calls


def validate_xprompt_call(
    call: _XPromptCall,
    xprompt: XPrompt,
    step_name: str,
) -> list[str]:
    """Validate call arguments against xprompt definition.

    Args:
        call: The parsed xprompt call.
        xprompt: The xprompt definition to validate against.
        step_name: Name of the step containing the call (for error messages).

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    # Check positional arg count
    if len(call.positional_args) > len(xprompt.inputs):
        errors.append(
            f"Step '{step_name}': #{call.name} has {len(call.positional_args)} "
            f"positional args but only {len(xprompt.inputs)} inputs defined"
        )

    # Check named args match defined input names
    defined_names = {inp.name for inp in xprompt.inputs}
    for arg_name in call.named_args:
        if arg_name not in defined_names:
            available = sorted(defined_names)
            errors.append(
                f"Step '{step_name}': #{call.name} has no input named '{arg_name}'. "
                f"Available: {available}"
            )

    # Check required args are provided
    # Build set of provided arg names
    provided_names: set[str] = set(call.named_args.keys())

    # Positional args map to inputs by position
    for i, _ in enumerate(call.positional_args):
        if i < len(xprompt.inputs):
            provided_names.add(xprompt.inputs[i].name)

    # Find missing required args (those without defaults)
    missing_required: list[str] = []
    for inp in xprompt.inputs:
        if inp.default is UNSET and inp.name not in provided_names:
            # Skip check if a template variable could provide it at runtime
            # (but we still report it since we can't be sure)
            missing_required.append(inp.name)

    if missing_required:
        errors.append(
            f"Step '{step_name}': #{call.name} missing required args: {missing_required}"
        )

    return errors


def collect_step_content(step: WorkflowStep) -> list[str]:
    """Collect all template content from a step.

    Args:
        step: The workflow step to scan.

    Returns:
        List of content strings that may contain template references.
    """
    contents: list[str] = []

    if step.agent:
        contents.append(step.agent)
    if step.bash:
        contents.append(step.bash)
    if step.python:
        contents.append(step.python)
    if step.prompt_part:
        contents.append(step.prompt_part)
    if step.condition:
        contents.append(step.condition)
    if step.for_loop:
        for value in step.for_loop.values():
            contents.append(value)
    if step.repeat_config:
        contents.append(step.repeat_config.condition)
    if step.while_config:
        contents.append(step.while_config.condition)
    if step.parallel_config:
        for nested_step in step.parallel_config.steps:
            contents.extend(collect_step_content(nested_step))

    return contents


def collect_used_variables(workflow: Workflow) -> set[str]:
    """Collect all variable names referenced in workflow templates.

    Args:
        workflow: The workflow to scan.

    Returns:
        Set of variable names referenced in templates.
    """
    used_vars: set[str] = set()

    for step in workflow.steps:
        for content in collect_step_content(step):
            for ref in extract_template_refs(content):
                var_name = ref.split(".")[0]
                # Skip special variables like 'item' from for-loops
                if var_name not in ("item", "loop"):
                    used_vars.add(var_name)

    return used_vars
