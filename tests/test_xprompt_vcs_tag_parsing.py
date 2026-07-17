"""Tests for xprompt._parsing VCS tag parsing helpers."""

import re
from unittest.mock import patch

from sase.xprompt._parsing import (
    extract_vcs_workflow_tag,
    find_vcs_workflow_tag,
    find_vcs_workflow_tag_prepend_offset,
    find_vcs_workflow_tag_span,
    normalize_default_vcs_workflow_segment,
    normalize_launch_xprompt_at_refs,
    normalize_vcs_underscore_refs,
    replace_ref_in_vcs_tag,
)


_TEST_VCS_PATTERN = re.compile(
    r"^#(?:gh|git|spy)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s"
)


def _patch_vcs_pattern():
    """Patch _get_vcs_tag_pattern to use the test pattern."""
    return patch(
        "sase.xprompt._parsing._get_vcs_tag_pattern",
        return_value=_TEST_VCS_PATTERN,
    )


def test_extract_vcs_workflow_tag_basic() -> None:
    """Test extracting a basic VCS tag like #gh:sase."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#gh:sase Fix the bug") == "#gh:sase "


def test_extract_vcs_workflow_tag_spy_hitl() -> None:
    """Test extracting a VCS tag with !! HITL suffix."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#spy!!:cl Fix it") == "#spy!!:cl "


def test_extract_vcs_workflow_tag_git_paren() -> None:
    """Test extracting a VCS tag with parenthesis args."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#git(repo) Do stuff") == "#git(repo) "


def test_extract_vcs_workflow_tag_with_directives() -> None:
    """Test that %directive lines are skipped before VCS tag."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%name\n#gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_extract_vcs_workflow_tag_multiple_directives() -> None:
    """Test skipping multiple %directive lines."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%name\n%model:opus\n#gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_extract_vcs_workflow_tag_after_parenthesized_directive() -> None:
    """Spaces in parenthesized directive args stay inside the directive."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag(
            "%family(epic-1, role=phase)\n#gh:sase Fix the bug"
        )
        assert result == "#gh:sase "


def test_normalize_default_vcs_after_parenthesized_directive() -> None:
    """Default VCS insertion must not split parenthesized directive args."""
    with patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value={"git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))")},
    ):
        prompt = "%family(epic-1, role=phase)\nDo the work"
        assert normalize_default_vcs_workflow_segment(prompt) == (
            "%family(epic-1, role=phase)\n#git:home Do the work"
        )


def test_extract_vcs_workflow_tag_no_tag() -> None:
    """Test returns None when no VCS tag is present."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("Just a normal prompt") is None


def test_extract_vcs_workflow_tag_directive_only() -> None:
    """Test returns None when prompt is only a directive with no newline."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("%name") is None


def test_extract_vcs_workflow_tag_empty() -> None:
    """Test returns None for empty prompt."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("") is None


def test_extract_vcs_workflow_tag_underscore() -> None:
    """Test extracting a VCS tag with underscore separator (#gh_sase)."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#gh_sase Fix the bug") == "#gh_sase "


def test_extract_vcs_workflow_tag_underscore_git() -> None:
    """Test extracting a VCS tag with underscore separator for git."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#git_myrepo Do stuff") == "#git_myrepo "


def test_extract_vcs_workflow_tag_directive_same_line() -> None:
    """Test extracting VCS tag when %directive is on the same line."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%n:a #gh_sase Fix the bug")
        assert result == "#gh_sase "


def test_extract_vcs_workflow_tag_multiple_directives_same_line() -> None:
    """Test extracting VCS tag with multiple %directives on the same line."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%n:a %model:opus #gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_extract_vcs_workflow_tag_directive_mixed_lines() -> None:
    """Test extracting VCS tag with directives on separate lines and same line."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%model:opus\n%n:a #gh:sase Fix the bug")
        assert result == "#gh:sase "


_TEST_EMBEDDED_VCS_PATTERN = re.compile(
    r"(?:^|(?<=\s))#(?:gh|git|spy)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s"
)


