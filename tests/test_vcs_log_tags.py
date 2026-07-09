"""Tests for ``sase vcs log --tags`` footer parsing helpers."""

from __future__ import annotations

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_log.tags import commit_tag_view


def _commit(body: str, subject: str = "feat: work") -> VcsCommitWire:
    return VcsCommitWire(
        full_id="a1b2c3d4",
        short_id="a1b2c3d",
        author_name="bryan",
        author_email="b@x",
        timestamp=300,
        subject=subject,
        body=body,
    )


def test_parses_trailing_sase_tag_block() -> None:
    view = commit_tag_view(
        _commit("body text\n\nSASE_TYPE=sdd\nSASE_PLAN=sdd/tales/foo.md")
    )

    assert view.tags == (
        ("TYPE", "sdd"),
        ("PLAN", "sdd/tales/foo.md"),
    )
    assert view.body == "body text"


def test_strips_only_sase_prefix_from_keys() -> None:
    view = commit_tag_view(_commit("SASE_AGENT=worker-1\nSASE_MACHINE=host-a"))

    assert view.tags == (("AGENT", "worker-1"), ("MACHINE", "host-a"))
    assert view.body == ""


def test_ignores_non_trailing_sase_text() -> None:
    body = "SASE_TYPE=sdd\n\nregular body after"

    view = commit_tag_view(_commit(body))

    assert view.tags == ()
    assert view.body == body


def test_ignores_legacy_unprefixed_footer_keys() -> None:
    body = "body text\n\nTYPE=sdd\nAGENT=worker-1"

    view = commit_tag_view(_commit(body))

    assert view.tags == ()
    assert view.body == body


def test_mixed_footer_displays_only_sase_tags_and_strips_block() -> None:
    view = commit_tag_view(_commit("body text\n\nTYPE=legacy\nSASE_TYPE=sdd"))

    assert view.tags == (("TYPE", "sdd"),)
    assert view.body == "body text"


def test_duplicate_sase_keys_keep_later_value() -> None:
    view = commit_tag_view(
        _commit("body text\n\nSASE_TYPE=old\nSASE_PLAN=plan.md\nSASE_TYPE=new")
    )

    assert view.tags == (("TYPE", "new"), ("PLAN", "plan.md"))
    assert view.body == "body text"
