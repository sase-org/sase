"""Tests for VCS-reference inheritance during xprompt swarm expansion."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.multi_prompt_reference_directives import extract_static_clan_directive
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
from sase.xprompt.models import InputArg, InputType

from tests._xprompt_swarm_helpers import (
    expand_xprompt_swarms,
    patch_catalog,
    patch_vcs_patterns,
    xp,
)


def test_expand_inline_with_vcs_prefix_inherits_followups() -> None:
    catalog = {
        "three": xp(
            "three",
            "Plan {{ feature }}\n---\nBuild {{ feature }}\n---\nTest {{ feature }}",
            inputs=[InputArg(name="feature", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #three:: login flow"])
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
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["%i:abq #gh:sase #swarm:: review the changes"])
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%i:abq #gh:sase Plan review the changes",
        "%w #gh:sase #fork #research/more %m:opus",
        "%w #gh:sase #fork #research/image",
    ]


def test_expand_inline_multiple_same_line_directives_inherit_vcs() -> None:
    catalog = {
        "swarm": xp(
            "swarm",
            "Plan {{ prompt }}\n---\n%w #fork #research/more",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(
            ["%i:abq %model:opus #gh:sase #swarm:: review the changes"]
        )
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%i:abq %model:opus #gh:sase Plan review the changes",
        "%w #gh:sase #fork #research/more",
    ]


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
            return_value={"git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))")},
        ),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"sase": Path("/work/sase")},
        ),
    ):
        out = expand_xprompt_swarms(["%i:abq #gh_sase #swarm:: review the changes"])
        normalized = [
            normalize_default_vcs_workflow_segment(segment) for segment in out
        ]
    assert normalized == [
        "%i:abq #gh_sase Plan review the changes",
        "%w #gh_sase #fork #research/more",
    ]


def test_expand_inline_vcs_prefix_does_not_override_generated_vcs_ref() -> None:
    catalog = {"three": xp("three", "Plan\n---\n#git:other Build\n---\nTest")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #three"])
    assert out == ["#gh:sase Plan", "#git:other Build", "#gh:sase Test"]


def test_multiple_xprompt_swarm_references_inherit_leading_vcs_ref() -> None:
    catalog = {
        "a": xp("a", "a1\n---\na2"),
        "b": xp("b", "b1\n---\n#git:other b2"),
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase Review #a then #b after"])
    assert out == [
        "#gh:sase Review a1",
        "#gh:sase a2",
        "#gh:sase b1",
        "#git:other b2",
    ]


def test_expand_vcs_prefixed_xprompt_swarm_prefixes_every_subsegment() -> None:
    catalog = {"three": xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #!three"])
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
        out = expand_xprompt_swarms(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_with_directives_keeps_directives_on_first_segment() -> None:
    catalog = {"three": xp("three", "Plan\n---\nImplement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["%id:custom\n#gh:sase #!three"])
    assert out == [
        "%id:custom\n#gh:sase Plan",
        "#gh:sase Implement",
        "#gh:sase Verify",
    ]


def test_expand_vcs_prefix_preserves_generated_directives() -> None:
    catalog = {"three": xp("three", "%id:plan\nPlan\n---\nImplement")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #!three"])
    assert out == ["%id:plan\n#gh:sase Plan", "#gh:sase Implement"]


def test_expand_vcs_prefix_does_not_override_segment_local_vcs_ref() -> None:
    catalog = {"three": xp("three", "Plan\n---\n#git:other Implement\n---\nVerify")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #!three"])
    assert out == ["#gh:sase Plan", "#git:other Implement", "#gh:sase Verify"]


def test_bare_vcs_prefixed_xprompt_swarm_expands() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #three"])
    assert out == ["#gh:sase a", "#gh:sase b", "#gh:sase c"]


def test_vcs_prefixed_xprompt_swarm_with_prose_inherits_vcs() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase please #!three"])
    assert out == ["#gh:sase please a", "#gh:sase b", "#gh:sase c"]


def test_inherited_vcs_ref_does_not_split_multiline_clan_directive() -> None:
    """Regression: a wrapped ``%clan(...)`` must stay intact when the launch
    prompt's VCS ref is inherited into the swarm's first segment (the
    Telegram-shaped ``#gh:sase #swarm:: ...`` launch)."""
    catalog = {
        "swarm": xp(
            "swarm",
            "%clan(swarm.abc, tribe=research,\n"
            "summary=[[RESEARCH PROMPT: {{ prompt }}]]) %id:swarm.abc.cdx\n"
            "%wait(priority=20) %model:@research_a {{ prompt }} #research"
            "\n---\nfollow-up {{ prompt }}",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #swarm:: review the changes"])
    assert len(out) == 2
    segment = out[0]
    assert ",\n#gh:sase" not in segment
    assert (
        "%clan(swarm.abc, tribe=research,\n"
        "summary=[[RESEARCH PROMPT: review the changes]]) %id:swarm.abc.cdx\n"
        "%wait(priority=20) %model:@research_a #gh:sase review the changes #research"
    ) == segment


def test_inherited_vcs_ref_multiline_clan_directive_parses_cleanly() -> None:
    """The expanded segment must parse to a real clan directive, not the
    corrupted-keyword error the splicing bug produced."""
    catalog = {
        "swarm": xp(
            "swarm",
            "%clan(swarm.abc, tribe=research,\n"
            "summary=[[RESEARCH PROMPT: {{ prompt }}]]) %id:swarm.abc.cdx\n"
            "%wait(priority=20) %model:@research_a {{ prompt }} #research"
            "\n---\nfollow-up {{ prompt }}",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #swarm:: review the changes"])
    directive = extract_static_clan_directive(out[0])
    assert directive is not None
    assert directive.name == "swarm.abc"
    assert directive.tribe == "research"


def test_inherited_vcs_ref_multiline_clan_directive_with_unbalanced_paren() -> None:
    """The fix must rely on text-block-aware paren matching, not a regex that
    happens to balance: an unmatched '(' in the user's prose (inside the
    ``summary=[[...]]`` text block) must not defeat the scan."""
    catalog = {
        "swarm": xp(
            "swarm",
            "%clan(swarm.abc, tribe=research,\n"
            "summary=[[RESEARCH PROMPT: {{ prompt }}]]) %id:swarm.abc.cdx\n"
            "{{ prompt }}\n---\nfollow-up",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(
            ["#gh:sase #swarm:: fix (the gates without closing it"]
        )
    assert len(out) == 2
    segment = out[0]
    assert ",\n#gh:sase" not in segment
    directive = extract_static_clan_directive(segment)
    assert directive is not None
    assert directive.name == "swarm.abc"


def test_inherited_vcs_ref_leaves_malformed_clan_directive_malformed() -> None:
    """A ``%clan(`` that never closes must not get a VCS ref spliced into its
    argument list; the ref is placed ahead of the directive run instead, and
    the prompt still fails with the parser's own malformed-directive error."""
    catalog = {
        "swarm": xp(
            "swarm",
            "%clan(swarm.abc, tribe=research\n{{ prompt }}\n---\nfollow-up",
            inputs=[InputArg(name="prompt", type=InputType.TEXT)],
        )
    }
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_xprompt_swarms(["#gh:sase #swarm:: review the changes"])
    assert len(out) == 2
    segment = out[0]
    assert segment.startswith("#gh:sase %clan(")
    with pytest.raises(DirectiveError, match="missing closing"):
        extract_static_clan_directive(segment)
