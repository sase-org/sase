"""Remote creation cases for onboarding apply."""

from __future__ import annotations

from typing import Any

import pytest

from sase import workspace_provider
from sase.main import project_handler_add as add_cli
from sase.main.parser import create_parser
from sase.project_onboarding.journal import lookup_journal
from sase.workspace_provider._hookspec import (
    RepoCreateResult,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)
from ._apply_test_support import (
    FakeGh,
    IDENTITY,
    request as make_request,
    run,
    step_ids,
)


def _create_request(checkout: str, **overrides: Any) -> dict[str, Any]:
    payload = make_request(
        checkout,
        mode="create",
        creation={"visibility": "private", "summary": []},
        options={"visibility": "private"},
    )
    payload["requested"] = {"setup": "off", "make_current": False}
    payload.update(overrides)
    return payload


class TestCreateRemote:
    def test_cli_explicit_false_options_reach_provider_create_hook(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        form = RepoCreationForm(
            workflow_type="gh",
            namespace="sase-org",
            fields=(
                RepoCreationField(
                    name="visibility",
                    label="Visibility",
                    kind="choice",
                    default="private",
                    choices=(
                        RepoCreationChoice(value="private", label="Private"),
                        RepoCreationChoice(value="public", label="Public"),
                    ),
                ),
                RepoCreationField(
                    name="issues", label="Issues", kind="bool", default="true"
                ),
                RepoCreationField(
                    name="wiki", label="Wiki", kind="bool", default="true"
                ),
            ),
            can_create=True,
        )
        monkeypatch.setattr(
            workspace_provider, "describe_repo_creation", lambda *_args: form
        )
        monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_kwargs: "human"
        )
        args = create_parser(only="project").parse_args(
            [
                "project",
                "create",
                "gh:sase-org/bob",
                "--no-setup",
                "--option",
                "issues=false",
                "--option",
                "wiki=false",
                "--yes",
                "--json",
            ]
        )

        assert add_cli.handle_create(args) == 0
        created_options = fake_gh.create_calls[0][2]
        assert created_options["issues"] == "false"
        assert created_options["wiki"] == "false"

    def test_intent_is_recorded_before_create_hook(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_k: "human"
        )
        seen: list[bool] = []
        original = fake_gh.create

        def wrapped(
            workflow_type: str, ref: str, options: dict[str, str]
        ) -> RepoCreateResult:
            journal = lookup_journal(IDENTITY)
            seen.append(
                journal is not None
                and journal.get("status") == "running"
                and bool(journal.get("remote"))
                and journal["remote"].get("created") is False
            )
            return original(workflow_type, ref, options)

        monkeypatch.setattr(workspace_provider, "create_repo", wrapped)
        result, events = run(_create_request(fake_gh.checkouts[IDENTITY]))
        assert seen == [True]
        assert result["status"] == "ok"
        assert "create_remote" in step_ids(events)
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["remote"]["created"] is True
        assert journal["remote"]["repo_id"] == "R1"

    def test_lost_response_does_not_adopt_without_evidence(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        fake_gh.is_empty = False
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_k: "human"
        )

        def boom(
            workflow_type: str, ref: str, options: dict[str, str]
        ) -> RepoCreateResult:
            del workflow_type, ref, options
            fake_gh.probe_status = "found"
            raise RuntimeError("connection lost after create")

        monkeypatch.setattr(workspace_provider, "create_repo", boom)
        checkout = fake_gh.checkouts[IDENTITY]
        first, _ = run(_create_request(checkout))
        assert first["status"] == "failed"
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["remote"]["created"] is False
        assert journal["remote"]["repo_id"] == ""

        second, _ = run(_create_request(checkout))
        assert second["status"] == "blocked"
        assert "add" in second["message"].casefold()

    def test_exists_without_evidence_is_remote_exists(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        fake_gh.create_status = "exists"
        fake_gh.is_empty = False
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_k: "human"
        )
        result, _ = run(_create_request(fake_gh.checkouts[IDENTITY]))
        assert result["status"] == "blocked"
        codes = [str(item.get("code") or "") for item in result.get("blockers") or []]
        assert "remote_exists" in codes
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["remote"]["created"] is False
        assert journal["status"] == "complete"

    def test_exists_with_empty_visibility_evidence_is_adopted(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        fake_gh.create_status = "exists"
        fake_gh.is_empty = True
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_k: "human"
        )
        result, events = run(_create_request(fake_gh.checkouts[IDENTITY]))
        assert result["status"] == "ok"
        assert "create_remote" in step_ids(events)
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["remote"]["created"] is True

    def test_live_agent_refuses_create_even_when_request_says_human(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gh.probe_status = "not_found"
        monkeypatch.setattr(
            "sase.project_onboarding._apply_run.detect_actor", lambda **_k: "agent"
        )
        result, _ = run(_create_request(fake_gh.checkouts[IDENTITY]))
        assert result["status"] == "blocked"
        assert "/sase_gate" in result["message"]
        assert "human approval" in result["message"]
        assert fake_gh.create_calls == []
