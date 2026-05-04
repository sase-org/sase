"""Tests for multi-agent xprompt expansion at dispatch time."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.multi_agent_xprompt import (
    MultiAgentXPromptDepthError,
    MultiAgentXPromptUsageError,
    expand_multi_agent_xprompts,
    extract_top_level_xprompt_reference,
    xprompt_has_segment_separators,
)
from sase.xprompt.models import InputArg, InputType, XPrompt


def _xp(name: str, content: str, *, inputs: list[InputArg] | None = None) -> XPrompt:
    return XPrompt(name=name, content=content, inputs=inputs or [])


def _patch_catalog(catalog: dict[str, XPrompt]):
    """Patch ``get_all_xprompts`` in both the helper and the inline expander."""
    return patch(
        "sase.agent.multi_agent_xprompt.get_all_xprompts", return_value=catalog
    )


def _patch_vcs_patterns():
    return patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value={
            "gh": re.compile(r"#gh(?::([^\s]+)|\(([^)]*)\))"),
            "git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))"),
        },
    )


# --- xprompt_has_segment_separators ---


def test_has_separators_simple() -> None:
    assert xprompt_has_segment_separators(_xp("x", "a\n---\nb")) is True


def test_has_separators_none() -> None:
    assert xprompt_has_segment_separators(_xp("x", "just one segment")) is False


def test_has_separators_inside_fence_ignored() -> None:
    body = "before\n```\ncode\n---\nmore\n```\nafter"
    assert xprompt_has_segment_separators(_xp("x", body)) is False


# --- extract_top_level_xprompt_reference ---


def test_extract_simple_reference() -> None:
    call = extract_top_level_xprompt_reference("#foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.marker.value == "#"
    assert call.positional_args == []


def test_extract_standalone_reference() -> None:
    call = extract_top_level_xprompt_reference("#!foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.marker.value == "#!"


def test_extract_with_args() -> None:
    call = extract_top_level_xprompt_reference("#!foo(a, b)", {"foo"})
    assert call is not None
    assert call.positional_args == ["a", "b"]


def test_extract_with_named_args() -> None:
    call = extract_top_level_xprompt_reference("#foo(name=val)", {"foo"})
    assert call is not None
    assert call.named_args == {"name": "val"}


def test_extract_with_leading_directives() -> None:
    call = extract_top_level_xprompt_reference("%name:custom\n%wait\n#foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.leading_directives == ["%name:custom", "%wait"]


def test_extract_returns_none_for_prose() -> None:
    assert extract_top_level_xprompt_reference("Hello #foo and stuff", {"foo"}) is None


def test_extract_returns_none_for_trailing_prose() -> None:
    assert extract_top_level_xprompt_reference("#foo and stuff", {"foo"}) is None


def test_extract_returns_none_when_name_unknown() -> None:
    assert extract_top_level_xprompt_reference("#foo", {"bar"}) is None


def test_extract_colon_arg() -> None:
    call = extract_top_level_xprompt_reference("#foo:hello", {"foo"})
    assert call is not None
    assert call.positional_args == ["hello"]


def test_extract_with_leading_vcs_ref() -> None:
    with _patch_vcs_patterns():
        call = extract_top_level_xprompt_reference("#gh:sase #!foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.leading_vcs_ref_text == "#gh:sase"


# --- expand_multi_agent_xprompts ---


def test_expand_single_segment_xprompt_unchanged() -> None:
    """Xprompt with no separators in body → segments untouched."""
    catalog = {"single": _xp("single", "just one body")}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#single"])
    assert out == ["#single"]


def test_bang_single_segment_xprompt_invalid() -> None:
    """Ordinary xprompts remain embeddable and cannot use the standalone marker."""
    catalog = {"single": _xp("single", "just one body")}
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"Use '#single'"):
            expand_multi_agent_xprompts(["#!single"])


def test_expand_three_segment_xprompt() -> None:
    """Xprompt body with 3 segments → 3 sub-segments after expansion."""
    catalog = {"three": _xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!three"])
    assert out == ["phase A", "phase B", "phase C"]


def test_bare_multi_agent_xprompt_requires_bang() -> None:
    catalog = {"three": _xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!three"):
            expand_multi_agent_xprompts(["#three"])


def test_expand_with_positional_args() -> None:
    """Args propagate into every segment via Jinja2 substitution."""
    catalog = {
        "three": _xp(
            "three",
            "Plan for {{ feature }}.\n---\nImplement {{ feature }}.\n---\nTest {{ feature }}.",
            inputs=[InputArg(name="feature", type=InputType.LINE)],
        )
    }
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!three(login bug fix)"])
    assert out == [
        "Plan for login bug fix.",
        "Implement login bug fix.",
        "Test login bug fix.",
    ]


def test_expand_with_named_args() -> None:
    catalog = {
        "two": _xp(
            "two",
            "Run with {{ x }} and {{ y }}\n---\n{{ x }}/{{ y }} done",
            inputs=[
                InputArg(name="x", type=InputType.LINE),
                InputArg(name="y", type=InputType.LINE),
            ],
        )
    }
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!two(x=A, y=B)"])
    assert out == ["Run with A and B", "A/B done"]


def test_expand_jinja_in_body() -> None:
    """Jinja2 expressions in a multi-agent body resolve once across segments."""
    body = (
        "{% if include_plan %}Plan first.{% endif %}\n"
        "---\n"
        "Implement {{ feature }}.\n"
        "---\n"
        "Test {{ feature }}."
    )
    catalog = {
        "loop": _xp(
            "loop",
            body,
            inputs=[
                InputArg(name="feature", type=InputType.LINE),
                InputArg(name="include_plan", type=InputType.BOOL),
            ],
        )
    }
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!loop(login, include_plan=true)"])
    assert len(out) == 3
    assert out[0] == "Plan first."
    assert out[1] == "Implement login."
    assert out[2] == "Test login."


def test_expand_mixed_with_prose_raises() -> None:
    """Multi-agent xprompt referenced mid-prose → MultiAgentXPromptUsageError."""
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!three"):
            expand_multi_agent_xprompts(["Hello #three(arg) world"])


def test_expand_inline_ordinary_xprompt_inside_other_xprompt_body_no_resplit() -> None:
    """If ordinary #b appears inline inside #a's body, no re-split.

    The inner xprompt reference survives as text in one of the outer's segments
    and gets passed through unchanged — the agent runner expands it later.
    """
    catalog = {
        "outer": _xp("outer", "first\n---\nprose with #inner here\n---\nthird"),
        "inner": _xp("inner", "x"),
    }
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert len(out) == 3
    assert out[0] == "first"
    assert "#inner" in out[1]
    assert out[2] == "third"


def test_expand_inline_multi_agent_inside_other_xprompt_body_requires_bang() -> None:
    """A real inline reference to a multi-agent xprompt is rejected recursively."""
    catalog = {
        "outer": _xp("outer", "first\n---\nprose with #inner here\n---\nthird"),
        "inner": _xp("inner", "x\n---\ny"),
    }
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!inner"):
            expand_multi_agent_xprompts(["#!outer"])


def test_expand_recursive_standalone_reference() -> None:
    """Multi-agent xprompt that references another multi-agent xprompt as a sole segment."""
    catalog = {
        "outer": _xp("outer", "before\n---\n#!inner\n---\nafter"),
        "inner": _xp("inner", "x1\n---\nx2"),
    }
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert out == ["before", "x1", "x2", "after"]


def test_expand_recursive_bare_reference_requires_bang() -> None:
    catalog = {
        "outer": _xp("outer", "before\n---\n#inner\n---\nafter"),
        "inner": _xp("inner", "x1\n---\nx2"),
    }
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!inner"):
            expand_multi_agent_xprompts(["#!outer"])


def test_expand_separator_inside_fenced_block_in_body() -> None:
    """--- inside fenced code blocks inside the xprompt body is not a separator."""
    body = "intro\n```\ncode\n---\ndata\n```\n---\nreal split"
    catalog = {"x": _xp("x", body)}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!x"])
    assert len(out) == 2
    assert "```" in out[0]
    assert out[1] == "real split"


def test_expand_leading_directives_attach_to_first_subsegment() -> None:
    catalog = {"x": _xp("x", "a\n---\nb\n---\nc")}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["%name:custom\n#!x"])
    assert out[0] == "%name:custom\na"
    assert out[1] == "b"
    assert out[2] == "c"


def test_expand_vcs_prefixed_multi_agent_xprompt_prefixes_every_subsegment() -> None:
    catalog = {"three": _xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#gh:sase Implement", "#gh:sase Verify"]


def test_expand_known_project_vcs_prefix_without_registered_provider() -> None:
    catalog = {"three": _xp("three", "Plan\n---\nImplement")}
    with (
        _patch_catalog(catalog),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"sase": Path("/work/sase")},
        ),
    ):
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_with_directives_keeps_directives_on_first_segment() -> None:
    catalog = {"three": _xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["%name:custom\n#gh:sase #!three"])
    assert out == [
        "%name:custom\n#gh:sase Plan",
        "#gh:sase Implement",
        "#gh:sase Verify",
    ]


def test_expand_vcs_prefix_preserves_generated_directives() -> None:
    catalog = {"three": _xp("three", "%name:plan\nPlan\n---\nImplement")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["%name:plan\n#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_does_not_override_segment_local_vcs_ref() -> None:
    catalog = {"three": _xp("three", "Plan\n---\n#git:other Implement\n---\nVerify")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#git:other Implement", "#gh:sase Verify"]


def test_bare_vcs_prefixed_multi_agent_xprompt_requires_bang() -> None:
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!three"):
            expand_multi_agent_xprompts(["#gh:sase #three"])


def test_vcs_prefixed_multi_agent_xprompt_with_prose_remains_invalid() -> None:
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    with _patch_catalog(catalog), _patch_vcs_patterns():
        with pytest.raises(MultiAgentXPromptUsageError, match="sole '#!'"):
            expand_multi_agent_xprompts(["#gh:sase please #!three"])


def test_expand_local_xprompts_resolve() -> None:
    """Locally-defined xprompts (frontmatter) participate in expansion."""
    local = {
        "_local_three": _xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with _patch_catalog({}):  # No global xprompts
        out = expand_multi_agent_xprompts(["#!_local_three"], local_xprompts=local)
    assert out == ["alpha", "beta", "gamma"]


def test_expand_local_xprompts_require_bang() -> None:
    local = {
        "_local_three": _xp("_local_three", "alpha\n---\nbeta\n---\ngamma"),
    }
    with _patch_catalog({}):
        with pytest.raises(MultiAgentXPromptUsageError, match=r"#!_local_three"):
            expand_multi_agent_xprompts(["#_local_three"], local_xprompts=local)


def test_expand_depth_cap() -> None:
    """A self-referential multi-agent xprompt blows the depth cap."""
    catalog = {"loopy": _xp("loopy", "step\n---\n#!loopy")}
    with _patch_catalog(catalog):
        with pytest.raises(MultiAgentXPromptDepthError):
            expand_multi_agent_xprompts(["#!loopy"], max_depth=3)


def test_expand_passthrough_unknown_name() -> None:
    """Unknown xprompt names pass through unchanged (handled later by processor)."""
    with _patch_catalog({}):
        out = expand_multi_agent_xprompts(["#not_in_catalog"])
    assert out == ["#not_in_catalog"]


def test_expand_no_hashtag_fast_path() -> None:
    """Segments without '#' should not even need the catalog."""
    out = expand_multi_agent_xprompts(["plain segment", "another plain"])
    assert out == ["plain segment", "another plain"]


def test_expand_empty_subsegments_dropped() -> None:
    """Empty or whitespace-only sub-segments are dropped."""
    catalog = {"x": _xp("x", "a\n---\n   \n---\nb")}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!x"])
    assert out == ["a", "b"]


def test_expand_mixes_passthrough_and_expansion() -> None:
    """When a list contains a plain segment plus a multi-agent ref, both are handled."""
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["plain", "#!three"])
    assert out == ["plain", "a", "b", "c"]


def test_fenced_multi_agent_references_are_ignored() -> None:
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    segment = "Example:\n```\n#three\n#!three\n```"
    with _patch_catalog(catalog):
        out = expand_multi_agent_xprompts([segment])
    assert out == [segment]


def test_fenced_vcs_prefixed_multi_agent_references_are_ignored() -> None:
    catalog = {"three": _xp("three", "a\n---\nb\n---\nc")}
    segment = "Example:\n```\n#gh:sase #!three\n```"
    with _patch_catalog(catalog), _patch_vcs_patterns():
        out = expand_multi_agent_xprompts([segment])
    assert out == [segment]
