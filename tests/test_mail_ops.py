"""Tests for mail_ops module."""

from sase.ace.mail_ops import (
    MailPrepResult,
    _modify_description_for_mailing,
)


def test_mail_prep_result_should_mail_true() -> None:
    """Test MailPrepResult dataclass with should_mail=True."""
    result = MailPrepResult(should_mail=True)
    assert result.should_mail is True


def test_mail_prep_result_should_mail_false() -> None:
    """Test MailPrepResult dataclass with should_mail=False."""
    result = MailPrepResult(should_mail=False)
    assert result.should_mail is False


def test_modify_description_one_reviewer_with_parent() -> None:
    """Test scenario 2: 1 reviewer, valid parent.

    When there's a valid parent, R= should remain as "R=startblock" and the
    reviewer will be added later by the startblock system.
    """
    description = """This is a test CL.

R=startblock
Bug: b/12345
Test: manual"""

    result = _modify_description_for_mailing(description, ["reviewer1"], True, "123456")

    assert "R=startblock" in result
    assert "R=reviewer1,startblock" not in result  # Should NOT add reviewer to R= tag
    assert "### Startblock Conditions" in result
    assert "cl/123456 has LGTM" in result
    assert "add reviewer reviewer1" in result
    assert "Bug: b/12345" in result


def test_modify_description_two_reviewers_no_parent() -> None:
    """Test scenario 3: 2 reviewers, no valid parent."""
    description = """This is a test CL.

R=startblock
Bug: b/12345
Test: manual"""

    result = _modify_description_for_mailing(
        description, ["reviewer1", "reviewer2"], False, None
    )

    assert "R=reviewer1,startblock" in result
    assert "### Startblock Conditions" in result
    assert "has LGTM from reviewer1" in result
    assert "add reviewer reviewer2" in result
    assert "Bug: b/12345" in result


def test_modify_description_two_reviewers_with_parent() -> None:
    """Test scenario 4: 2 reviewers, valid parent."""
    description = """This is a test CL.

R=startblock
Bug: b/12345
Test: manual"""

    result = _modify_description_for_mailing(
        description, ["reviewer1", "reviewer2"], True, "123456"
    )

    assert "### Startblock Conditions" in result
    assert "cl/123456 has LGTM" in result
    assert "add reviewer reviewer1" in result
    assert "has LGTM from reviewer1" in result
    assert "add reviewer reviewer2" in result
    assert "Bug: b/12345" in result


def test_modify_description_preserves_tags() -> None:
    """Test that tags are preserved at the end of description."""
    description = """This is a test CL.

R=startblock
Bug: b/12345
Test: manual
Change-Id: I1234567890abcdef"""

    result = _modify_description_for_mailing(description, ["reviewer1"], False, None)

    assert "Bug: b/12345" in result
    assert "Test: manual" in result
    assert "Change-Id: I1234567890abcdef" in result
    # Tags should be at the end
    lines = result.split("\n")
    assert "Change-Id:" in lines[-1]
