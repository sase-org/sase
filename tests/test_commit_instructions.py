"""Tests for shared commit finalizer instruction helpers."""

from __future__ import annotations

import pytest

from sase.commit_instructions import (
    build_commit_details,
    build_commit_instruction_message,
)


def test_commit_instruction_non_pr_method_includes_scope_restriction() -> None:
    """Non-PR methods must constrain commit message scope to current commit."""
    message = build_commit_instruction_message("/sase_git_commit", "create_commit")
    assert "The commit method type is `create_commit`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


def test_commit_instruction_pr_method_omits_scope_restriction() -> None:
    """PR method should not include non-PR commit message scope constraints."""
    message = build_commit_instruction_message(
        "/sase_git_commit", "create_pull_request"
    )
    assert "The commit method type is `create_pull_request`." in message
    assert "describe only the changes in this commit" not in message
    assert "Do NOT describe the entire pull request" not in message


def test_commit_instruction_unknown_method_defaults_to_scope_restriction() -> None:
    """Unknown methods should use non-PR scope guidance by default."""
    message = build_commit_instruction_message("/sase_git_commit", "unexpected_method")
    assert "The commit method type is `unexpected_method`." in message
    assert "describe only the changes in this commit" in message
    assert "Do NOT describe the entire pull request" in message


@pytest.mark.parametrize(
    "method", ["create_commit", "create_proposal", "create_pull_request"]
)
def test_commit_instruction_includes_method_override_warning(method: str) -> None:
    """Instruction text must warn agents not to override the stated method."""
    message = build_commit_instruction_message("/sase_git_commit", method)
    assert "Do NOT pass a --type value that conflicts" in message
    assert f"--type {method}" in message


def test_commit_instruction_requires_completing_commit_within_response() -> None:
    """Instruction text must state the commit must finish within this response."""
    message = build_commit_instruction_message("/sase_git_commit", "create_commit")
    assert (
        "Complete the commit within this response: ending the response without "
        "committing ends the run." in message
    )


def test_commit_instruction_describes_stage_everything_default() -> None:
    """Finalizer-triggered commits stage everything by default; -x opts out."""
    message = build_commit_instruction_message("/sase_git_commit", "create_commit")
    assert "stages every change in that repository by default" in message
    assert "including newly created untracked files" in message
    assert "Pass `-x <path>` (repeatable) only when a specific path" in message
    assert "Do not preemptively stash, pull, fast-forward, or hand-sync" in message


def test_commit_instruction_includes_bead_close_when_bead_id_is_set() -> None:
    """SASE_BEAD_ID should close the bead before invoking the commit skill."""
    message = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "  sase-2d.4  "
    )
    assert "If you DID make these changes" in message
    assert message.index("sase bead close sase-2d.4") < message.index(
        "using your /sase_git_commit skill"
    )
    assert "using your /sase_git_commit skill" in message
    assert "sase bead close sase-2d.4" in message
    assert '--note "<what you verified>"' in message
    assert "before invoking the commit skill" in message


def test_commit_instruction_points_bead_verification_at_published_state() -> None:
    """The close command, not a local re-read, is the close verification."""
    message = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "sase-2d.4"
    )
    assert "That command is itself the verification" in message
    assert "was committed locally but NOT published" in message
    assert "Do NOT confirm the close by re-reading bead `sase-2d.4`" in message
    assert "reads the same local store the close just wrote" in message
    assert "remediation command in that diagnostic" in message


def test_commit_instruction_gates_bead_close_on_agent_ownership() -> None:
    """Bead closure must be explicit only for changes this agent made."""
    message = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "sase-2d.4"
    )
    ownership_gate = "If you DID make these changes"
    bead_close = "sase bead close sase-2d.4"
    assert (
        "First decide whether the listed uncommitted changes were made by you"
        in message
    )
    assert (
        "If you did NOT make these changes, ignore this warning for the session"
        in message
    )
    assert message.index(ownership_gate) < message.index(bead_close)


def test_commit_instruction_omits_bead_close_when_bead_id_is_unset() -> None:
    """Unset or blank bead IDs must not mention bead closure."""
    message = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "   "
    )
    assert "sase bead close" not in message
    assert "bead `" not in message


def test_build_commit_details_clean_returns_empty() -> None:
    """When the changed-file helper reports clean, details are empty."""
    has, files, instr, details = build_commit_details(
        "/some/dir",
        get_changed_files=lambda _: (False, []),
    )
    assert has is False
    assert files == []
    assert instr == ""
    assert details == ""


def test_build_commit_details_matches_finalizer_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public helper emits the instruction consumed by the finalizer."""
    monkeypatch.delenv("SASE_BEAD_ID", raising=False)

    has, files, instr, details = build_commit_details(
        "/some/dir",
        commit_method="create_commit",
        bead_id=None,
        get_changed_files=lambda _: (True, ["src/x.py", "src/y.py"]),
        resolve_commit_skill=lambda _: "/sase_git_commit",
        build_name_instruction=lambda: None,
    )
    expected_instr = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", None
    )
    assert has is True
    assert files == ["src/x.py", "src/y.py"]
    assert instr == expected_instr
    assert details == (
        "Uncommitted changes detected:\nsrc/x.py\nsrc/y.py\n\n" + expected_instr
    )


def test_build_commit_details_appends_name_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR name guidance is appended to the finalizer commit instruction."""
    monkeypatch.delenv("SASE_BEAD_ID", raising=False)

    has, files, instr, details = build_commit_details(
        "/some/dir",
        commit_method="create_pull_request",
        bead_id=None,
        get_changed_files=lambda _: (True, ["src/x.py"]),
        resolve_commit_skill=lambda _: "/sase_git_commit",
        build_name_instruction=lambda: "Use the configured PR name.",
    )

    assert has is True
    assert files == ["src/x.py"]
    assert instr.endswith(" Use the configured PR name.")
    assert details.endswith(instr)
