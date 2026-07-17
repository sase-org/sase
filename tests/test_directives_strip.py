"""Tests for the side-effect-free strip_known_directives() helper."""

from sase.xprompt.directives import strip_known_directives


def test_no_directives_passthrough() -> None:
    """Text without % is returned unchanged."""
    text = "Just a normal prompt with no directives"
    assert strip_known_directives(text) == text


def test_strips_known_directives_colon_and_plus() -> None:
    """Known directives (colon, plus, alias) are removed; prose stays.

    Whitespace cleanup is intentionally not this helper's job (the resume
    sanitizer tidies), so we compare after stripping.
    """
    text = "%name:foo %wait:bar %t:research %auto Do the thing"
    result = strip_known_directives(text)
    assert "%" not in result
    assert result.strip() == "Do the thing"


def test_strips_paren_argument_form() -> None:
    """Paren-argument directives are removed including their parens."""
    text = "%model(claude) Review this"
    result = strip_known_directives(text)
    assert "%model" not in result
    assert "claude" not in result
    assert result.strip() == "Review this"


def test_strips_family_directive_and_alias() -> None:
    text = "%family(root, role=phase) %f:root Do the thing"

    result = strip_known_directives(text)

    assert "%family" not in result
    assert "%f" not in result
    assert result.strip() == "Do the thing"


def test_unknown_directive_preserved() -> None:
    """Unknown %name tokens are left untouched."""
    text = "%unknown:value stays"
    assert strip_known_directives(text) == text


def test_removed_group_directive_preserved() -> None:
    """Removed group spellings are no longer known directives."""
    text = "%group:research %g:research stays"
    assert strip_known_directives(text) == text


def test_removed_auto_approve_directive_preserved() -> None:
    """Removed auto-approve spellings are no longer known directives."""
    text = "%approve stays"
    assert strip_known_directives(text) == text


def test_deprecated_time_directive_stripped_for_history_cleanup() -> None:
    """Deprecated %time remains strippable from historical prompt text."""
    text = "%time:5m Do the thing"
    result = strip_known_directives(text)
    assert "%time" not in result
    assert result.strip() == "Do the thing"


def test_duplicate_directives_do_not_raise() -> None:
    """Duplicate non-multi directives are stripped without raising."""
    # extract_prompt_directives would raise DirectiveError here.
    text = "%name:a %name:b content"
    result = strip_known_directives(text)
    assert "%name" not in result
    assert result.strip() == "content"


def test_bare_name_does_not_allocate() -> None:
    """Bare %name is stripped without allocating an auto-name."""
    # If this allocated a name it would hit sase.agent.names; it must not.
    text = "%name content here"
    result = strip_known_directives(text)
    assert "%name" not in result
    assert result.strip() == "content here"


def test_fenced_directives_preserved() -> None:
    """Directives inside fenced code blocks are preserved."""
    text = "Example:\n\n```\n%name:foo\n%wait:bar\n```\n\nDone"
    result = strip_known_directives(text)
    assert "%name:foo" in result
    assert "%wait:bar" in result
    assert "Done" in result


def test_idempotent() -> None:
    """Sanitizing already-clean text is a no-op."""
    text = "%name:foo Do the thing"
    once = strip_known_directives(text)
    assert strip_known_directives(once) == once
