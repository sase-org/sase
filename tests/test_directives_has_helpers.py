"""Tests for directive presence helpers (has_wait, has_model, has_alt)."""

from sase.xprompt.directives import (
    has_alt_directive,
    has_model_directive,
    has_tag_directive,
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


def test_has_wait_directive_duration() -> None:
    """has_wait_directive detects %wait:5m."""
    assert has_wait_directive("%wait:5m\nDo something") is True


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


# --- has_tag_directive tests ---


def test_has_tag_directive_colon() -> None:
    """Detects %tag:name syntax."""
    assert has_tag_directive("%tag:review\nDo something") is True


def test_has_tag_directive_alias_colon() -> None:
    """Detects %t:name shorthand."""
    assert has_tag_directive("Do something %t:review") is True


def test_has_tag_directive_paren() -> None:
    """Detects %tag(name) syntax."""
    assert has_tag_directive("Do something %tag(review)") is True


def test_has_tag_directive_absent() -> None:
    """Returns False when ordinary text mentions tag without a directive."""
    assert has_tag_directive("tag this after the launch") is False
    assert has_tag_directive("Do something %target:review") is False


def test_has_tag_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_tag_directive("Just a plain prompt") is False


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
