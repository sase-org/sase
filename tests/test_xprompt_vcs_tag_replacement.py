"""Tests for xprompt._parsing VCS tag replacement and inheritance helpers."""

import re
from unittest.mock import patch

from sase.xprompt._disabled_regions import protect_disabled_regions
from sase.xprompt._parsing import (
    inherit_vcs_workflow_tag,
    normalize_default_vcs_workflow,
    replace_vcs_workflow_tags,
)
from sase.xprompt._parsing_vcs_tags import (
    _inherit_vcs_workflow_tag_segment,
    normalize_default_vcs_workflow_segment,
)


_TEST_VCS_REPLACE_PATTERN = re.compile(
    r"^((?:%\S+[\s]+)*)#(?:gh|git|spy)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)(?:\s|$)",
    re.MULTILINE,
)


def _patch_vcs_replace_pattern():
    """Patch _get_vcs_replace_pattern to use the test pattern."""
    return patch(
        "sase.xprompt._parsing._get_vcs_replace_pattern",
        return_value=_TEST_VCS_REPLACE_PATTERN,
    )


def test_replace_vcs_tags_single_prompt() -> None:
    """Replace the VCS tag in a simple single-segment prompt."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#gh:sase Fix the bug", "#gh:other")
        assert result == "#gh:other Fix the bug"


def test_replace_vcs_tags_multi_prompt() -> None:
    """Replace VCS tags in each segment of a multi-prompt."""
    prompt = "#gh:sase Fix A\n---\n#gh:sase Fix B"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "#gh:other Fix A\n---\n#gh:other Fix B"


def test_replace_vcs_tags_cross_vcs() -> None:
    """Replace a #git tag with a #gh tag (cross-VCS reuse)."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#git:repo Fix bug", "#gh:sase")
        assert result == "#gh:sase Fix bug"


def test_replace_vcs_tags_with_directive_same_line() -> None:
    """Preserve %directive prefix when replacing VCS tag."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("%i:a #gh:sase Fix bug", "#gh:other")
        assert result == "%i:a #gh:other Fix bug"


def test_replace_vcs_tags_with_directives_multi_line() -> None:
    """Preserve multi-line directives before VCS tag."""
    prompt = "%model:opus\n%i:a #gh:sase Fix bug"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "%model:opus\n%i:a #gh:other Fix bug"


def test_replace_vcs_tags_multi_prompt_with_directives() -> None:
    """Replace VCS tags in multi-prompt where segments have directives."""
    prompt = "%i:a #gh:sase Fix A\n---\n%i:b #gh:sase Fix B"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "%i:a #gh:other Fix A\n---\n%i:b #gh:other Fix B"


def test_replace_vcs_tags_no_existing_tag() -> None:
    """Prepend VCS prefix when prompt has no existing VCS tag."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("Fix the bug", "#gh:sase")
        assert result == "#gh:sase Fix the bug"


def test_replace_vcs_tags_tag_only_at_eof() -> None:
    """Replace a VCS tag that sits at end-of-input with no trailing space.

    A prompt consisting solely of a VCS tag (the state left behind after the
    ``+`` project-completion trigger is stripped from ``#gh:sase +``) must be
    replaced, not prepended -- otherwise the selected tag is doubled.
    """
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#git:foo", "#gh:sase")
        assert result == "#gh:sase "


def test_replace_vcs_tags_tag_only_at_eof_same_prefix() -> None:
    """A bare tag at EOF is replaced even when the new prefix matches it."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#gh:sase", "#gh:sase")
        assert result == "#gh:sase "


def test_replace_vcs_tags_hitl_modifier() -> None:
    """Replace a VCS tag that has !! (HITL) modifier."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#spy!!:cl Fix it", "#gh:sase")
        assert result == "#gh:sase Fix it"


def test_replace_vcs_tags_paren_args() -> None:
    """Replace a VCS tag that uses parenthesis args."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#git(repo) Do stuff", "#gh:sase")
        assert result == "#gh:sase Do stuff"


def test_replace_vcs_tags_mixed_vcs_multi_prompt() -> None:
    """Replace different VCS tags across multi-prompt segments."""
    prompt = "#gh:sase Fix A\n---\n#git:repo Fix B"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "#gh:other Fix A\n---\n#gh:other Fix B"


def _patch_ref_patterns(names: set[str] | None = None):
    pattern = re.compile(
        r"#(?:gh|git|spy|cd)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)(?=\s|$)"
    )
    return patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value=dict.fromkeys(names or {"gh", "git", "spy", "cd"}, pattern),
    )


def test_inherit_vcs_tag_prefixes_bare_prompt() -> None:
    """Bare prompt segments inherit the wrapper VCS tag."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        assert inherit_vcs_workflow_tag("Fix the bug", "#gh:sase ") == (
            "#gh:sase Fix the bug"
        )


