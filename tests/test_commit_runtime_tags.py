"""Tests for runtime commit provenance tags."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.runtime_tags import (
    RUNTIME_COMMIT_TAG_KEYS,
    _resolve_runtime_commit_tags,
    apply_auto_commit_tags_with_runtime,
    apply_auto_commit_type_tag,
    filter_runtime_owned_tags,
    parse_trailing_commit_tags,
    update_trailing_commit_tags,
)
from sase.workflows.commit.workflow import CommitWorkflow, RunResult

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_HOSTNAME_TARGET = "sase.workflows.commit.runtime_tags.socket.gethostname"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


@pytest.fixture(autouse=True)
def _clean_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_PLAN",
        "SASE_BUG_ID",
        "HOSTNAME",
    ):
        monkeypatch.delenv(name, raising=False)


def test_runtime_tags_use_sase_agent_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    with patch(_HOSTNAME_TARGET, return_value="machine-a"):
        assert _resolve_runtime_commit_tags() == {
            "AGENT": "agent-alpha",
            "MACHINE": "machine-a",
        }


def test_runtime_tags_fall_back_to_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "agent-meta"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    with patch(_HOSTNAME_TARGET, return_value="machine-a"):
        assert _resolve_runtime_commit_tags() == {
            "AGENT": "agent-meta",
            "MACHINE": "machine-a",
        }


def test_runtime_tags_omit_agent_when_no_name_exists() -> None:
    with patch(_HOSTNAME_TARGET, return_value="machine-a"):
        assert _resolve_runtime_commit_tags() == {"MACHINE": "machine-a"}


def test_runtime_tags_sanitize_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "  agent\nalpha  ")
    with patch(_HOSTNAME_TARGET, return_value=" machine\rhost "):
        assert _resolve_runtime_commit_tags() == {
            "AGENT": "agent alpha",
            "MACHINE": "machine host",
        }


def test_update_trailing_tags_adds_runtime_tags() -> None:
    assert (
        update_trailing_commit_tags(
            "Fix bug",
            {"AGENT": "agent-a", "MACHINE": "machine-a"},
            remove_keys=RUNTIME_COMMIT_TAG_KEYS,
        )
        == "Fix bug\n\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_update_trailing_tags_preserves_existing_metadata() -> None:
    assert update_trailing_commit_tags(
        "Fix bug\n\nPLAN=sdd/plans/plan.md\nBUG=123",
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    ) == (
        "Fix bug\n\nSASE_PLAN=sdd/plans/plan.md\nSASE_BUG=123"
        "\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_update_trailing_tags_replaces_stale_runtime_tags() -> None:
    message = "Fix bug\n\nBUG=123\nAGENT=old-agent\nMACHINE=old-machine"

    updated = update_trailing_commit_tags(
        message,
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert (
        updated == "Fix bug\n\nSASE_BUG=123\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )
    assert "old-agent" not in updated
    assert "old-machine" not in updated
    assert updated.count("AGENT=") == 1
    assert updated.count("MACHINE=") == 1


def test_update_trailing_tags_render_every_owned_builtin_prefixed() -> None:
    """TYPE, AGENT, MACHINE, PLAN, and BUG all render with the SASE_ prefix."""
    updated = update_trailing_commit_tags(
        "Fix bug",
        {
            "TYPE": "sdd",
            "AGENT": "agent-a",
            "MACHINE": "machine-a",
            "PLAN": "sdd/plans/plan.md",
            "BUG": "123",
        },
    )

    assert updated == (
        "Fix bug\n\nSASE_TYPE=sdd\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
        "\nSASE_PLAN=sdd/plans/plan.md\nSASE_BUG=123"
    )


def test_update_trailing_tags_prefixed_input_key_is_not_double_prefixed() -> None:
    """An already-prefixed input key renders once, replacing the legacy alias."""
    updated = update_trailing_commit_tags(
        "Fix bug\n\nTYPE=old",
        {"SASE_TYPE": "new"},
        remove_keys={"SASE_TYPE"},
    )

    assert updated == "Fix bug\n\nSASE_TYPE=new"
    assert "SASE_SASE_TYPE" not in updated
    assert "TYPE=old" not in updated


def test_update_trailing_tags_removes_legacy_and_prefixed_aliases() -> None:
    """Updating an owned key drops both spellings already present in the block."""
    updated = update_trailing_commit_tags(
        "Fix bug\n\nTYPE=legacy\nSASE_TYPE=stale\nTEAM=infra",
        {"TYPE": "fresh"},
        remove_keys={"TYPE"},
    )

    assert updated == "Fix bug\n\nSASE_TEAM=infra\nSASE_TYPE=fresh"
    assert updated.count("TYPE=") == 1
    assert "TYPE=legacy" not in updated
    assert "SASE_TYPE=stale" not in updated


def test_auto_commit_type_tag_adds_type() -> None:
    assert apply_auto_commit_type_tag("Fix bug", "sdd") == "Fix bug\n\nSASE_TYPE=sdd"


def test_auto_commit_type_tag_replaces_stale_type_and_preserves_other_tags() -> None:
    updated = apply_auto_commit_type_tag(
        "Fix bug\n\nBUG=123\nTYPE=old\nTEAM=infra",
        "bead_work",
    )

    assert updated == "Fix bug\n\nSASE_BUG=123\nSASE_TEAM=infra\nSASE_TYPE=bead_work"
    assert "TYPE=old" not in updated


def test_auto_commit_type_tag_composes_with_runtime_tags_without_owning_type() -> None:
    message = apply_auto_commit_type_tag("Fix bug", "sdd")

    updated = update_trailing_commit_tags(
        message,
        {"AGENT": "agent-a", "MACHINE": "machine-a"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )

    assert "TYPE" not in RUNTIME_COMMIT_TAG_KEYS
    assert updated == (
        "Fix bug\n\nSASE_TYPE=sdd\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"
    )


def test_auto_commit_tags_with_runtime_type_only_without_agent_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an agent identity, only ``TYPE=`` is written (no AGENT/MACHINE)."""
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    assert (
        apply_auto_commit_tags_with_runtime("Fix bug", "sdd")
        == "Fix bug\n\nSASE_TYPE=sdd"
    )


