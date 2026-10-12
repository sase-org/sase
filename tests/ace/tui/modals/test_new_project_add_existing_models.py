"""Textual-free add-existing models for the New Project wizard.

Covers the Configure cards, the plan-document to Review rows, the
``project.add`` submission keys, the NDJSON progress reducer, and the stage
machine through Ready and Failed. No widgets, no PNG, no subprocesses.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from sase import workspace_provider
from sase.ace.tui.modals.init_plan_modal_rendering import operation_glyph
from sase.ace.tui.modals.new_project_configure_model import (
    ConfigureDraft,
    build_project_card,
    build_setup_card,
    check_identity,
    validate_draft,
)
from sase.ace.tui.modals.new_project_progress_model import reduce_lines
from sase.ace.tui.modals.new_project_review_model import (
    apply_submission,
    build_review,
)
from sase.ace.tui.modals.new_project_state import NewProjectStateMachine
from sase.workspace_provider._hookspec import ParsedRepoRef, WorkflowMetadata


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "add",
        "status": "ready",
        "intent_fingerprint": "f" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/bob",
            "display": "sase-org/bob",
            "identity_key": "github.com/sase-org/bob",
            "web_url": "https://github.com/sase-org/bob",
            "visibility": "private",
            "default_branch": "main",
            "checkout_dir": "/tmp/bob",
            "can_push": True,
            "sase_managed": False,
        },
        "project": {
            "key": "gh_sase-org__bob",
            "name": "bob",
            "aliases": [],
            "accent": "#B9589C",
            "state": "enabled",
            "existing": False,
        },
        "setup": {
            "enabled": True,
            "code": "unmanaged_can_push",
            "reason": "needed before agents can launch here",
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "label": "Clone into /tmp/bob and register",
                "detail": "/tmp/bob",
                "state": "pending",
            },
            {
                "id": "manage",
                "operation": "create",
                "label": "Mark the repository as SASE-managed",
                "detail": "commit and push sase/sase.yml is_sase_managed",
                "state": "pending",
            },
            {
                "id": "init",
                "operation": "validate",
                "label": "Initialize SASE",
                "detail": "init preview; sidecar creation asks in a terminal",
                "state": "pending",
            },
        ],
        "warnings": [],
        "blockers": [],
        "apply_argv": ["sase", "project", "add", "sase-org/bob", "--yes", "--json"],
        "next_argv": ["sase", "init", "-p", "gh_sase-org__bob"],
    }
    document.update(overrides)
    return document


def _target() -> dict[str, Any]:
    return {
        "workflow_type": "gh",
        "provider_display": "GitHub",
        "storage_policy": "separate_repo",
        "ref": "sase-org/bob",
        "identity_key": "github.com/sase-org/bob",
        "display": "sase-org/bob",
        "host": "github.com",
        "owner": "sase-org",
        "name": "bob",
        "web_url": "https://github.com/sase-org/bob",
        "checkout_dir": "/tmp/bob",
        "project_key_base": "gh_sase-org__bob",
        "project_name_base": "bob",
    }


@pytest.fixture
def local_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan locally without provider hooks; facts carry only records."""

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


class TestProjectCard:
    def test_clone_pending_marks_will_clone(self) -> None:
        card = build_project_card(_document(), ConfigureDraft(name="bob"))
        assert card.will_clone is True
        assert card.checkout_line == "Will clone into /tmp/bob."
        assert card.key == "gh_sase-org__bob"
        assert card.reenable_note is None

    def test_matching_checkout_marks_existing(self) -> None:
        document = _document()
        document["steps"][0] = {**document["steps"][0], "state": "done"}
        card = build_project_card(document, ConfigureDraft(name="bob"))
        assert card.will_clone is False
        assert card.checkout_line == "Uses the existing checkout at /tmp/bob."

    def test_disabled_project_names_reenable(self) -> None:
        document = _document()
        document["project"] = {**document["project"], "state": "disabled"}
        card = build_project_card(document, ConfigureDraft(name="bob"))
        assert card.state == "disabled"
        assert card.reenable_note == "Adding re-enables this project."


