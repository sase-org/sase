"""Tests for strip_pr_tags()."""

from sase.vcs_provider.config import strip_pr_tags


def test_no_tags() -> None:
    desc = "Fix the login bug\n\nThis resolves the auth issue."
    assert strip_pr_tags(desc) == desc


def test_tags_at_end() -> None:
    desc = "Fix the login bug\n\nAUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT\nMARKDOWN=true"
    assert strip_pr_tags(desc) == "Fix the login bug"


def test_tags_with_trailing_blank_lines() -> None:
    desc = "Fix the login bug\n\nR=startblock\nWANT_LGTM=all\n\n"
    assert strip_pr_tags(desc) == "Fix the login bug"


def test_only_tags() -> None:
    desc = "AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT\nMARKDOWN=true"
    assert strip_pr_tags(desc) == ""


def test_mixed_content_then_tags() -> None:
    desc = "Add feature X\n\nSome details here.\n\nR=reviewer\nWANT_LGTM=all"
    assert strip_pr_tags(desc) == "Add feature X\n\nSome details here."


def test_empty_string() -> None:
    assert strip_pr_tags("") == ""


def test_non_tag_uppercase_lines_preserved() -> None:
    desc = "Fix bug\n\nNOTE: this is important"
    assert strip_pr_tags(desc) == desc


def test_tag_like_line_in_middle_not_stripped() -> None:
    desc = "Fix bug\n\nAUTO=yes\n\nMore text after"
    assert strip_pr_tags(desc) == desc


def test_single_tag() -> None:
    desc = "Update docs\n\nMARKDOWN=true"
    assert strip_pr_tags(desc) == "Update docs"


def test_tags_separated_by_blank_line() -> None:
    desc = (
        "Fix bug\n\n"
        "BUG=483686843\n\n"
        "AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT\n"
        "R=startblock\n"
        "MARKDOWN=true"
    )
    assert strip_pr_tags(desc) == "Fix bug"


def test_multiple_blank_line_separated_tag_groups() -> None:
    desc = "Fix bug\n\nBUG=483686843\n\nFIXES=123\n\nR=startblock\nWANT_LGTM=all"
    assert strip_pr_tags(desc) == "Fix bug"
