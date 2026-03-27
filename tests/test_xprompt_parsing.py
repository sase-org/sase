"""Tests for xprompt._parsing functions."""

import re
from unittest.mock import patch

from sase.xprompt._parsing import (
    _preprocess_paren_shorthand,
    extract_vcs_workflow_tag,
    find_matching_paren_for_args,
    normalize_vcs_underscore_refs,
    parse_workflow_reference,
    preprocess_shorthand_syntax,
    replace_ref_in_vcs_tag,
    replace_vcs_workflow_tags,
    strip_hitl_suffix,
)


# Tests for _process_text_block


# Tests for _find_shorthand_text_end


# Tests for preprocess_shorthand_syntax


# Tests for find_matching_paren_for_args


def test_find_matching_paren_not_at_paren() -> None:
    """Test find_matching_paren_for_args returns None when not at paren."""
    assert find_matching_paren_for_args("hello", 0) is None


def test_find_matching_paren_with_text_block() -> None:
    """Test find_matching_paren_for_args handles text blocks."""
    assert find_matching_paren_for_args("([[content]]))", 0) == 12


# Tests for _parse_named_arg


# Tests for parse_args


# Tests for parse_workflow_reference


def test_parse_workflow_reference_plus() -> None:
    """Test parse_workflow_reference with plus syntax."""
    name, pos, _ = parse_workflow_reference("myworkflow+")
    assert name == "myworkflow"
    assert pos == ["true"]


def test_parse_workflow_reference_paren() -> None:
    """Test parse_workflow_reference with parenthesis syntax."""
    name, pos, named = parse_workflow_reference('myworkflow(a, key="b")')
    assert name == "myworkflow"
    assert pos == ["a"]
    assert named == {"key": "b"}


# Tests for _format_as_text_block


# Tests for _preprocess_paren_shorthand


def test_paren_shorthand_multiline_double_newline() -> None:
    """Test paren shorthand with multiline text terminated by \\n\\n."""
    result = _preprocess_paren_shorthand("#test(arg1): line1\nline2\n\nother", {"test"})
    assert result == "#test(arg1, [[line1\n  line2]])\n\nother"


def test_paren_shorthand_unknown_name() -> None:
    """Test unknown names are not processed."""
    prompt = "#unknown(arg): hello"
    result = _preprocess_paren_shorthand(prompt, {"test"})
    assert result == "#unknown(arg): hello"


def test_paren_shorthand_mid_line() -> None:
    """Test paren shorthand matches mid-line after a space."""
    result = _preprocess_paren_shorthand("expanded #test(arg1): hello world", {"test"})
    assert result == "expanded #test(arg1, [[hello world]])"


# Tests for _find_double_colon_text_end


# Tests for simple double-colon shorthand


def test_double_colon_shorthand_terminated_by_next_directive() -> None:
    """Test double-colon text ends at the next directive."""
    prompt = "#foo:: line1\n\nline3\n#bar: other"
    result = preprocess_shorthand_syntax(prompt, {"foo", "bar"})
    assert result == "#foo([[line1\n\n  line3]])\n#bar([[other]])"


def test_double_colon_shorthand_unknown_name_ignored() -> None:
    """Test that unknown names are not processed for double-colon."""
    prompt = "#unknown:: some text"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    assert result == "#unknown:: some text"


# Tests for strip_hitl_suffix


def test_strip_hitl_suffix_double_bang() -> None:
    """Test strip_hitl_suffix with !! suffix returns True."""
    ref, override = strip_hitl_suffix("foo!!")
    assert ref == "foo"
    assert override is True


def test_strip_hitl_suffix_question_with_paren_args() -> None:
    """Test strip_hitl_suffix ?? with parenthesis args."""
    ref, override = strip_hitl_suffix("foo??(a, b)")
    assert ref == "foo(a, b)"
    assert override is False


# Tests for paren double-colon shorthand


def test_paren_double_colon_shorthand_empty_parens() -> None:
    """Test #name():: text → #name([[text]])."""
    result = _preprocess_paren_shorthand("#test():: hello world", {"test"})
    assert result == "#test([[hello world]])"


# Tests for mixed directives


# Tests for extract_vcs_workflow_tag

