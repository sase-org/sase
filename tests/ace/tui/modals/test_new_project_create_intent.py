"""Create checkout observation and plan-intent tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase import workspace_provider
from sase.ace.tui.modals import new_project_create as create
from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from ._new_project_create_helpers import fake_provider_fixture, probe, repo_form


def test_observe_checkout_reports_states_without_subprocesses(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.noninteractive_subprocess as noninteractive

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("checkout observation must not spawn subprocesses")

    monkeypatch.setattr(noninteractive, "run_noninteractive", _boom)
    base = {
        "identity_key": "github.com/sase-org/new",
        "workflow_type": "gh",
    }
    missing = tmp_path / "missing"
    assert create.observe_create_checkout(str(missing), **base)["state"] == "absent"
    assert create.observe_create_checkout("", **base)["state"] == "absent"
    occupied_file = tmp_path / "file"
    occupied_file.write_text("x")
    assert (
        create.observe_create_checkout(str(occupied_file), **base)["state"] == "not_git"
    )
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert (
        create.observe_create_checkout(str(empty_dir), **base)["state"] == "empty_dir"
    )
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    (plain_dir / "notes.txt").write_text("unrelated")
    assert create.observe_create_checkout(str(plain_dir), **base)["state"] == "not_git"


def test_observe_checkout_matches_origin_identity(
    tmp_path: Any, fake_provider: None
) -> None:
    checkout = tmp_path / "checkout"
    git_dir = checkout / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/sase-org/new.git\n'
    )
    matching = create.observe_create_checkout(
        str(checkout),
        identity_key="github.com/sase-org/new",
        workflow_type="gh",
    )
    assert matching["state"] == "matching"
    assert matching["origin_url"] == "https://github.com/sase-org/new.git"
    mismatch = create.observe_create_checkout(
        str(checkout),
        identity_key="github.com/sase-org/other",
        workflow_type="gh",
    )
    assert mismatch["state"] == "mismatch"


def test_lenient_options_omit_unavailable_controls() -> None:
    effective = create._lenient_effective_options(
        repo_form(), {"description": "hi", "readme": "true", "template": "sase-org/t"}
    )
    assert effective.get("template") == "sase-org/t"
    assert "readme" not in effective


def test_build_create_plan_request_preserves_complete_intent(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("gh", "sase-org", "new")
    request = create._build_create_plan_request(
        identity=identity,
        workflow_type="gh",
        provider_display="GitHub",
        project=ConfigureDraft(name="new", setup_override="auto"),
        visibility="private",
        summary=["Create sase-org/new"],
        effective_options={"description": "hi"},
    )
    assert request["mode"] == "create"
    assert request["actor"] == "human"
    assert request["target"]["ref"] == "sase-org/new"
    assert request["target"]["identity_key"] == "github.com/sase-org/new"
    assert request["requested"] == {
        "name": "new",
        "aliases": [],
        "setup": "auto",
        "make_current": False,
    }
    assert request["creation"] == {
        "visibility": "private",
        "summary": ["Create sase-org/new"],
    }
    assert request["options"] == {"description": "hi"}


def test_build_create_plan_request_reflects_bare_git_paths(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("git", "", "notes")
    request = create._build_create_plan_request(
        identity=identity,
        workflow_type="git",
        project=ConfigureDraft(name="notes"),
        visibility="private",
        effective_options={"checkout_dir": "/srv/checkouts/notes/"},
    )
    assert request["target"]["checkout_dir"] == "/srv/checkouts/notes/"


def test_plan_create_display_builds_mode_create_document(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("gh", "sase-org", "new")
    facts = create.assemble_create_facts(
        records=[],
        probe=probe("not_found"),
        identity_key=identity.identity_key,
        checkout={"state": "absent"},
    )
    document = create.plan_create_display(
        identity=identity,
        workflow_type="gh",
        provider_display="GitHub",
        project=ConfigureDraft(name="new"),
        visibility="private",
        effective_options={},
        facts=facts,
    )
    assert document["mode"] == "create"
    assert document["target"]["ref"] == "sase-org/new"
    verdict, _ = create._create_identity_verdict(document)
    assert verdict


def test_create_identity_verdict_reports_taken_and_invalid() -> None:
    ok, reason = create._create_identity_verdict({"blockers": []})
    assert (ok, reason) == (True, "")
    taken, taken_reason = create._create_identity_verdict(
        {"blockers": [{"code": "name_taken", "message": "Name is taken."}]}
    )
    assert not taken
    assert taken_reason == "Name is taken."
    invalid, invalid_reason = create._create_identity_verdict(
        {"blockers": [{"code": "invalid_name", "message": "Bad name."}]}
    )
    assert not invalid
    assert invalid_reason == "Bad name."


def test_add_instead_seed_preserves_canonical_target(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("gh", "sase-org", "new")
    seed = create._add_instead_seed(
        identity=identity, workflow_type="gh", provider_display="GitHub"
    )
    assert seed["ref"] == "sase-org/new"
    assert seed["identity_key"] == "github.com/sase-org/new"
    assert seed["checkout_dir"] == "/home/user/projects/github/sase-org/new/"
    assert seed["project_key_base"] == "gh_sase-org__new"
    assert seed["web_url"] == "https://github.com/sase-org/new"