def test_inherit_vcs_tag_preserves_leading_directives() -> None:
    """Inherited tags are inserted after leading % directives."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        prompt = "%w #fork #research/more %m:opus"
        assert inherit_vcs_workflow_tag(prompt, "#gh:sase ") == (
            "%w #gh:sase #fork #research/more %m:opus"
        )


def test_inherit_vcs_tag_applies_per_multi_prompt_segment() -> None:
    """Each untagged multi-prompt segment inherits independently."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        prompt = "Fix A\n---\n%w Fix B"
        assert inherit_vcs_workflow_tag(prompt, "#gh:sase ") == (
            "#gh:sase Fix A\n---\n%w #gh:sase Fix B"
        )


def test_inherit_vcs_tag_skips_explicit_workspace_refs() -> None:
    """Explicit VCS refs remain authoritative."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        prompt = "#git:other Fix A\n---\n#spy:work Fix B"
        assert inherit_vcs_workflow_tag(prompt, "#gh:sase ") == prompt


def test_inherit_vcs_tag_skips_known_project_fallback_ref() -> None:
    """Known-project refs are preserved even without a registered provider."""
    with (
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces", return_value={"sase"}
        ),
    ):
        prompt = "#gh:sase Fix it"
        assert inherit_vcs_workflow_tag(prompt, "#git:other ") == prompt


def _fork_shaped_prompt(query: str = "New query text") -> str:
    """Build a ``#fork``-injected-history-shaped prompt, tag already leading."""
    return (
        "#gh:sase \n"
        "%xprompts_enabled:false\n"
        "# Previous Conversation\n\n"
        "turn one\n\n"
        "---\n\n"
        "turn two\n\n"
        "---\n\n"
        "%xprompts_enabled:true\n"
        f"# New Query\n\n{query}"
    )


def test_inherit_vcs_tag_leaves_fork_injected_history_untouched() -> None:
    """A fork-shaped prompt is returned unchanged: no tag inside the region,
    and ``# New Query`` is not preceded by an injected tag."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        prompt = _fork_shaped_prompt()
        result = inherit_vcs_workflow_tag(prompt, "#gh:sase ")
        assert result == prompt
        assert "#gh:sase # New Query" not in result
        assert result.count("#gh:sase") == 1


def test_inherit_vcs_tag_mixed_multi_prompt_and_fork_region() -> None:
    """Real ``---`` segments outside a disabled region inherit; the region's
    internal ``---`` lines never become segment boundaries."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        fork_block = (
            "%xprompts_enabled:false\n"
            "# Previous Conversation\n\n"
            "turn one\n\n"
            "---\n\n"
            "turn two\n\n"
            "---\n\n"
            "%xprompts_enabled:true\n"
            "# New Query"
        )
        prompt = f"Fix A\n---\n{fork_block}\n\nquery text"
        result = inherit_vcs_workflow_tag(prompt, "#gh:sase ")

        assert result.startswith("#gh:sase Fix A\n---\n")
        assert "\n---\n\nturn two\n\n---\n\n%xprompts_enabled:true" in result
        assert "#gh:sase # New Query" not in result


def test_normalize_default_vcs_workflow_leaves_fork_injected_history_untouched() -> (
    None
):
    """Mirrors the ``inherit_vcs_workflow_tag`` fork-shaped-prompt case."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        prompt = _fork_shaped_prompt()
        result = normalize_default_vcs_workflow(prompt)
        assert result == prompt


def test_normalize_default_vcs_workflow_mixed_multi_prompt_and_fork_region() -> None:
    """Mirrors the ``inherit_vcs_workflow_tag`` mixed multi-prompt case."""
    with (
        _patch_ref_patterns(),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value=set()),
    ):
        fork_block = (
            "%xprompts_enabled:false\n"
            "# Previous Conversation\n\n"
            "turn one\n\n"
            "---\n\n"
            "turn two\n\n"
            "---\n\n"
            "%xprompts_enabled:true\n"
            "# New Query"
        )
        prompt = f"Fix A\n---\n{fork_block}\n\nquery text"
        result = normalize_default_vcs_workflow(prompt)

        assert result.startswith("#git:home Fix A\n---\n")
        assert "\n---\n\nturn two\n\n---\n\n%xprompts_enabled:true" in result
        assert "#git:home # New Query" not in result


def test_inherit_vcs_tag_segment_keeps_marker_at_line_start() -> None:
    """Guard: a tag inserted before a disabled-region-opening body leaves the
    marker on its own line, so the region stays parseable."""
    segment = "%xprompts_enabled:false\nhidden ---\n%xprompts_enabled:true"
    result = _inherit_vcs_workflow_tag_segment(segment, "#gh:sase ")

    regions: list[str] = []
    protected = protect_disabled_regions(result, regions)
    assert len(regions) == 1
    assert "---" not in protected


def test_normalize_default_vcs_workflow_segment_keeps_marker_at_line_start() -> None:
    """Guard: mirrors the ``_inherit_vcs_workflow_tag_segment`` case."""
    segment = "%xprompts_enabled:false\nhidden ---\n%xprompts_enabled:true"
    result = normalize_default_vcs_workflow_segment(segment)

    regions: list[str] = []
    protected = protect_disabled_regions(result, regions)
    assert len(regions) == 1
    assert "---" not in protected
