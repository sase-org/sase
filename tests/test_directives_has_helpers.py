"""Tests for directive presence helpers (has_wait, has_model, has_alt)."""

from collections.abc import Callable

import pytest

from sase.xprompt.directives import (
    has_alt_directive,
    has_deferred_start_directive,
    has_model_directive,
    has_wait_directive,
)


# --- has_wait_directive tests ---


def test_has_wait_directive_colon() -> None:
    """Detects %wait:name syntax."""
    assert has_wait_directive("Do something %wait:faster") is True


def test_has_wait_directive_alias() -> None:
    """Detects %w:name shorthand."""
    assert has_wait_directive("Do something %w:faster") is True


def test_has_wait_directive_paren() -> None:
    """Detects %wait(name) syntax."""
    assert has_wait_directive("Do something %wait(faster)") is True


def test_has_wait_directive_plus() -> None:
    """Detects %wait+ and %w+ syntax."""
    assert has_wait_directive("Do something %wait+") is True
    assert has_wait_directive("Do something %w+") is True


def test_has_wait_directive_start_of_line() -> None:
    """Detects %wait at start of line."""
    assert has_wait_directive("%wait:faster\nDo something") is True


def test_has_wait_directive_absent() -> None:
    """Returns False when no %wait directive present."""
    assert has_wait_directive("Do something %model:opus") is False


def test_has_wait_directive_bare() -> None:
    """Detects bare %wait (no argument)."""
    assert has_wait_directive("%wait\nDo something") is True
    assert has_wait_directive("Do something %wait") is True
    assert has_wait_directive("Do something %w\nmore") is True


def test_has_wait_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_wait_directive("Just a plain prompt") is False


def test_has_wait_directive_does_not_match_time() -> None:
    """has_wait_directive must not match %time/%t (scoped to %wait/%w only)."""
    assert has_wait_directive("%time:5m\nDo something") is False
    assert has_wait_directive("%t:5m\nDo something") is False


@pytest.mark.parametrize("directive", ["%wait:old_agent", "%w:old_agent"])
def test_has_wait_directive_ignores_fenced_blocks(directive: str) -> None:
    """Directive-looking text inside fences is not a live wait directive."""
    assert has_wait_directive(f"snapshot\n```text\n{directive}\n```\nDo work") is False


@pytest.mark.parametrize("directive", ["%wait:old_agent", "%w:old_agent"])
def test_has_wait_directive_ignores_disabled_regions(directive: str) -> None:
    """Directive-looking text inside disabled regions is not live."""
    prompt = f"%xprompts_enabled:false\n{directive}\n%xprompts_enabled:true\nDo work"
    assert has_wait_directive(prompt) is False


# --- has_deferred_start_directive tests ---


def test_has_deferred_start_directive_wait() -> None:
    """Matches %wait variants."""
    assert has_deferred_start_directive("%wait:agent\nDo something") is True
    assert has_deferred_start_directive("Do %w:agent more") is True
    assert has_deferred_start_directive("%wait\nDo something") is True


def test_has_deferred_start_directive_time() -> None:
    """Matches %time variants."""
    assert has_deferred_start_directive("%time:5m\nDo something") is True
    assert has_deferred_start_directive("%t:5m\nDo something") is True
    assert has_deferred_start_directive("Do %time(5m) more") is True


def test_has_deferred_start_directive_absent() -> None:
    """Returns False when no deferred-start directive present."""
    assert has_deferred_start_directive("Do something %model:opus") is False


def test_has_deferred_start_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_deferred_start_directive("Just a plain prompt") is False


@pytest.mark.parametrize(
    "directive",
    ["%wait:old_agent", "%w:old_agent", "%time:5m", "%t:5m"],
)
def test_has_deferred_start_directive_ignores_fenced_blocks(directive: str) -> None:
    """Deferred-start syntax inside fences does not defer launch."""
    prompt = f"snapshot\n```text\n{directive}\n```\nDo work"
    assert has_deferred_start_directive(prompt) is False


@pytest.mark.parametrize(
    "directive",
    ["%wait:old_agent", "%w:old_agent", "%time:5m", "%t:5m"],
)
def test_has_deferred_start_directive_ignores_disabled_regions(
    directive: str,
) -> None:
    """Deferred-start syntax inside disabled regions does not defer launch."""
    prompt = f"%xprompts_enabled:false\n{directive}\n%xprompts_enabled:true\nDo work"
    assert has_deferred_start_directive(prompt) is False


