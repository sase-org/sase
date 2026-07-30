"""Tests for composing, nesting, and qualifying xprompt swarms."""

from __future__ import annotations

from itertools import count
from unittest.mock import patch

import pytest

from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
from sase.xprompt.models import InputArg, InputType

from tests._xprompt_swarm_helpers import (
    expand_xprompt_swarms,
    patch_catalog,
    xp,
)


def test_multiple_xprompt_swarm_references_expand_in_document_order() -> None:
    catalog = {
        "a": xp("a", "a1\n---\na2"),
        "b": xp("b", "b1\n---\nb2"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["Use #a then #b after"])
    assert out == ["Use a1", "a2", "b1", "b2"]


def test_multiple_xprompt_swarm_references_keep_distinct_args_and_groups() -> None:
    catalog = {
        "a": xp(
            "a",
            "a1 {{ target }}\n---\na2 {{ target }}",
            inputs=[InputArg(name="target", type=InputType.WORD)],
        ),
        "b": xp(
            "b",
            "b1 {{ mode }}\n---\nb2 {{ mode }}",
            inputs=[InputArg(name="mode", type=InputType.WORD)],
        ),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms_with_metadata(
            ["Start #a(foo) then #b(mode=bar) done"]
        )

    assert [record.prompt for record in out] == [
        "Start a1 foo",
        "a2 foo",
        "b1 bar",
        "b2 bar",
    ]
    assert [record.template_group for record in out] == [
        "xprompt:a:0",
        "xprompt:a:0",
        "xprompt:b:1",
        "xprompt:b:1",
    ]
    assert [record.swarm_xprompts for record in out] == [
        ("a",),
        ("a",),
        ("b",),
        ("b",),
    ]


def test_three_xprompt_swarm_references_expand_sequentially() -> None:
    catalog = {
        "a": xp("a", "a1\n---\n"),
        "b": xp("b", "b1\n---\n"),
        "c": xp("c", "c1\n---\n"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["Lead #a between #b and #c tail"])
    assert out == ["Lead a1", "b1", "c1"]


def test_multiple_xprompt_swarm_references_obey_depth_cap() -> None:
    catalog = {
        "a": xp("a", "#a\n---\na2"),
        "b": xp("b", "b1\n---\nb2"),
    }
    with patch_catalog(catalog):
        with pytest.raises(ValueError, match="exceeded max depth"):
            expand_xprompt_swarms(["#a then #b"], max_depth=1)


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
        out = expand_xprompt_swarms(["#!outer"])
    assert len(out) == 3
    assert out[0] == "first"
    assert "#inner" in out[1]
    assert out[2] == "third"


def test_expand_inline_multi_agent_inside_other_xprompt_body_embeds() -> None:
    """A real inline reference to an xprompt swarm is expanded recursively."""
    catalog = {
        "outer": xp("outer", "first\n---\nprose with #inner here\n---\nthird"),
        "inner": xp("inner", "x\n---\ny"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!outer"])
    assert out == ["first", "prose with x here", "y", "third"]


def test_expand_recursive_standalone_reference() -> None:
    """Xprompt swarm that references another xprompt swarm as a sole segment."""
    catalog = {
        "outer": xp("outer", "before\n---\n#!inner\n---\nafter"),
        "inner": xp("inner", "x1\n---\nx2"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!outer"])
    assert out == ["before", "x1", "x2", "after"]


def test_expand_recursive_bare_reference() -> None:
    catalog = {
        "outer": xp("outer", "before\n---\n#inner\n---\nafter"),
        "inner": xp("inner", "x1\n---\nx2"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!outer"])
    assert out == ["before", "x1", "x2", "after"]


def test_nested_xprompt_swarm_metadata_records_outer_to_inner_chain() -> None:
    catalog = {
        "outer": xp("outer", "outer first\n---\n#!inner"),
        "inner": xp("inner", "inner first\n---\ninner second"),
    }
    with patch_catalog(catalog):
        out = expand_xprompt_swarms_with_metadata(["#!outer"])

    assert [record.prompt for record in out] == [
        "outer first",
        "inner first",
        "inner second",
    ]
    assert [record.template_group for record in out] == [
        "xprompt:outer:0",
        "xprompt:outer:0",
        "xprompt:outer:0",
    ]
    assert [record.swarm_xprompts for record in out] == [
        ("outer",),
        ("outer", "inner"),
        ("outer", "inner"),
    ]


def test_expand_separator_inside_fenced_block_in_body() -> None:
    """--- inside fenced code blocks inside the xprompt body is not a separator."""
    body = "intro\n```\ncode\n---\ndata\n```\n---\nreal split"
    catalog = {"x": xp("x", body)}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["#!x"])
    assert len(out) == 2
    assert "```" in out[0]
    assert out[1] == "real split"


def test_expand_leading_directives_attach_to_first_subsegment() -> None:
    catalog = {"x": xp("x", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog):
        out = expand_xprompt_swarms(["%id:custom\n#!x"])
    assert out[0] == "%id:custom\na"
    assert out[1] == "b"
    assert out[2] == "c"


def test_shared_group_counter_keeps_invocations_distinct_across_calls() -> None:
    """Per-segment expansion calls sharing a counter never collide on groups.

    Regression test for the ``segment_extra_env`` launch path, which expands
    one segment per call: without a shared counter the per-call counter reset
    to 0 and two invocations of the same xprompt merged into one template
    group (and thus one shared name namespace).
    """
    catalog = {"two": xp("two", "phase A\n---\nphase B")}
    shared_counter = count()
    shared_qualification_counter = count()
    with patch_catalog(catalog):
        first = expand_xprompt_swarms_with_metadata(
            ["#!two"],
            group_counter=shared_counter,
            qualification_counter=shared_qualification_counter,
        )
        second = expand_xprompt_swarms_with_metadata(
            ["#!two"],
            group_counter=shared_counter,
            qualification_counter=shared_qualification_counter,
        )

    assert [record.template_group for record in first] == [
        "xprompt:two:0",
        "xprompt:two:0",
    ]
    assert [record.template_group for record in second] == [
        "xprompt:two:1",
        "xprompt:two:1",
    ]


def test_swarm_qualifies_one_key_consistently_across_segments() -> None:
    catalog = {
        "swarm": xp(
            "swarm",
            (
                "%id:research.{@1}.cdx\n"
                "Prose `research.{@1}.cdx`\n"
                "---\n"
                "%clan:research.{@1}\n"
                "Lead research.{@1}.cdx"
            ),
        )
    }

    with (
        patch_catalog(catalog),
        patch("sase.core.time.generate_timestamp", return_value="260729_093000"),
    ):
        out = expand_xprompt_swarms(["#!swarm"])

    marker = "{@swarm.260729.093000.0.1!}"
    assert out == [
        f"%id:research.{marker}.cdx\nProse `research.{marker}.cdx`",
        f"%clan:research.{marker}\nLead research.{marker}.cdx",
    ]


def test_two_swarm_invocations_get_distinct_qualified_keys() -> None:
    catalog = {"swarm": xp("swarm", "%id:r.{@1}.a\n---\n%id:r.{@1}.b")}

    with (
        patch_catalog(catalog),
        patch("sase.core.time.generate_timestamp", return_value="260729_093000"),
    ):
        out = expand_xprompt_swarms(["#!swarm", "#!swarm"])

    assert out == [
        "%id:r.{@swarm.260729.093000.0.1!}.a",
        "%id:r.{@swarm.260729.093000.0.1!}.b",
        "%id:r.{@swarm.260729.093000.1.1!}.a",
        "%id:r.{@swarm.260729.093000.1.1!}.b",
    ]


def test_swarm_leaves_qualified_bare_and_protected_markers_untouched() -> None:
    catalog = {
        "swarm": xp(
            "swarm",
            (
                "%id:r.{@x!}.a\n"
                "Bare r.@.a\n"
                "```\n"
                "%id:r.{@fenced}.a\n"
                "```\n"
                "---\n"
                "%xprompts_enabled:false\n"
                "%id:r.{@disabled}.a\n"
                "%xprompts_enabled:true\n"
                "%id:r.{@active}.a"
            ),
        )
    }

    with (
        patch_catalog(catalog),
        patch("sase.core.time.generate_timestamp", return_value="260729_093000"),
    ):
        out = expand_xprompt_swarms(["#!swarm"])

    assert out == [
        ("%id:r.{@x!}.a\nBare r.@.a\n```\n%id:r.{@fenced}.a\n```"),
        (
            "%xprompts_enabled:false\n"
            "%id:r.{@disabled}.a\n"
            "%xprompts_enabled:true\n"
            "%id:r.{@swarm.260729.093000.0.active!}.a"
        ),
    ]


def test_nested_swarms_use_distinct_keys_unless_already_qualified() -> None:
    catalog = {
        "outer": xp(
            "outer",
            "%id:outer.{@1}\nCaller {@shared!}\n---\n#!inner",
        ),
        "inner": xp(
            "inner",
            "%id:inner.{@1}\nInner {@shared!}\n---\nDone {@1} {@shared!}",
        ),
    }

    with (
        patch_catalog(catalog),
        patch("sase.core.time.generate_timestamp", return_value="260729_093000"),
    ):
        out = expand_xprompt_swarms(["#!outer"])

    outer = "{@outer.260729.093000.0.1!}"
    inner = "{@inner.260729.093000.1.1!}"
    assert out == [
        f"%id:outer.{outer}\nCaller {{@shared!}}",
        f"%id:inner.{inner}\nInner {{@shared!}}",
        f"Done {inner} {{@shared!}}",
    ]