# Build a test pattern that matches #gh, #hg, #git tags
_TEST_VCS_PATTERN = re.compile(
    r"^#(?:gh|git|hg)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s"
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


def test_extract_vcs_workflow_tag_hg_hitl() -> None:
    """Test extracting a VCS tag with !! HITL suffix."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#hg!!:cl Fix it") == "#hg!!:cl "


def test_extract_vcs_workflow_tag_git_paren() -> None:
    """Test extracting a VCS tag with parenthesis args."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("#git(repo) Do stuff") == "#git(repo) "


def test_extract_vcs_workflow_tag_with_directives() -> None:
    """Test that %directive lines are skipped before VCS tag."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%plan\n#gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_extract_vcs_workflow_tag_multiple_directives() -> None:
    """Test skipping multiple %directive lines."""
    with _patch_vcs_pattern():
        result = extract_vcs_workflow_tag("%plan\n%fast\n#gh:sase Fix the bug")
        assert result == "#gh:sase "


def test_extract_vcs_workflow_tag_no_tag() -> None:
    """Test returns None when no VCS tag is present."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("Just a normal prompt") is None


def test_extract_vcs_workflow_tag_directive_only() -> None:
    """Test returns None when prompt is only a directive with no newline."""
    with _patch_vcs_pattern():
        assert extract_vcs_workflow_tag("%plan") is None


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
        result = extract_vcs_workflow_tag("%plan\n%n:a #gh:sase Fix the bug")
        assert result == "#gh:sase "


# Tests for replace_ref_in_vcs_tag


def test_replace_ref_in_vcs_tag_colon() -> None:
    """Test replacing ref in colon format: #gh:sase → #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh:sase ", "sase_foobar_1") == "#gh:sase_foobar_1 "


def test_replace_ref_in_vcs_tag_paren() -> None:
    """Test replacing ref in parenthesized format: #git(repo) → #git(new_branch)."""
    assert replace_ref_in_vcs_tag("#git(repo) ", "new_branch") == "#git(new_branch) "


def test_replace_ref_in_vcs_tag_hitl_bang() -> None:
    """Test that !! HITL suffix is stripped: #gh!!:sase → #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh!!:sase ", "new_branch") == "#gh:new_branch "


def test_replace_ref_in_vcs_tag_hitl_question() -> None:
    """Test that ?? HITL suffix is stripped: #hg??:cl → #hg:new_branch."""
    assert replace_ref_in_vcs_tag("#hg??:cl ", "new_branch") == "#hg:new_branch "


def test_replace_ref_in_vcs_tag_underscore() -> None:
    """Test replacing ref in underscore format: #gh_sase → #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh_sase ", "sase_foobar_1") == "#gh:sase_foobar_1 "


def test_replace_ref_in_vcs_tag_bare() -> None:
    """Test replacing ref on bare tag: #gh → #gh:new_branch."""
    assert replace_ref_in_vcs_tag("#gh ", "new_branch") == "#gh:new_branch "


# Tests for normalize_vcs_underscore_refs


def _patch_workflow_names(names: set[str]):
    """Patch get_workflow_names to return *names*."""
    return patch(
        "sase.workspace_provider.get_workflow_names",
        return_value=names,
    )


def test_normalize_vcs_underscore_basic() -> None:
    """Test #gh_sase → #gh:sase."""
    # Reset cached normalizer so the patched names take effect
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "hg"}):
        assert normalize_vcs_underscore_refs("#gh_sase Fix bug") == "#gh:sase Fix bug"


def test_normalize_vcs_underscore_git() -> None:
    """Test #git_myrepo → #git:myrepo."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "hg"}):
        assert (
            normalize_vcs_underscore_refs("#git_myrepo Do stuff")
            == "#git:myrepo Do stuff"
        )


def test_normalize_vcs_underscore_not_vcs() -> None:
    """Test non-VCS underscore names like #my_xprompt are NOT normalized."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "hg"}):
        assert normalize_vcs_underscore_refs("#my_xprompt hello") == "#my_xprompt hello"


def test_normalize_vcs_underscore_preserves_colon() -> None:
    """Test #gh:sase is left unchanged."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "hg"}):
        assert normalize_vcs_underscore_refs("#gh:sase Fix bug") == "#gh:sase Fix bug"


def test_normalize_vcs_underscore_mid_line() -> None:
    """Test normalization works after whitespace mid-line."""
    import sase.xprompt._parsing as _mod

    _mod._VCS_UNDERSCORE_NORMALIZER = None
    with _patch_workflow_names({"gh", "git", "hg"}):
        assert (
            normalize_vcs_underscore_refs("text #gh_sase prompt")
            == "text #gh:sase prompt"
        )


# Tests for strip_vcs_workflow_tag


# Tests for replace_vcs_workflow_tags

_TEST_VCS_REPLACE_PATTERN = re.compile(
    r"^((?:%\S+[\s]+)*)#(?:gh|git|hg)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s",
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
        result = replace_vcs_workflow_tags("%n:a #gh:sase Fix bug", "#gh:other")
        assert result == "%n:a #gh:other Fix bug"


def test_replace_vcs_tags_with_directives_multi_line() -> None:
    """Preserve multi-line directives before VCS tag."""
    prompt = "%plan\n%n:a #gh:sase Fix bug"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "%plan\n%n:a #gh:other Fix bug"


def test_replace_vcs_tags_multi_prompt_with_directives() -> None:
    """Replace VCS tags in multi-prompt where segments have directives."""
    prompt = "%n:a #gh:sase Fix A\n---\n%n:b #gh:sase Fix B"
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags(prompt, "#gh:other")
        assert result == "%n:a #gh:other Fix A\n---\n%n:b #gh:other Fix B"


def test_replace_vcs_tags_no_existing_tag() -> None:
    """Prepend VCS prefix when prompt has no existing VCS tag."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("Fix the bug", "#gh:sase")
        assert result == "#gh:sase Fix the bug"


def test_replace_vcs_tags_hitl_modifier() -> None:
    """Replace a VCS tag that has !! (HITL) modifier."""
    with _patch_vcs_replace_pattern():
        result = replace_vcs_workflow_tags("#hg!!:cl Fix it", "#gh:sase")
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
