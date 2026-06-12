"""Tests for multi-agent xprompt expansion."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.multi_agent_xprompt import (
    _MultiAgentXPromptUsageError,
    expand_multi_agent_xprompts,
    expand_multi_agent_xprompts_with_metadata,
)
from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
from sase.xprompt.models import InputArg, InputType

from tests._multi_agent_xprompt_helpers import (
    patch_catalog,
    patch_vcs_patterns,
    patch_vcs_patterns_with_cd,
    xp,
)

# --- expand_multi_agent_xprompts ---


def test_expand_single_segment_xprompt_unchanged() -> None:
    """Xprompt with no separators in body → segments untouched."""
    catalog = {"single": xp("single", "just one body")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#single"])
    assert out == ["#single"]


def test_bang_single_segment_xprompt_invalid() -> None:
    """Ordinary xprompts remain embeddable and cannot use the standalone marker."""
    catalog = {"single": xp("single", "just one body")}
    with patch_catalog(catalog):
        with pytest.raises(_MultiAgentXPromptUsageError, match=r"Use '#single'"):
            expand_multi_agent_xprompts(["#!single"])


def test_expand_three_segment_xprompt() -> None:
    """Xprompt body with 3 segments → 3 sub-segments after expansion."""
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!three"])
    assert out == ["phase A", "phase B", "phase C"]


def test_expand_three_segment_xprompt_metadata_groups_one_invocation() -> None:
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts_with_metadata(["#!three"])

    assert [record.prompt for record in out] == ["phase A", "phase B", "phase C"]
    assert [record.template_group for record in out] == [
        "xprompt:three:0",
        "xprompt:three:0",
        "xprompt:three:0",
    ]


def test_expand_two_xprompt_invocations_get_distinct_metadata_groups() -> None:
    catalog = {"two": xp("two", "phase A\n---\nphase B")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts_with_metadata(["#!two", "#!two"])

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


def test_bare_multi_agent_xprompt_expands_as_sole_segment() -> None:
    catalog = {"three": xp("three", "phase A\n---\nphase B\n---\nphase C")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#three"])
    assert out == ["phase A", "phase B", "phase C"]


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
        out = expand_multi_agent_xprompts(["#!three(login bug fix)"])
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
        out = expand_multi_agent_xprompts(
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
        out = expand_multi_agent_xprompts(["#!loop(login, include_plan=true)"])
    assert len(out) == 3
    assert out[0] == "Plan first."
    assert out[1] == "Implement login."
    assert out[2] == "Test login."


def test_expand_mixed_with_prose_embeds_first_segment() -> None:
    """Multi-agent xprompt referenced mid-prose embeds its first sub-prompt."""
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["Hello #three world"])
    assert out == ["Hello a world", "b", "c"]


def test_expand_inline_with_shorthand_args() -> None:
    catalog = {
        "three": xp(
            "three",
            "Plan {{ feature }}\n---\nBuild {{ feature }}\n---\nTest {{ feature }}",
            inputs=[InputArg(name="feature", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#three:: login flow"])
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
        out = expand_multi_agent_xprompts(["#three:: login flow (oauth)"])
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
        out = expand_multi_agent_xprompts(["#research_swarm:: find foo (bar)"])
    assert out == [
        "find foo (bar) #research",
        "%w #fork #research/more %m:opus",
        "%w #fork #research/image",
    ]


def test_expand_inline_with_vcs_prefix_inherits_followups() -> None:
    catalog = {
        "three": xp(
            "three",
            "Plan {{ feature }}\n---\nBuild {{ feature }}\n---\nTest {{ feature }}",
            inputs=[InputArg(name="feature", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #three:: login flow"])
    assert out == [
        "#gh:sase Plan login flow",
        "#gh:sase Build login flow",
        "#gh:sase Test login flow",
    ]


def test_expand_inline_same_line_directive_inherits_vcs_to_followups() -> None:
    catalog = {
        "swarm": xp(
            "swarm",
            "Plan {{ prompt }}\n"
            "---\n"
            "%w #fork #research/more %m:opus\n"
            "---\n"
            "%w #fork #research/image",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns_with_cd():
        out = expand_multi_agent_xprompts(
            ["%n:abq #gh:sase #swarm:: review the changes"]
        )
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%n:abq #gh:sase Plan review the changes",
        "%w #gh:sase #fork #research/more %m:opus",
        "%w #gh:sase #fork #research/image",
    ]
    assert "#cd:~" not in "\n".join(normalized)


def test_expand_inline_multiple_same_line_directives_inherit_vcs() -> None:
    catalog = {
        "swarm": xp(
            "swarm",
            "Plan {{ prompt }}\n---\n%w #fork #research/more",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns_with_cd():
        out = expand_multi_agent_xprompts(
            ["%n:abq %model:opus #gh:sase #swarm:: review the changes"]
        )
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%n:abq %model:opus #gh:sase Plan review the changes",
        "%w #gh:sase #fork #research/more",
    ]
    assert "#cd:~" not in "\n".join(normalized)


def test_expand_inline_same_line_directive_inherits_known_project_underscore_ref() -> (
    None
):
    catalog = {
        "swarm": xp(
            "swarm",
            "Plan {{ prompt }}\n---\n%w #fork #research/more",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with (
        patch_catalog(catalog),
        patch(
            "sase.workspace_provider.get_ref_patterns",
            return_value={"cd": re.compile(r"#cd(?::([^\s]+)|\(([^)]*)\))")},
        ),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"sase": Path("/work/sase")},
        ),
    ):
        out = expand_multi_agent_xprompts(
            ["%n:abq #gh_sase #swarm:: review the changes"]
        )
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%n:abq #gh_sase Plan review the changes",
        "%w #gh_sase #fork #research/more",
    ]
    assert "#cd:~" not in "\n".join(normalized)


def test_expand_inline_vcs_prefix_does_not_override_generated_vcs_ref() -> None:
    catalog = {"three": xp("three", "Plan\n---\n#git:other Build\n---\nTest")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #three"])
    assert out == ["#gh:sase Plan", "#git:other Build", "#gh:sase Test"]


def test_multiple_multi_agent_references_in_one_segment_raises() -> None:
    catalog = {
        "a": xp("a", "a1\n---\na2"),
        "b": xp("b", "b1\n---\nb2"),
    }
    with patch_catalog(catalog):
        with pytest.raises(_MultiAgentXPromptUsageError, match="only one"):
            expand_multi_agent_xprompts(["Use #a and #b"])


def test_expand_inline_ordinary_xprompt_inside_other_xprompt_body_no_resplit() -> None:
    """If ordinary #b appears inline inside #a's body, no re-split.

    The inner xprompt reference survives as text in one of the outer's segments
    and gets passed through unchanged — the agent runner expands it later.
    """
    catalog = {
        "outer": xp("outer", "first\n---\nprose with #inner here\n---\nthird"),
        "inner": xp("inner", "x"),
    }
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert len(out) == 3
    assert out[0] == "first"
    assert "#inner" in out[1]
    assert out[2] == "third"


def test_expand_inline_multi_agent_inside_other_xprompt_body_embeds() -> None:
    """A real inline reference to a multi-agent xprompt is expanded recursively."""
    catalog = {
        "outer": xp("outer", "first\n---\nprose with #inner here\n---\nthird"),
        "inner": xp("inner", "x\n---\ny"),
    }
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert out == ["first", "prose with x here", "y", "third"]


def test_expand_recursive_standalone_reference() -> None:
    """Multi-agent xprompt that references another multi-agent xprompt as a sole segment."""
    catalog = {
        "outer": xp("outer", "before\n---\n#!inner\n---\nafter"),
        "inner": xp("inner", "x1\n---\nx2"),
    }
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert out == ["before", "x1", "x2", "after"]


def test_expand_recursive_bare_reference() -> None:
    catalog = {
        "outer": xp("outer", "before\n---\n#inner\n---\nafter"),
        "inner": xp("inner", "x1\n---\nx2"),
    }
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!outer"])
    assert out == ["before", "x1", "x2", "after"]


def test_expand_separator_inside_fenced_block_in_body() -> None:
    """--- inside fenced code blocks inside the xprompt body is not a separator."""
    body = "intro\n```\ncode\n---\ndata\n```\n---\nreal split"
    catalog = {"x": xp("x", body)}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["#!x"])
    assert len(out) == 2
    assert "```" in out[0]
    assert out[1] == "real split"


def test_expand_leading_directives_attach_to_first_subsegment() -> None:
    catalog = {"x": xp("x", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog):
        out = expand_multi_agent_xprompts(["%name:custom\n#!x"])
    assert out[0] == "%name:custom\na"
    assert out[1] == "b"
    assert out[2] == "c"


def test_expand_vcs_prefixed_multi_agent_xprompt_prefixes_every_subsegment() -> None:
    catalog = {"three": xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#gh:sase Implement", "#gh:sase Verify"]


def test_expand_known_project_vcs_prefix_without_registered_provider() -> None:
    catalog = {"three": xp("three", "Plan\n---\nImplement")}
    with (
        patch_catalog(catalog),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"sase": Path("/work/sase")},
        ),
    ):
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_with_directives_keeps_directives_on_first_segment() -> None:
    catalog = {"three": xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["%name:custom\n#gh:sase #!three"])
    assert out == [
        "%name:custom\n#gh:sase Plan",
        "#gh:sase Implement",
        "#gh:sase Verify",
    ]


def test_expand_vcs_prefix_preserves_generated_directives() -> None:
    catalog = {"three": xp("three", "%name:plan\nPlan\n---\nImplement")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["%name:plan\n#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_does_not_override_segment_local_vcs_ref() -> None:
    catalog = {"three": xp("three", "Plan\n---\n#git:other Implement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#git:other Implement", "#gh:sase Verify"]


def test_bare_vcs_prefixed_multi_agent_xprompt_expands() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase #three"])
    assert out == ["#gh:sase a", "#gh:sase b", "#gh:sase c"]


def test_vcs_prefixed_multi_agent_xprompt_with_prose_inherits_vcs() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_multi_agent_xprompts(["#gh:sase please #!three"])
    assert out == ["#gh:sase please a", "#gh:sase b", "#gh:sase c"]


def test_shared_group_counter_keeps_invocations_distinct_across_calls() -> None:
    """Per-segment expansion calls sharing a counter never collide on groups.

    Regression test for the ``segment_extra_env`` launch path, which expands
    one segment per call: without a shared counter the per-call counter reset
    to 0 and two invocations of the same xprompt merged into one template
    group (and thus one shared name namespace).
    """
    from itertools import count

    catalog = {"two": xp("two", "phase A\n---\nphase B")}
    shared_counter = count()
    with patch_catalog(catalog):
        first = expand_multi_agent_xprompts_with_metadata(
            ["#!two"], group_counter=shared_counter
        )
        second = expand_multi_agent_xprompts_with_metadata(
            ["#!two"], group_counter=shared_counter
        )

    assert [record.template_group for record in first] == [
        "xprompt:two:0",
        "xprompt:two:0",
    ]
    assert [record.template_group for record in second] == [
        "xprompt:two:1",
        "xprompt:two:1",
    ]
