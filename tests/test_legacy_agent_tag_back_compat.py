"""Back-compat guard for member-name ``SASE_AGENT=`` commit footers.

Commit provenance is anchored on the agent *lane*, so new footers spell a
family member's commits with the family container's name and link the family
page without a ``#member-<role>`` anchor.  History is never rewritten, though,
so every reader must keep understanding the member-anchored footer that
commits made before that change still carry.

The fixture below is a verbatim legacy footer; each test drives one reader
that this epic touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.revert_agent_discovery import agent_tag_matches
from sase.axe.image_attachments import _agent_tag_matches
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.vcs_log._tag_style import inline_tag_text
from sase.vcs_log.tags import commit_tag_view
from sase.core.vcs_log_wire import VcsCommitWire
from sase.workflows.commit.pr_operations import build_pr_body
from sase.workflows.commit.runtime_tags import (
    parse_trailing_commit_tag_values,
    parse_trailing_commit_tags,
)

_LEGACY_LABEL = "bbugyi200.athena.pc--code"
_LEGACY_DESTINATION = (
    "https://github.com/sase-org/sase--agents/blob/main/"
    "families/bbugyi200.athena.pc.md#member-code"
)
_LEGACY_MESSAGE = (
    "feat: legacy member commit\n\n"
    f"SASE_AGENT=[{_LEGACY_LABEL}][2]\n"
    "SASE_TYPE=sdd\n\n"
    f"[2]: {_LEGACY_DESTINATION}"
)
_IDENTITY = AgentIdentitySnapshot(AgentOwnerIdentity("bbugyi200", "athena"))


def test_legacy_footer_parses_to_the_member_label_and_anchor() -> None:
    values = parse_trailing_commit_tag_values(_LEGACY_MESSAGE)

    agent = values["AGENT"]

    assert isinstance(agent, LinkedCommitTagValue)
    assert agent.label == _LEGACY_LABEL
    assert agent.destination == _LEGACY_DESTINATION
    assert parse_trailing_commit_tags(_LEGACY_MESSAGE)["AGENT"] == _LEGACY_LABEL


def test_legacy_footer_still_attributes_image_attachments() -> None:
    # Both the member that made the commit and any of its lane-mates.
    assert _agent_tag_matches(_LEGACY_LABEL, "pc--code", _IDENTITY)
    assert _agent_tag_matches(_LEGACY_LABEL, "pc--plan", _IDENTITY)
    assert not _agent_tag_matches(_LEGACY_LABEL, "other--code", _IDENTITY)


def test_legacy_footer_still_matches_revert_targets() -> None:
    assert agent_tag_matches(_LEGACY_LABEL, _LEGACY_LABEL, None)
    assert agent_tag_matches("pc--code", "pc--plan", "pc")
    assert not agent_tag_matches("pc--code", "other--plan", "other")


def test_legacy_footer_still_renders_the_pr_body_agent_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "pc--code"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = {"message": _LEGACY_MESSAGE}

    build_pr_body(payload)

    assert f"**Agent:** [{_LEGACY_LABEL}]({_LEGACY_DESTINATION})" in payload["_pr_body"]


def test_legacy_footer_still_renders_in_the_vcs_log_tag_chip() -> None:
    view = commit_tag_view(
        VcsCommitWire(
            full_id="a1b2c3d4",
            short_id="a1b2c3d",
            author_name="bryan",
            author_email="b@x",
            timestamp=300,
            subject="feat: legacy member commit",
            body=_LEGACY_MESSAGE.split("\n\n", 1)[1],
        )
    )

    assert ("AGENT", _LEGACY_LABEL) in view.tags
    assert _LEGACY_LABEL in inline_tag_text(view.tags).plain