# --- has_model_directive tests ---


def test_has_model_directive_colon() -> None:
    """Detects %model:name syntax."""
    assert has_model_directive("%model:opus\nDo something") is True


def test_has_model_directive_alias_colon() -> None:
    """Detects %m:name shorthand."""
    assert has_model_directive("Do something %m:sonnet") is True


def test_has_model_directive_paren() -> None:
    """Detects %m(name) syntax."""
    assert has_model_directive("Do something %m(opus)") is True


def test_has_model_directive_absent() -> None:
    """Returns False when no %model directive present."""
    assert has_model_directive("Do something %wait:faster") is False


def test_has_model_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_model_directive("Just a plain prompt") is False


@pytest.mark.parametrize("directive", ["%model:opus", "%m:opus"])
def test_has_model_directive_ignores_fenced_blocks(directive: str) -> None:
    """Directive-looking text inside fences is not a live model directive."""
    assert has_model_directive(f"snapshot\n```text\n{directive}\n```\nDo work") is False


@pytest.mark.parametrize("directive", ["%model:opus", "%m:opus"])
def test_has_model_directive_ignores_disabled_regions(directive: str) -> None:
    """Directive-looking text inside disabled regions is not live."""
    prompt = f"%xprompts_enabled:false\n{directive}\n%xprompts_enabled:true\nDo work"
    assert has_model_directive(prompt) is False


# --- has_alt_directive tests ---


def test_has_alt_directive_present() -> None:
    """Detects %alt( syntax."""
    assert has_alt_directive("%alt(a,b)\nDo something") is True


def test_has_alt_directive_start_of_line() -> None:
    """Detects %alt at start of line."""
    assert has_alt_directive("Do work\n%alt(a,b)") is True


def test_has_alt_directive_after_space() -> None:
    """Detects %alt after whitespace."""
    assert has_alt_directive("Do something %alt(a,b)") is True


def test_has_alt_directive_absent() -> None:
    """Returns False when no %alt directive present."""
    assert has_alt_directive("Do something %model:opus") is False


def test_has_alt_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_alt_directive("Just a plain prompt") is False


def test_has_alt_directive_partial_no_paren() -> None:
    """Returns False for %alt without opening paren."""
    assert has_alt_directive("%alt:something") is False


def test_has_alt_directive_shorthand() -> None:
    """Detects %( shorthand syntax."""
    assert has_alt_directive("%(a,b)\nDo something") is True
    assert has_alt_directive("Do something %(a,b)") is True


def test_has_alt_directive_bare_percent_no_paren() -> None:
    """Returns False for % without ( (no regression)."""
    assert has_alt_directive("50% done") is False
    assert has_alt_directive("Use 100% of CPU") is False


@pytest.mark.parametrize("directive", ["%alt(a,b)", "%(a,b)"])
def test_has_alt_directive_ignores_fenced_blocks(directive: str) -> None:
    """Alt syntax inside fences is not a live alt directive."""
    assert has_alt_directive(f"snapshot\n```text\n{directive}\n```\nDo work") is False


@pytest.mark.parametrize("directive", ["%alt(a,b)", "%(a,b)"])
def test_has_alt_directive_ignores_disabled_regions(directive: str) -> None:
    """Alt syntax inside disabled regions is not live."""
    prompt = f"%xprompts_enabled:false\n{directive}\n%xprompts_enabled:true\nDo work"
    assert has_alt_directive(prompt) is False


@pytest.mark.parametrize(
    ("predicate", "directive"),
    [
        (has_wait_directive, "%wait:old_agent"),
        (has_wait_directive, "%w:old_agent"),
        (has_deferred_start_directive, "%time:5m"),
        (has_deferred_start_directive, "%t:5m"),
        (has_model_directive, "%model:opus"),
        (has_model_directive, "%m:opus"),
        (has_alt_directive, "%alt(a,b)"),
        (has_alt_directive, "%(a,b)"),
    ],
)
def test_has_directive_helpers_still_detect_top_level_directives(
    predicate: Callable[[str], bool],
    directive: str,
) -> None:
    """The protected scan keeps normal top-level directive behavior."""
    assert predicate(f"{directive}\nDo work") is True
