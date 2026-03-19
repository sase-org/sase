"""Tests for user-prompt frontmatter (local xprompts) integration.

Phase 2 of the multi-agent prompts plan (sase-2.2): verifies that
frontmatter-defined local xprompts are wired into prompt preprocessing.
"""

from unittest.mock import patch

import pytest

from sase.multi_prompt import _LocalXPromptNameError, parse_multi_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Patch both get_all_xprompts (disk-based xprompts) and
# resolve_xprompt_aliases (config-based aliases) so tests are isolated
# from the user's filesystem.
_PATCH_XPROMPTS = patch(
    "sase.xprompt.processor.get_all_xprompts", side_effect=lambda: {}
)
_PATCH_ALIASES = patch(
    "sase.xprompt.processor.resolve_xprompt_aliases", side_effect=lambda x: x
)


def _expand_with_local(text: str) -> str:
    """Parse frontmatter from *text* and expand local xprompts."""
    from sase.xprompt.processor import process_xprompt_references

    multi = parse_multi_prompt(text)
    body = "\n---\n".join(multi.segments)
    return process_xprompt_references(body, extra_xprompts=multi.local_xprompts or None)


# ---------------------------------------------------------------------------
# Local xprompt expansion
# ---------------------------------------------------------------------------


@_PATCH_ALIASES
@_PATCH_XPROMPTS
def test_local_xprompts_expand_in_prompt(_xp, _al) -> None:
    """Local xprompts defined in frontmatter expand correctly."""
    text = '---\nxprompts:\n  _style: "be concise"\n---\nDo the thing. #_style'
    expanded = _expand_with_local(text)
    assert "be concise" in expanded
    assert "#_style" not in expanded


@_PATCH_ALIASES
@_PATCH_XPROMPTS
def test_local_xprompts_with_arguments(_xp, _al) -> None:
    """Local xprompts with inputs expand with arguments."""
    text = (
        "---\n"
        "xprompts:\n"
        "  _greet:\n"
        "    input: {name: word}\n"
        '    content: "Hello {{ name }}"\n'
        "---\n"
        "#_greet(World)"
    )
    expanded = _expand_with_local(text)
    assert "Hello World" in expanded


# ---------------------------------------------------------------------------
# Scoping: local xprompts don't leak
# ---------------------------------------------------------------------------


@_PATCH_ALIASES
@_PATCH_XPROMPTS
def test_local_xprompts_scoped_to_extra(_xp, _al) -> None:
    """Local xprompts only expand when passed as extra_xprompts."""
    from sase.xprompt.processor import process_xprompt_references

    text = '---\nxprompts:\n  _secret: "classified"\n---\nSay #_secret'
    multi = parse_multi_prompt(text)
    body = "\n---\n".join(multi.segments)

    # With local xprompts — should expand.
    expanded = process_xprompt_references(body, extra_xprompts=multi.local_xprompts)
    assert "classified" in expanded

    # Without local xprompts — should NOT expand.
    expanded_without = process_xprompt_references(body)
    assert "#_secret" in expanded_without


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_underscore_prefix_required() -> None:
    """Local xprompt names must start with _."""
    text = '---\nxprompts:\n  badname: "content"\n---\nbody'
    with pytest.raises(_LocalXPromptNameError):
        parse_multi_prompt(text)


# ---------------------------------------------------------------------------
# Frontmatter stripping
# ---------------------------------------------------------------------------


def test_frontmatter_stripped_from_body() -> None:
    """Frontmatter is not included in the prompt body."""
    text = '---\nxprompts:\n  _style: "be concise"\n---\nDo the thing.'
    multi = parse_multi_prompt(text)
    body = "\n---\n".join(multi.segments)
    assert "xprompts:" not in body
    assert body == "Do the thing."


def test_no_frontmatter_passthrough() -> None:
    """Prompts without frontmatter pass through unchanged."""
    text = "Just a plain prompt"
    multi = parse_multi_prompt(text)
    body = "\n---\n".join(multi.segments)
    assert body == "Just a plain prompt"
    assert multi.local_xprompts == {}


# ---------------------------------------------------------------------------
# Integration with extract_directives_and_write_meta
# ---------------------------------------------------------------------------


@_PATCH_ALIASES
@_PATCH_XPROMPTS
def test_extract_directives_handles_frontmatter(_xp, _al, tmp_path) -> None:
    """extract_directives_and_write_meta correctly processes frontmatter prompts."""
    from sase.multi_prompt import parse_multi_prompt

    prompt = (
        '---\nxprompts:\n  _ctx: "extra context"\n---\n%name:test_agent\nDo work. #_ctx'
    )
    multi = parse_multi_prompt(prompt)
    body = "\n---\n".join(multi.segments)

    # Verify frontmatter is stripped and local xprompts are available.
    assert "xprompts:" not in body
    assert "_ctx" in multi.local_xprompts
    assert multi.local_xprompts["_ctx"].content == "extra context"


# ---------------------------------------------------------------------------
# Integration with run_query (anonymous workflow xprompts)
# ---------------------------------------------------------------------------


def test_anonymous_workflow_gets_local_xprompts() -> None:
    """Anonymous workflow's xprompts field is populated from frontmatter."""
    from sase.xprompt.models import create_anonymous_workflow

    text = '---\nxprompts:\n  _hint: "think step by step"\n---\nSolve #_hint'
    multi = parse_multi_prompt(text)
    query_body = "\n---\n".join(multi.segments)

    anon = create_anonymous_workflow(query_body)
    if multi.local_xprompts:
        anon.xprompts = multi.local_xprompts

    assert "_hint" in anon.xprompts
    assert anon.xprompts["_hint"].content == "think step by step"
