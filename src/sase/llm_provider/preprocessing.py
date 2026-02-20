"""Prompt preprocessing pipeline.

Extracts the preprocessing steps from the old GeminiCommandWrapper.invoke()
into a standalone function. The preprocessing functions themselves remain in
their original modules (xprompt, gemini_wrapper.file_references).
"""

import re
from dataclasses import dataclass, field

from sase.gemini_wrapper.file_references import (
    format_with_prettier,
    process_command_substitution,
    process_file_references,
    strip_html_comments,
)
from sase.xprompt import (
    is_jinja2_template,
    process_xprompt_references,
    render_toplevel_jinja2,
)
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


@dataclass
class _PreprocessResult:
    """Result of prompt preprocessing.

    Attributes:
        prompt: The fully preprocessed prompt text.
        directives: Parsed prompt directives extracted before preprocessing.
    """

    prompt: str
    directives: PromptDirectives = field(default_factory=PromptDirectives)


_FENCED_BLOCK_PLACEHOLDER = "\x00FENCED_BLOCK_{}\x00"
_FENCED_CODE_BLOCK_PATTERN = r"```[^\n]*\n[\s\S]*?```"


def _extract_fenced_code_blocks(text: str) -> tuple[str, list[str]]:
    """Extract fenced code blocks, replacing them with placeholders.

    Returns:
        A tuple of (text_with_placeholders, list_of_extracted_blocks).
    """
    blocks: list[str] = []

    def _save_block(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return _FENCED_BLOCK_PLACEHOLDER.format(len(blocks) - 1)

    text_with_placeholders = re.sub(_FENCED_CODE_BLOCK_PATTERN, _save_block, text)
    return text_with_placeholders, blocks


def _restore_fenced_code_blocks(text: str, blocks: list[str]) -> str:
    """Restore placeholders with original fenced code block content."""
    for i, block in enumerate(blocks):
        text = text.replace(_FENCED_BLOCK_PLACEHOLDER.format(i), block)
    return text


def preprocess_prompt(prompt: str, *, is_home_mode: bool = False) -> _PreprocessResult:
    """Apply the full preprocessing pipeline to a raw prompt.

    Steps:
        0. Extract ``%name`` prompt directives.
        1. Expand ``#name`` xprompt references.
        2. Expand ``$(cmd)`` command substitutions.
        3. Expand ``@path`` file references (copy absolute/tilde paths).
        4. Render Jinja2 templates (after all expansions).
        5. Format with prettier for consistent markdown.
        6. Strip HTML/markdown comments.

    Fenced code blocks (triple-backtick) are extracted before processing
    and restored afterward, so their content is never expanded.

    Args:
        prompt: The raw prompt text.
        is_home_mode: If True, skip file copying for ``@`` file references.

    Returns:
        A _PreprocessResult with the cleaned prompt and extracted directives.
    """
    # Extract fenced code blocks before any processing
    prompt, fenced_blocks = _extract_fenced_code_blocks(prompt)

    # 0. Extract prompt directives (%name patterns) before other processing
    prompt, directives = extract_prompt_directives(prompt)

    # 1. Process xprompt references (#name patterns)
    prompt = process_xprompt_references(prompt)

    # 2. Process command substitution ($(cmd) patterns)
    prompt = process_command_substitution(prompt)

    # 3. Process file references (@path patterns)
    prompt = process_file_references(prompt, is_home_mode=is_home_mode)

    # 4. Process Jinja2 templates AFTER all expansions
    if is_jinja2_template(prompt):
        prompt = render_toplevel_jinja2(prompt)

    # 5. Format with prettier for consistent markdown
    prompt = format_with_prettier(prompt)

    # 6. Strip HTML/markdown comments
    prompt = strip_html_comments(prompt)

    # Restore fenced code blocks after all processing
    prompt = _restore_fenced_code_blocks(prompt, fenced_blocks)

    return _PreprocessResult(prompt=prompt, directives=directives)
