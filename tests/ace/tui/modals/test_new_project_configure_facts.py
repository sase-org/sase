"""Observed-fact adapter for Configure-stage display plans."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase.ace.tui.modals.new_project_configure_facts import (
    assemble_configure_facts,
    checkout_facts_from_source,
    matching_project_record,
    remote_facts_from_probe,
)
from sase.ace.tui.modals.new_project_configure_model import (
    ConfigureDraft,
    build_setup_card,
    plan_configure_display,
)
from sase.project_onboarding.facts import gather_facts
from sase.workspace_provider._hookspec import ParsedRepoRef, WorkflowMetadata


def _probe(**overrides: Any) -> SimpleNamespace:
    values = {
        "status": "found",
        "visibility": "private",
        "is_empty": False,
        "is_archived": False,
        "can_push": True,
        "sase_managed": False,
        "repo_id": "1",
        "default_branch": "main",
        "message": "",
        "web_url": "https://github.com/sase-org/bob",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _target() -> dict[str, Any]:
    return {
        "workflow_type": "gh",
        "ref": "sase-org/bob",
        "identity_key": "github.com/sase-org/bob",
        "checkout_dir": "/tmp/bob",
        "project_key_base": "gh_sase-org__bob",
        "project_name_base": "bob",
    }


@pytest.fixture
def local_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    def parse(workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "gh" or "/" not in text:
            return None
        owner, name = text.split("/", 1)
        return ParsedRepoRef(
            workflow_type="gh",
            ref=text,
            identity_key=f"github.com/{text}".casefold(),
            display=text,
            host="github.com",
            owner=owner,
            name=name,
            project_key_base=f"gh_{owner}__{name}",
            project_name_base=name,
            checkout_dir=f"/tmp/{name}",
            web_url=f"https://github.com/{text}",
        )

    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: (
            WorkflowMetadata(
                workflow_type="gh",
                ref_pattern="",
                display_name="GitHub",
                pre_allocated_env_prefix="",
                sdd_storage_policy="separate_repo",
            ),
        ),
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parse)
    monkeypatch.setattr(
        workspace_provider, "get_display_name", lambda workflow_type: "GitHub"
    )


def test_missing_probe_omits_remote() -> None:
    facts = assemble_configure_facts(
        records=[],
        probe=None,
        identity_key="github.com/sase-org/bob",
        source_group="suggested",
        checkout_dir="",
    )
    assert "remote" not in facts
    assert "checkout" not in facts
    assert facts["projects"] == []


def test_local_group_adds_matching_checkout() -> None:
    checkout = checkout_facts_from_source(group="local", checkout_dir="/tmp/bob")
    assert checkout is not None
    assert checkout["state"] == "matching"


def test_matching_record_is_case_insensitive() -> None:
    records = [
        {
            "key": "old",
            "name": "old",
            "aliases": [],
            "state": "disabled",
            "identity_keys": ["github.com/sase-org/bob"],
        }
    ]
    match = matching_project_record(records, "GitHub.com/sase-org/bob")
    assert match is not None
    assert match["state"] == "disabled"


def test_remote_probe_copies_planner_fields() -> None:
    remote = remote_facts_from_probe(_probe(can_push=False, sase_managed=True))
    assert remote is not None
    assert remote["can_push"] is False
    assert remote["sase_managed"] is True
    assert remote["status"] == "found"


def test_no_push_display_plan_uses_observed_remote(
    local_planner: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

    def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("display planning must not gather facts")

    monkeypatch.setattr("sase.project_onboarding.planning.gather_facts", boom)
    facts = assemble_configure_facts(
        records=[],
        probe=_probe(can_push=False, sase_managed=False),
        identity_key="github.com/sase-org/bob",
        source_group="suggested",
        checkout_dir="/tmp/bob",
    )
    document = plan_configure_display(_target(), ConfigureDraft(name="bob"), facts)
    card = build_setup_card(document, ConfigureDraft())
    assert card.checked is False
    assert card.reason_style == "amber"
    assert card.follow_up == "sase init -M"


def test_managed_display_plan_hides_checkbox(
    local_planner: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    facts = assemble_configure_facts(
        records=[],
        probe=_probe(can_push=True, sase_managed=True),
        identity_key="github.com/sase-org/bob",
        source_group="suggested",
        checkout_dir="/tmp/bob",
    )
    document = plan_configure_display(_target(), ConfigureDraft(name="bob"), facts)
    card = build_setup_card(document, ConfigureDraft())
    assert card.show_checkbox is False


def test_gather_facts_is_unused_by_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.project_onboarding.facts.gather_facts",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("gather")),
    )
    assemble_configure_facts(
        records=[{"key": "k", "name": "n", "aliases": [], "state": "enabled"}],
        probe=_probe(),
        identity_key="github.com/sase-org/bob",
        source_group="local",
        checkout_dir="/tmp/bob",
    )
    assert gather_facts is not None
