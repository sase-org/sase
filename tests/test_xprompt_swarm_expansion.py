"""Tests for xprompt swarm expansion."""

from __future__ import annotations

import pytest

from sase.agent.xprompt_swarm import (
    _XpromptSwarmUsageError,
    expand_xprompt_swarms_with_metadata,
)
from sase.xprompt.models import InputArg, InputType

from tests._xprompt_swarm_helpers import (
    expand_xprompt_swarms,
    patch_catalog,
    xp,
)


def test_plain_segment_metadata_has_empty_swarm_chain() -> None:
    out = expand_xprompt_swarms_with_metadata(["plain segment"])

    assert [record.prompt for record in out] == ["plain segment"]
    assert [record.template_group for record in out] == [None]
    assert [record.swarm_xprompts for record in out] == [()]


def test_expand_single_segment_xprompt_unchanged() -> None:
    """Xprompt with no separators in body → segments untouched."""
    catalog = {"single": xp("single", "just one body")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#single"])
    assert out == ["#single"]


def test_bang_single_segment_xprompt_invalid() -> None:
    """Ordinary xprompts remain embeddable and cannot use the standalone marker."""
    catalog = {"single": xp("single", "just one body")}
    with patch_catalog(catalog):
        with pytest.raises(_XpromptSwarmUsageError, match=r"Use `#single`"):
            expand_xprompt_swarms(["#!single"])


def test_expand_three_segment_xprompt() -> None:
    """Xprompt body with 3 segments → 3 sub-segments after expansion."""
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!three"])
    assert out == ["phase A", "phase B", "phase C"]


def test_expand_three_segment_xprompt_metadata_groups_one_invocation() -> None:
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms_with_metadata(["#!three"])

    assert [record.prompt for record in out] == ["phase A", "phase B", "phase C"]
    assert [record.template_group for record in out] == [
        "xprompt:three:0",
        "xprompt:three:0",
        "xprompt:three:0",
    ]
    assert [record.swarm_xprompts for record in out] == [
        ("three",),
        ("three",),
        ("three",),
    ]


def test_expand_two_xprompt_invocations_get_distinct_metadata_groups() -> None:
    catalog = {"two": xp("two", "phase A\n---\nphase B")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms_with_metadata(["#!two", "#!two"])

    assert [record.prompt for record in out] == [
        "phase A",
        "phase B",
        "phase A",
        "phase B",
    ]
    assert [record.template_group for record in out] == [
        "xprompt:two:0",
        "xprompt:two:0",
        "xprompt:two:1",
        "xprompt:two:1",
    ]


def test_bare_xprompt_swarm_expands_as_sole_segment() -> None:
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#three"])
    assert out == ["phase A", "phase B", "phase C"]


def test_bang_xprompt_swarm_remains_accepted_for_compatibility() -> None:
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        bare = expand_xprompt_swarms(["#three"])
        bang = expand_xprompt_swarms(["#!three"])
    assert bang == bare


def test_expand_with_positional_args() -> None:
    """Args propagate into every segment via Jinja2 substitution."""
    catalog = {
        "three": xp(
            "three",
            "Plan for {{ feature }}.\n---\nImplement {{ feature }}.\n---\nTest {{ feature }}.",
            inputs=[InputArg(name="feature", type=InputType.LINE)],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!three(login bug fix)"])
    assert out == [
        "Plan for login bug fix.",
        "Implement login bug fix.",
        "Test login bug fix.",
    ]


def test_expand_with_colon_arg_decodes_plus_space_substitution() -> None:
    catalog = {
        "two": xp(
            "two",
            "Plan {{ root }}.\n---\nUse {{ root }}.",
            inputs=[InputArg(name="root", type=InputType.PATH)],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(
            ["#!two:/Users/me/Library/Application+Support/sase"]
        )
    assert out == [
        "Plan /Users/me/Library/Application Support/sase.",
        "Use /Users/me/Library/Application Support/sase.",
    ]


def test_expand_with_named_args() -> None:
    catalog = {
        "two": xp(
            "two",
            "Run with {{ x }} and {{ y }}\n---\n{{ x }}/{{ y }} done",
            inputs=[
                InputArg(name="x", type=InputType.LINE),
                InputArg(name="y", type=InputType.LINE),
            ],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!two(x=A, y=B)"])
    assert out == ["Run with A and B", "A/B done"]


def test_expand_jinja_in_body() -> None:
    """Jinja2 expressions in an xprompt swarm body resolve once across segments."""
    body = (
        "{% if include_plan %}Plan first.{% endif %}\n"
        "---\n"
        "Implement {{ feature }}.\n"
        "---\n"
        "Test {{ feature }}."
    )
    catalog = {
        "loop": xp(
            "loop",
            body,
            inputs=[
                InputArg(name="feature", type=InputType.LINE),
                InputArg(name="include_plan", type=InputType.BOOL),
            ],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!loop(login, include_plan=true)"])
    assert len(out) == 3
    assert out[0] == "Plan first."
    assert out[1] == "Implement login."
    assert out[2] == "Test login."


def test_expand_mixed_with_prose_embeds_first_segment() -> None:
    """Xprompt swarm referenced mid-prose embeds its first sub-prompt."""
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms_with_metadata(["Hello #three world"])
    assert [record.prompt for record in out] == ["Hello a world", "b", "c"]
    assert [record.template_group for record in out] == [
        "xprompt:three:0",
        "xprompt:three:0",
        "xprompt:three:0",
    ]
    assert [record.swarm_xprompts for record in out] == [
        ("three",),
        ("three",),
        ("three",),
    ]


def test_expand_inline_with_shorthand_args() -> None:
    catalog = {
        "three": xp(
            "three",
            "Plan {{ feature }}\n---\nBuild {{ feature }}\n---\nTest {{ feature }}",
            inputs=[InputArg(name="feature", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#three:: login flow"])
    assert out == ["Plan login flow", "Build login flow", "Test login flow"]


def test_expand_inline_with_shorthand_args_preserves_parentheses() -> None:
    catalog = {
        "three": xp(
            "three",
            "Plan {{ feature }}\n---\nBuild {{ feature }}\n---\nTest {{ feature }}",
            inputs=[InputArg(name="feature", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#three:: login flow (oauth)"])
    assert out == [
        "Plan login flow (oauth)",
        "Build login flow (oauth)",
        "Test login flow (oauth)",
    ]


def test_expand_research_swarm_style_shorthand_preserves_parentheses() -> None:
    catalog = {
        "research_swarm": xp(
            "research_swarm",
            "{{ prompt }} #research\n---\n"
            "%w #fork #research/more %m:opus\n---\n"
            "%w #fork #research/image",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#research_swarm:: find foo (bar)"])
    assert out == [
        "find foo (bar) #research",
        "%w #fork #research/more %m:opus",
        "%w #fork #research/image",
    ]
