"""Tests for xprompt snippet bridge conversion logic."""

from unittest.mock import patch

from sase.xprompt.models import UNSET, InputArg, XPrompt
from sase.xprompt.snippet_bridge import (
    _xprompt_to_snippet_template,
    get_xprompt_snippets,
)


def _make_xp(
    content: str,
    inputs: list[InputArg] | None = None,
    snippet: str | bool | None = True,
    name: str = "test",
) -> XPrompt:
    return XPrompt(
        name=name,
        content=content,
        inputs=inputs or [],
        snippet=snippet,
    )


# --- _xprompt_to_snippet_template ---


def test_plain_content_no_inputs() -> None:
    """Xprompt with no inputs and no Jinja2 → content + $0."""
    xp = _make_xp("Hello world")
    assert _xprompt_to_snippet_template(xp) == "Hello world$0"


def test_single_required_input() -> None:
    xp = _make_xp(
        "Hello {{ name }}!",
        inputs=[InputArg(name="name", default=UNSET)],
    )
    assert _xprompt_to_snippet_template(xp) == "Hello $1!$0"


def test_multiple_required_inputs() -> None:
    xp = _make_xp(
        "{{ greeting }} {{ name }}!",
        inputs=[
            InputArg(name="greeting", default=UNSET),
            InputArg(name="name", default=UNSET),
        ],
    )
    assert _xprompt_to_snippet_template(xp) == "$1 $2!$0"


def test_input_with_default_prefilled() -> None:
    xp = _make_xp(
        "Count: {{ count }}",
        inputs=[InputArg(name="count", default=5)],
    )
    assert _xprompt_to_snippet_template(xp) == "Count: 5$0"


def test_mixed_required_and_defaulted() -> None:
    xp = _make_xp(
        "{{ name }} has {{ count }} items",
        inputs=[
            InputArg(name="name", default=UNSET),
            InputArg(name="count", default=0),
        ],
    )
    assert _xprompt_to_snippet_template(xp) == "$1 has 0 items$0"


def test_none_default_becomes_empty() -> None:
    xp = _make_xp(
        "Val: {{ x }}",
        inputs=[InputArg(name="x", default=None)],
    )
    assert _xprompt_to_snippet_template(xp) == "Val: $0"


def test_bail_on_jinja2_control() -> None:
    xp = _make_xp("{% if x %}yes{% endif %}")
    assert _xprompt_to_snippet_template(xp) is None


def test_bail_on_jinja2_comment() -> None:
    xp = _make_xp("{# comment #}Hello")
    assert _xprompt_to_snippet_template(xp) is None


def test_bail_on_computed_expression() -> None:
    xp = _make_xp(
        "{{ count + 1 }}",
        inputs=[InputArg(name="count", default=UNSET)],
    )
    assert _xprompt_to_snippet_template(xp) is None


def test_legacy_placeholder_numeric() -> None:
    xp = _make_xp("Hello {1}, welcome to {2}!")
    assert _xprompt_to_snippet_template(xp) == "Hello $1, welcome to $2!$0"


def test_legacy_placeholder_with_default() -> None:
    xp = _make_xp("Hello {1:world}!")
    assert _xprompt_to_snippet_template(xp) == "Hello world!$0"


def test_repeated_input_reference() -> None:
    xp = _make_xp(
        "{{ name }} says hi, {{ name }}!",
        inputs=[InputArg(name="name", default=UNSET)],
    )
    assert _xprompt_to_snippet_template(xp) == "$1 says hi, $1!$0"


def test_only_defaulted_inputs() -> None:
    """All inputs have defaults → no tabstops, just $0."""
    xp = _make_xp(
        "{{ a }} and {{ b }}",
        inputs=[
            InputArg(name="a", default="x"),
            InputArg(name="b", default="y"),
        ],
    )
    assert _xprompt_to_snippet_template(xp) == "x and y$0"


def test_tabstop_numbering_skips_defaulted() -> None:
    """Tabstop numbers only assigned to required inputs."""
    xp = _make_xp(
        "{{ a }} {{ b }} {{ c }}",
        inputs=[
            InputArg(name="a", default=UNSET),
            InputArg(name="b", default="mid"),
            InputArg(name="c", default=UNSET),
        ],
    )
    assert _xprompt_to_snippet_template(xp) == "$1 mid $2$0"


# --- get_xprompt_snippets composition ---


def test_get_xprompt_snippets_composes_nested_xprompt_reference() -> None:
    xprompts = {
        "baz": _make_xp(
            "Don't forget to review bazbuz first!",
            name="baz",
            snippet=True,
        ),
        "foo": _make_xp(
            "Can you help me foobar? #baz",
            name="foo",
            snippet=True,
        ),
    }

    with (
        patch("sase.config.load_merged_config", return_value={}),
        patch("sase.xprompt.loader.get_all_xprompts", return_value=xprompts),
    ):
        snippets = get_xprompt_snippets()

    assert snippets["foo"] == (
        "Can you help me foobar? Don't forget to review bazbuz first!$0"
    )


def test_get_xprompt_snippets_composes_non_snippet_reference() -> None:
    xprompts = {
        "baz": _make_xp("Nested content", name="baz", snippet=None),
        "foo": _make_xp("Outer #baz", name="foo", snippet=True),
    }

    with (
        patch("sase.config.load_merged_config", return_value={}),
        patch("sase.xprompt.loader.get_all_xprompts", return_value=xprompts),
    ):
        snippets = get_xprompt_snippets()

    assert snippets == {"foo": "Outer Nested content$0"}


def test_get_xprompt_snippets_composes_multiple_nested_levels() -> None:
    xprompts = {
        "baz": _make_xp("baz", name="baz", snippet=None),
        "bar": _make_xp("bar #baz", name="bar", snippet=None),
        "foo": _make_xp("foo #bar", name="foo", snippet=True),
    }

    with (
        patch("sase.config.load_merged_config", return_value={}),
        patch("sase.xprompt.loader.get_all_xprompts", return_value=xprompts),
    ):
        snippets = get_xprompt_snippets()

    assert snippets == {"foo": "foo bar baz$0"}


def test_get_xprompt_snippets_leaves_unknown_nested_references_literal() -> None:
    xprompts = {
        "foo": _make_xp("Outer #missing", name="foo", snippet=True),
    }

    with (
        patch("sase.config.load_merged_config", return_value={}),
        patch("sase.xprompt.loader.get_all_xprompts", return_value=xprompts),
    ):
        snippets = get_xprompt_snippets()

    assert snippets == {"foo": "Outer #missing$0"}