class TestSetupCard:
    def test_recommended_setup_mirrors_planner(self) -> None:
        card = build_setup_card(_document(), ConfigureDraft())
        assert card.show_checkbox is True
        assert card.checked is True
        assert card.reason == "needed before agents can launch here"
        assert card.reason_style == ""
        assert card.follow_up is None
        assert card.note == "commit and push sase/sase.yml is_sase_managed"

    def test_setup_override_off_unchecks(self) -> None:
        card = build_setup_card(_document(), ConfigureDraft(setup_override="off"))
        assert card.checked is False
        assert card.note is None

    def test_already_managed_hides_checkbox(self) -> None:
        document = _document()
        document["target"] = {**document["target"], "sase_managed": True}
        document["setup"] = {
            "enabled": False,
            "code": "already_managed",
            "reason": "already SASE-managed",
        }
        card = build_setup_card(document, ConfigureDraft())
        assert card.show_checkbox is False
        assert card.checked is False
        assert card.note == "Sidecars connect on first launch."

    def test_bare_git_omits_sidecar_sentence(self) -> None:
        document = _document()
        document["provider"] = {"workflow_type": "git", "display": "Git (bare)"}
        document["target"] = {**document["target"], "sase_managed": True}
        document["setup"] = {
            "enabled": False,
            "code": "already_managed",
            "reason": "already SASE-managed",
        }
        card = build_setup_card(document, ConfigureDraft())
        assert card.show_checkbox is False
        assert card.note is None

    def test_no_push_rights_stays_unchecked_and_amber(self) -> None:
        document = _document()
        document["target"] = {**document["target"], "can_push": False}
        document["setup"] = {
            "enabled": False,
            "code": "no_push",
            "reason": "no push rights — run sase init -M",
        }
        card = build_setup_card(document, ConfigureDraft(setup_override="on"))
        assert card.checked is False
        assert card.reason_style == "amber"
        assert card.follow_up == "sase init -M"


class TestCheckIdentity:
    def test_unique_without_blockers(self) -> None:
        assert check_identity(_document()).status == "unique"

    def test_taken_names_the_holder(self) -> None:
        document = _document(
            status="blocked",
            blockers=[
                {
                    "code": "name_taken",
                    "message": "name bob is taken by bob-old",
                    "hint": "try bob_1",
                }
            ],
        )
        verdict = check_identity(document)
        assert verdict.status == "taken"
        assert "bob-old" in verdict.reason

    def test_invalid_name(self) -> None:
        document = _document(
            status="blocked",
            blockers=[{"code": "invalid_name", "message": "project key base is empty"}],
        )
        verdict = check_identity(document)
        assert verdict.status == "invalid"
        assert verdict.reason == "project key base is empty"