def test_auto_commit_tags_with_runtime_adds_agent_when_name_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_AGENT_NAME`` adds the runtime ``AGENT=`` provenance tag."""
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    monkeypatch.setattr(
        "sase.workflows.commit.runtime_tags.socket.gethostname",
        lambda: "machine-z",
    )

    updated = apply_auto_commit_tags_with_runtime("Fix bug", "sdd")

    tags = parse_trailing_commit_tags(updated)
    assert tags["TYPE"] == "sdd"
    assert tags["AGENT"] == "agent-alpha"
    assert tags["MACHINE"] == "machine-z"


def test_parse_trailing_commit_tags_reads_legacy_block() -> None:
    assert parse_trailing_commit_tags("Subject\n\nAGENT=foo\nTYPE=sdd") == {
        "AGENT": "foo",
        "TYPE": "sdd",
    }
    assert parse_trailing_commit_tags("Subject only") == {}


def test_parse_trailing_commit_tags_canonicalizes_prefixed_block() -> None:
    """New ``SASE_``-prefixed footer lines parse to canonical keys."""
    assert parse_trailing_commit_tags("Subject\n\nSASE_AGENT=foo\nSASE_TYPE=sdd") == {
        "AGENT": "foo",
        "TYPE": "sdd",
    }


def test_parse_trailing_commit_tags_prefixed_wins_over_legacy() -> None:
    """When both spellings are present, the later (prefixed) line wins."""
    assert parse_trailing_commit_tags("Subject\n\nAGENT=old\nSASE_AGENT=new") == {
        "AGENT": "new",
    }


def test_update_trailing_tags_keeps_body_text_intact() -> None:
    assert (
        update_trailing_commit_tags(
            "Fix bug\n\nBody line",
            {"MACHINE": "machine-a"},
            remove_keys=RUNTIME_COMMIT_TAG_KEYS,
        )
        == "Fix bug\n\nBody line\n\nSASE_MACHINE=machine-a"
    )


def test_filter_runtime_owned_tags() -> None:
    assert filter_runtime_owned_tags(
        {"TEAM": "infra", "AGENT": "old", "MACHINE": "old"}
    ) == {"TEAM": "infra"}


def test_filter_runtime_owned_tags_handles_prefixed_keys() -> None:
    """Runtime-owned keys are filtered in either spelling."""
    assert filter_runtime_owned_tags(
        {"SASE_TEAM": "infra", "SASE_AGENT": "old", "SASE_MACHINE": "old"}
    ) == {"SASE_TEAM": "infra"}


def _run_workflow(payload: dict, method: str, provider: MagicMock) -> RunResult:
    wf = CommitWorkflow(payload, method)
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch(
            "sase.workflows.commit.workflow.run_before_commit_hook", return_value=True
        ),
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook", return_value=True
        ),
        patch("sase.workflows.commit.workflow.resolve_cl_name", return_value=None),
        patch("sase.workflows.commit.workflow.resolve_project_file", return_value=None),
        patch(
            "sase.workflows.commit.workflow.capture_pre_commit_diff",
            return_value=None,
        ),
        patch("sase.workflows.commit.workflow.checkpoint_save"),
        patch("sase.workflows.commit.workflow.checkpoint_delete"),
        patch("sase.workflows.commit.workflow.append_commits_entry", return_value=None),
        patch("sase.workflows.commit.workflow.create_changespec", return_value=None),
        patch(_PROJECT_NAME_TARGET, return_value=None),
        patch(_PROVIDER_TARGET, return_value=provider),
    ):
        return wf.run()


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.create_commit.return_value = (True, "abc123")
    provider.create_proposal.return_value = (True, "proposal.diff")
    provider.create_pull_request.return_value = (True, "https://example.test/pr/1")
    return provider


def test_create_commit_provider_receives_runtime_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"message": "Fix bug"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with patch(_HOSTNAME_TARGET, return_value="machine-a"):
        assert _run_workflow(payload, "create_commit", provider) == RunResult.OK

    provider.create_commit.assert_called_once_with(payload, ANY)
    assert payload["message"] == "Fix bug\n\nSASE_AGENT=agent-a\nSASE_MACHINE=machine-a"


def test_create_pull_request_tags_override_inherited_runtime_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"name": "feat-x", "message": "Child PR"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-current")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "test", "model": "m1", "name": "agent-current"}),
        encoding="utf-8",
    )

    with (
        patch(_HOSTNAME_TARGET, return_value="machine-current"),
        patch(
            "sase.workflows.commit.pr_operations._fetch_parent_pr_tags",
            return_value={
                "TEAM": "infra",
                "AGENT": "agent-parent",
                "MACHINE": "machine-parent",
            },
        ),
        patch(
            "sase.vcs_provider.config.get_pr_tags",
            return_value={"MACHINE": "machine-config", "REVIEW": "true"},
        ),
    ):
        assert _run_workflow(payload, "create_pull_request", provider) == RunResult.OK

    provider.create_pull_request.assert_called_once_with(payload, ANY)
    message = payload["message"]
    assert "TEAM=infra" in message
    assert "REVIEW=true" in message
    assert "AGENT=agent-current" in message
    assert "MACHINE=machine-current" in message
    assert "agent-parent" not in message
    assert "machine-parent" not in message
    assert "machine-config" not in message
    assert "AGENT=agent-current" in payload["_pr_body"]
    assert "MACHINE=machine-current" in payload["_pr_body"]


def test_create_proposal_does_not_add_runtime_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"message": "Propose change"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with patch(_HOSTNAME_TARGET, return_value="machine-a"):
        assert _run_workflow(payload, "create_proposal", provider) == RunResult.OK

    provider.create_proposal.assert_called_once_with(payload, ANY)
    assert payload["message"] == "Propose change"