def _patch_embedded_vcs_pattern():
    """Patch _get_embedded_vcs_tag_pattern to use the test pattern."""
    return patch(
        "sase.xprompt._parsing._get_embedded_vcs_tag_pattern",
        return_value=_TEST_EMBEDDED_VCS_PATTERN,
    )


def test_find_vcs_workflow_tag_leading() -> None:
    """find_vcs_workflow_tag matches a leading tag like extract_vcs_workflow_tag."""
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag("#gh:sase Fix the bug") == "#gh:sase "


def test_find_vcs_workflow_tag_second_line() -> None:
    """Embedded tag on line 2 is recovered."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("Some intro\n#gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_find_vcs_workflow_tag_mid_line() -> None:
    """Embedded tag mid-line is recovered."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("tweak something #gh:sase quickly")
        assert result == "#gh:sase "


def test_find_vcs_workflow_tag_after_xprompt_directive() -> None:
    """Embedded tag after a non-%directive xprompt line is recovered."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("#fast\n#gh:sase fix it")
        assert result == "#gh:sase "


def test_find_vcs_workflow_tag_no_tag() -> None:
    """Returns None when no VCS tag is present."""
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag("Just a normal prompt") is None


def test_find_vcs_workflow_tag_glued_prefix_skipped() -> None:
    """Returns None when the only #gh:... is glued to a non-whitespace prefix."""
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag("foo#gh:sase ") is None


def test_find_vcs_workflow_tag_first_match_wins() -> None:
    """First boundary-anchored tag wins when multiple are present."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("#gh:sase first\n#gh:other later")
        assert result == "#gh:sase "


def test_find_vcs_workflow_tag_paren_format() -> None:
    """Embedded paren-format tag is recovered."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("intro\n#git(repo) do stuff")
        assert result == "#git(repo) "


def test_find_vcs_workflow_tag_hitl_suffix() -> None:
    """Embedded tag with HITL suffix is recovered."""
    with _patch_embedded_vcs_pattern():
        result = find_vcs_workflow_tag("intro #spy!!:cl Fix it")
        assert result == "#spy!!:cl "


def test_find_vcs_workflow_tag_span_matches_tag_at_end() -> None:
    """Span matching uses a sentinel space so end-of-text tags are found."""
    prompt = "fix #gh:sase"
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag_span(prompt) == (len("fix "), len(prompt))


def test_find_vcs_workflow_tag_span_excludes_trailing_newline() -> None:
    """The returned span excludes the pattern's required whitespace."""
    prompt = "#gh:sase\nFix it"
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag_span(prompt) == (0, len("#gh:sase"))


def test_find_vcs_workflow_tag_span_skips_fenced_blocks() -> None:
    """Tags inside fenced code blocks are quoted content, not workflow refs."""
    prompt = "Fix it:\n```\nsase run #gh:sase do thing\n```\nthen #git:foo go"
    with _patch_embedded_vcs_pattern():
        start = prompt.index("#git:foo")
        assert find_vcs_workflow_tag_span(prompt) == (
            start,
            start + len("#git:foo"),
        )


def test_find_vcs_workflow_tag_span_returns_none_when_only_fenced() -> None:
    """A prompt whose only tag-like text is fenced has no workflow tag."""
    prompt = "Fix it:\n```\nsase run #gh:sase do thing\n```\n"
    with _patch_embedded_vcs_pattern():
        assert find_vcs_workflow_tag_span(prompt) is None


def test_prepend_offset_preserves_frontmatter_directives() -> None:
    prompt = "---\nxprompts: {}\n---\n  %n:a %wait Fix it"
    assert find_vcs_workflow_tag_prepend_offset(prompt) == len(
        "---\nxprompts: {}\n---\n  %n:a %wait "
    )


def test_prepend_offset_does_not_skip_line_breaks() -> None:
    assert find_vcs_workflow_tag_prepend_offset("\n") == 0
    assert find_vcs_workflow_tag_prepend_offset("\nmore") == 0
    assert find_vcs_workflow_tag_prepend_offset("  Body") == 2
    assert find_vcs_workflow_tag_prepend_offset("\tBody") == 1