class TestValidateDraft:
    def test_taken_name_uses_planner_reason(
        self, local_planner: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
        document = validate_draft(
            _target(),
            ConfigureDraft(name="taken"),
            [{"key": "other", "name": "taken"}],
        )
        verdict = check_identity(document)
        assert verdict.status == "taken"
        assert "taken" in verdict.reason

    def test_unique_name_passes(
        self, local_planner: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
        document = validate_draft(_target(), ConfigureDraft(name="fresh"), [])
        assert check_identity(document).status == "unique"


class TestBuildReview:
    def test_fresh_add_rows_and_confirm(self) -> None:
        view = build_review(_document())
        assert [row.label for row in view.rows] == [
            "Clone into /tmp/bob and register",
            "Mark the repository as SASE-managed",
            "Initialize SASE",
        ]
        assert all(row.glyph for row in view.rows)
        assert view.can_confirm is True
        assert view.is_public is False
        assert view.argv_line == "sase project add sase-org/bob --yes --json"
        assert not any(row.label == "REMOTE" for row in view.rows)

    def test_skipped_steps_are_omitted(self) -> None:
        document = _document()
        document["steps"] = [
            *document["steps"],
            {
                "id": "reenable",
                "operation": "update",
                "label": "Re-enable",
                "detail": "",
                "state": "skipped",
            },
        ]
        view = build_review(document)
        assert "Re-enable" not in [row.label for row in view.rows]

    def test_blocker_clears_confirm(self) -> None:
        document = _document(
            status="blocked",
            blockers=[
                {
                    "code": "checkout_conflict",
                    "message": "/tmp/bob is not a matching clone",
                    "hint": "choose a different path than /tmp/bob",
                }
            ],
        )
        view = build_review(document)
        assert view.can_confirm is False
        assert view.blockers[0].hint == "choose a different path than /tmp/bob"

    def test_warnings_and_public_flag(self) -> None:
        document = _document(
            warnings=[
                {"code": "not_launchable", "message": "agents cannot launch here yet"}
            ],
        )
        document["target"] = {**document["target"], "visibility": "PUBLIC"}
        view = build_review(document)
        assert view.warnings == ("agents cannot launch here yet",)
        assert view.is_public is True
        assert view.can_confirm is True

    def test_create_mode_keeps_remote_row(self) -> None:
        document = _document(mode="create")
        view = build_review(document)
        assert view.rows[0].label == "REMOTE"

    def test_operation_glyph_default(self) -> None:
        assert operation_glyph("create") == ("+", "green")
        assert operation_glyph("nope") == ("~", "yellow")


class TestApplySubmission:
    def test_submission_keys(self) -> None:
        document = _document(
            apply_argv=[
                "sase",
                "project",
                "add",
                "sase-org/bob",
                "--alias",
                "b1",
                "--alias",
                "b2",
                "--name",
                "bob",
                "--no-setup",
                "--make-current",
                "--yes",
                "--json",
            ]
        )
        submission = apply_submission(document)
        assert submission.argv == tuple(document["apply_argv"])
        assert submission.operation == "project.add"
        assert submission.request_fingerprint == "f" * 64
        assert submission.concurrency_keys == (
            "project-onboard:github.com/sase-org/bob",
            "checkout:/tmp/bob",
        )
        assert submission.request == {
            "mode": "add",
            "actor": "human",
            "target": {
                "ref": "sase-org/bob",
                "workflow_type": "gh",
                "identity_key": "github.com/sase-org/bob",
            },
            "requested": {
                "name": "bob",
                "aliases": ["b1", "b2"],
                "setup": "off",
                "make_current": True,
            },
        }
        assert "SASE_PROJECT_CREATE_BYPASS" not in submission.argv


class TestProgressReducer:
    def test_full_run_with_raw_line(self) -> None:
        plan = {
            "steps": [
                {"id": "checkout", "label": "Clone", "state": "pending"},
                {"id": "manage", "label": "Manage", "state": "skipped"},
            ]
        }
        lines = [
            json.dumps({"event": "plan", "plan": plan}),
            json.dumps({"event": "step", "id": "checkout", "status": "running"}),
            "not json at all",
            json.dumps({"event": "step", "id": "checkout", "status": "done"}),
            json.dumps(
                {
                    "event": "step",
                    "id": "manage",
                    "status": "failed",
                    "message": "no push",
                    "hint": "run sase init -M",
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "status": "partial",
                    "project": {"key": "k", "name": "n"},
                    "next_argv": ["sase", "init", "-p", "k"],
                    "message": "done-ish",
                }
            ),
        ]
        view = reduce_lines(lines)
        rows = {row.step_id: row for row in view.checklist()}
        assert rows["checkout"].state == "done"
        assert rows["manage"].state == "failed"
        assert rows["manage"].message == "no push"
        assert rows["manage"].hint == "run sase init -M"
        assert view.raw_log == ["not json at all"]
        assert view.result is not None
        assert view.result.status == "partial"
        assert view.result.project_key == "k"
        assert view.result.project_name == "n"
        assert view.result.next_argv == ("sase", "init", "-p", "k")
        assert view.result.message == "done-ish"

    def test_plan_seeding_marks_skipped(self) -> None:
        view = reduce_lines(
            [
                json.dumps(
                    {
                        "event": "plan",
                        "plan": {"steps": [{"id": "init", "state": "skipped"}]},
                    }
                )
            ]
        )
        assert view.checklist()[0].state == "skipped"
        assert view.result is None


class TestStageMachine:
    def test_ready_path_preserves_draft(self) -> None:
        machine = NewProjectStateMachine()
        draft = ConfigureDraft(name="bob")
        machine.to_configure()
        machine.set_draft(draft)
        machine.to_review()
        machine.back_to_configure()
        assert machine.draft == draft
        machine.to_review()
        machine.to_progress()
        machine.finish_ready()
        assert machine.stage == "ready"
        assert machine.draft == draft

    def test_failed_path_returns_to_review(self) -> None:
        machine = NewProjectStateMachine()
        draft = ConfigureDraft(name="bob")
        machine.to_configure()
        machine.set_draft(draft)
        machine.to_review()
        machine.to_progress()
        machine.finish_failed()
        assert machine.stage == "failed"
        machine.back_to_review()
        assert machine.stage == "review"
        assert machine.draft == draft
        machine.to_progress()
        machine.finish_failed()
        machine.replan()
        assert machine.stage == "review"
        assert machine.draft == draft

    def test_configure_back_to_source(self) -> None:
        machine = NewProjectStateMachine()
        machine.to_configure()
        machine.back_to_source()
        assert machine.stage == "source"