def test_replace_ref_in_vcs_tag_colon() -> None:
    """Test replacing ref in colon format: #gh:sase -> #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh:sase ", "sase_foobar_1") == "#gh:sase_foobar_1 "


def test_replace_ref_in_vcs_tag_paren() -> None:
    """Test replacing ref in parenthesized format: #git(repo) -> #git(new_branch)."""
    assert replace_ref_in_vcs_tag("#git(repo) ", "new_branch") == "#git(new_branch) "


def test_replace_ref_in_vcs_tag_hitl_bang() -> None:
    """Test that !! HITL suffix is stripped: #gh!!:sase -> #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh!!:sase ", "new_branch") == "#gh:new_branch "


def test_replace_ref_in_vcs_tag_hitl_question() -> None:
    """Test that ?? HITL suffix is stripped: #spy??:cl -> #spy:new_branch."""
    assert replace_ref_in_vcs_tag("#spy??:cl ", "new_branch") == "#spy:new_branch "


def test_replace_ref_in_vcs_tag_underscore() -> None:
    """Test replacing ref in underscore format: #gh_sase -> #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh_sase ", "sase_foobar_1") == "#gh:sase_foobar_1 "


def test_replace_ref_in_vcs_tag_bare() -> None:
    """Test replacing ref on bare tag: #gh -> #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh ", "new_branch") == "#gh:new_branch "


def _patch_workflow_names(names: set[str]):
    """Patch get_workflow_names to return *names*."""
    return patch(
        "sase.workspace_provider.get_workflow_names",
        return_value=names,
    )


def test_normalize_vcs_underscore_basic() -> None:
    """Test #gh_sase -> #gh:sase."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "spy"}):
        assert normalize_vcs_underscore_refs("#gh_sase Fix bug") == "#gh:sase Fix bug"


def test_normalize_vcs_underscore_git() -> None:
    """Test #git_myrepo -> #git:myrepo."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "spy"}):
        assert (
            normalize_vcs_underscore_refs("#git_myrepo Do stuff")
            == "#git:myrepo Do stuff"
        )


def test_normalize_vcs_underscore_not_vcs() -> None:
    """Test non-VCS underscore names like #my_xprompt are NOT normalized."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "spy"}):
        assert normalize_vcs_underscore_refs("#my_xprompt hello") == "#my_xprompt hello"


def test_normalize_vcs_underscore_preserves_colon() -> None:
    """Test #gh:sase is left unchanged."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "spy"}):
        assert normalize_vcs_underscore_refs("#gh:sase Fix bug") == "#gh:sase Fix bug"


def test_normalize_vcs_underscore_mid_line() -> None:
    """Test normalization works after whitespace mid-line."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "spy"}):
        assert (
            normalize_vcs_underscore_refs("text #gh_sase prompt")
            == "text #gh:sase prompt"
        )


def test_normalize_launch_xprompt_at_refs_scoped_to_workflows() -> None:
    import sase.xprompt._parsing as _mod

    _mod._LAUNCH_XPROMPT_AT_REF_RE = None
    with _patch_workflow_names({"gh", "git", "cd"}):
        assert normalize_launch_xprompt_at_refs("#gh@sase Fix") == "#gh:sase Fix"
        assert (
            normalize_launch_xprompt_at_refs("%n:a #git@repo Fix")
            == "%n:a #git:repo Fix"
        )
        assert normalize_launch_xprompt_at_refs("#topic@sase") == "#topic@sase"


def test_normalize_launch_xprompt_at_refs_skips_markdown_code() -> None:
    import sase.xprompt._parsing as _mod

    _mod._LAUNCH_XPROMPT_AT_REF_RE = None
    with _patch_workflow_names({"gh", "git"}):
        text = "run `#gh@sase` then #gh@zorg"
        assert normalize_launch_xprompt_at_refs(text) == "run `#gh@sase` then #gh:zorg"

        fenced = "```\n#gh@sase\n```\n#git@repo"
        assert (
            normalize_launch_xprompt_at_refs(fenced) == "```\n#gh@sase\n```\n#git:repo"
        )
