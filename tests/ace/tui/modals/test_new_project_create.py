"""Create-draft and Configure-stage coverage for new repositories."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase import workspace_provider
from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals import new_project_create as create
from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)


def _parsed(workflow_type: str, text: str) -> ParsedRepoRef | None:
    if workflow_type == "git":
        name = text.removeprefix("git:")
        if not name or "/" in name:
            return None
        return ParsedRepoRef(
            workflow_type="git",
            ref=name,
            identity_key=f"git:/repos/{name}.git",
            display=name,
            owner="",
            name=name,
            project_key_base=name,
            project_name_base=name,
            checkout_dir=f"/home/user/projects/git/{name}/",
        )
    ref = text
    if "://" in ref:
        ref = ref.split("://", 1)[1]
        if "/" in ref:
            ref = ref.split("/", 1)[1]
    ref = ref.removesuffix(".git")
    if "/" not in ref:
        return None
    owner, name = ref.split("/", 1)
    if not owner or not name:
        return None
    text = f"{owner}/{name}"
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=text,
        identity_key=f"github.com/{text}".casefold(),
        display=text,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"/home/user/projects/github/{owner}/{name}/",
        web_url=f"https://github.com/{text}",
    )


def _form() -> RepoCreationForm:
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
        fields=(
            RepoCreationField(
                name="description", label="Description", kind="line", default=""
            ),
            RepoCreationField(
                name="readme", label="README", kind="bool", default="true"
            ),
            RepoCreationField(
                name="template",
                label="Template",
                kind="line",
                group="advanced",
                excludes=("readme",),
            ),
        ),
        can_create=True,
    )


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parsed)


def _probe(status: str, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "status": status,
        "visibility": "",
        "is_empty": None,
        "is_archived": None,
        "can_push": None,
        "sase_managed": None,
        "repo_id": "",
        "default_branch": "",
        "message": "",
        "web_url": "",
        "error_kind": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_owner_defaults_prefer_last_used_then_project_then_account() -> None:
    owners = ["sase-org", "bbugyi200", "sase-org"]
    assert (
        create._default_create_owner(
            owners,
            account="bbugyi200",
            last_owner="sase-org",
            current_project_owner="bbugyi200",
            workflow_type="gh",
        )
        == "sase-org"
    )
    assert (
        create._default_create_owner(
            owners,
            account="bbugyi200",
            last_owner="gone",
            current_project_owner="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )
    assert (
        create._default_create_owner(
            ["sase-org"],
            account="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )
    assert (
        create._default_create_owner(
            ["sase-org"],
            account="bbugyi200",
            workflow_type="gh",
            unavailable={"bbugyi200"},
        )
        == "sase-org"
    )
    assert (
        create._default_create_owner(
            [],
            account="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )


def test_owner_defaults_skip_unavailable_and_support_bare_git() -> None:
    assert (
        create._default_create_owner(
            ["sase-org", "bbugyi200"],
            account="bbugyi200",
            last_owner="sase-org",
            workflow_type="gh",
            unavailable={"sase-org", "bbugyi200"},
        )
        == ""
    )
    assert (
        create._default_create_owner(
            [],
            account="bbugyi200",
            workflow_type="git",
        )
        == ""
    )
    assert (
        create._default_create_owner(
            ["docs"],
            account="bbugyi200",
            last_owner="bbugyi200",
            workflow_type="git",
        )
        == "docs"
    )


def test_visibility_defaults_to_private_then_last_supported_choice() -> None:
    supported = ("private", "public")
    assert (
        create._default_create_visibility(
            owner="sase-org", supported=supported, last_visibility={}
        )
        == "private"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=supported,
            last_visibility={"sase-org": "public"},
        )
        == "public"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=("private",),
            last_visibility={"sase-org": "public"},
        )
        == "private"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=supported,
            last_visibility={"sase-org": "public"},
            unavailable={"public"},
        )
        == "private"
    )


def test_supported_visibilities_follow_provider_choice_field() -> None:
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
                    RepoCreationChoice(value="internal", label="Internal"),
                ),
            ),
        ),
        can_create=True,
    )
    assert create._supported_create_visibilities(form) == ("private", "internal")
    assert create._supported_create_visibilities(None) == ("private", "public")


def test_normalize_create_name_preserves_provider_identity(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("gh", "sase-org", "  new  ")
    assert identity.valid
    assert identity.canonical_ref == "sase-org/new"
    assert identity.identity_key == "github.com/sase-org/new"
    assert identity.checkout_dir == "/home/user/projects/github/sase-org/new/"
    assert identity.project_key_base == "gh_sase-org__new"
    assert identity.project_name_base == "new"
    assert identity.web_url == "https://github.com/sase-org/new"
    assert identity.normalized_label == ""


def test_normalize_create_name_rejects_blank_and_unknown(
    fake_provider: None,
) -> None:
    blank = create.normalize_create_name("gh", "sase-org", "   ")
    assert not blank.valid
    assert blank.error
    empty_name = create.normalize_create_name("gh", "sase-org", "sase-org/")
    assert not empty_name.valid
    assert empty_name.error


def test_normalized_label_shows_only_genuine_changes() -> None:
    assert (
        create.CreateIdentity(
            valid=True, canonical_ref="a/b", normalized_from="a/B"
        ).normalized_label
        == "a/B → a/b"
    )
    assert create.CreateIdentity(valid=True, canonical_ref="a/b").normalized_label == ""
    assert create.CreateIdentity(valid=False, error="blank").normalized_label == ""


def test_normalize_bare_git_supports_empty_namespace(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("git", "", "notes")
    assert identity.valid
    assert identity.identity_key == "git:/repos/notes.git"
    assert identity.checkout_dir == "/home/user/projects/git/notes/"


def test_classify_probe_maps_all_states() -> None:
    assert create.classify_create_probe(_probe("not_found")).status == "available"
    assert create.classify_create_probe(_probe("found")).status == "taken"
    assert create.classify_create_probe(None).status == "unavailable"
    assert (
        create.classify_create_probe(_probe("unavailable", error_kind="auth")).status
        == "unavailable"
    )
    denied = create.classify_create_probe(
        _probe("unavailable", error_kind="auth", message="permission denied")
    )
    assert denied.status == "unavailable"
    assert "permission denied" in denied.reason
    assert create.classify_create_probe(_probe("bogus")).status == "unavailable"


def test_probe_result_current_rejects_every_stale_dimension() -> None:
    current = {
        "generation": 3,
        "expected_generation": 3,
        "mode": "create",
        "expected_mode": "create",
        "owner": "sase-org",
        "expected_owner": "sase-org",
        "identity_key": "github.com/sase-org/new",
        "expected_identity_key": "github.com/sase-org/new",
    }
    assert create._probe_result_current(**current)
    assert not create._probe_result_current(
        **{**current, "generation": 2},
    )
    assert not create._probe_result_current(**{**current, "mode": "add"})
    assert not create._probe_result_current(
        **{**current, "expected_owner": "other"},
    )
    assert not create._probe_result_current(
        **{**current, "identity_key": "github.com/sase-org/old"},
    )


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
        _form(), {"description": "hi", "readme": "true", "template": "sase-org/t"}
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
        probe=_probe("not_found"),
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


class _CreateApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


def _modal(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[_CreateApp, Any, list[str], list[str]]:
    from sase.ace.tui.modals.new_project_modal import NewProjectModal
    from sase.project_onboarding import Preferences
    from sase.workspace_provider import WorkflowMetadata
    from tests.ace.tui.modals.test_new_project_source import _inputs

    probe_calls: list[str] = []
    describe_calls: list[str] = []
    probe_status = overrides.get("probe_status", "not_found")
    form: RepoCreationForm | None = overrides.get("form", _form())

    def _probe_repo(workflow_type: str, ref: str) -> SimpleNamespace:
        probe_calls.append(ref)
        if isinstance(probe_status, Exception):
            raise probe_status
        return _probe(probe_status)

    def _describe(workflow_type: str, namespace: str) -> RepoCreationForm | None:
        describe_calls.append(namespace)
        return form

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parsed)
    monkeypatch.setattr(workspace_provider, "probe_repo", _probe_repo)
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", _describe)
    modal = NewProjectModal(
        provider_metadata=(
            WorkflowMetadata(
                workflow_type="gh",
                ref_pattern=r"^$",
                display_name="GitHub",
                pre_allocated_env_prefix="",
            ),
        ),
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(
            last_owner={"gh": "sase-org"},
            last_visibility={"sase-org": "public"},
        ),
    )
    app = _CreateApp()
    return app, modal, probe_calls, describe_calls


async def _enter(pilot: Any, modal: Any, **kwargs: Any) -> None:
    modal.enter_create_configure(
        workflow_type="gh",
        owners=["sase-org", "bbugyi200"],
        account="bbugyi200",
        **kwargs,
    )
    await pilot.pause(0.6)


async def test_typing_starts_no_sync_probe_and_settles_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, probe_calls, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org"],
            account="",
        )
        await pilot.pause(0.6)
        # Source detail probes are out of scope; isolate create-flow probes.
        probe_calls.clear()
        name = modal.query_one("#new-project-create-name", Input)
        # No awaits while typing: delivery is queued, so the debounce cannot
        # fire mid-word and the settled probe below is the only one.
        for character in ("n", "e", "w"):
            name.insert_text_at_cursor(character)
        assert probe_calls == []
        await pilot.pause(0.6)
        assert probe_calls == ["sase-org/new"]
        assert modal._create_availability.status == "available"


async def test_project_name_follows_until_explicitly_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        name = modal.query_one("#new-project-create-name", Input)
        project = modal.query_one("#new-project-create-project-name", Input)
        name.value = "alpha"
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.project.name == "alpha"
        assert project.value == "alpha"
        project.value = "custom"
        await pilot.pause(0.6)
        assert modal._state.create_draft.project_name_edited
        name.value = "beta"
        await pilot.pause(0.6)
        assert modal._state.create_draft.project.name == "custom"
        assert project.value == "custom"


async def test_owner_switch_preserves_per_owner_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "sase-org"
        assert modal._state.create_draft.visibility == "public"
        modal.query_one("#new-project-create-name", Input).value = "alpha"
        await pilot.pause(0.6)
        modal._on_create_owner_selected("bbugyi200")
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "bbugyi200"
        assert modal._state.create_draft.raw_name == ""
        modal._on_create_owner_selected("sase-org")
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.raw_name == "alpha"


async def test_taken_name_offers_explicit_add_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input

    app, modal, _, _ = _modal(monkeypatch, probe_status="found")
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "taken"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "taken"
        add_instead = modal.query_one("#new-project-create-add-instead", Button)
        assert add_instead.display
        assert modal.query_one("#new-project-create-review", Button).disabled
        name = modal.query_one("#new-project-create-name", Input)
        name.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal._state.wizard_mode == "add"
        assert modal._state.draft is not None
        assert modal._state.draft.name == "taken"


async def test_enter_with_available_name_creates_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "fresh"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "available"
        name = modal.query_one("#new-project-create-name", Input)
        name.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "create-configure"
        assert modal.create_review_intent() is None


async def test_probe_failure_never_becomes_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input, Static

    app, modal, _, _ = _modal(
        monkeypatch, probe_status=RuntimeError("permission denied")
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        assert modal._create_availability.status == "unavailable"
        assert "permission denied" in modal._create_availability.reason
        assert modal.query_one("#new-project-create-review", Button).disabled
        availability = modal.query_one("#new-project-create-availability", Static)
        assert "permission denied" in availability.render().plain


async def test_missing_form_leaves_no_confirmable_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input, Static

    app, modal, _, _ = _modal(monkeypatch, form=None)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        assert modal._create_form_status == "unavailable"
        assert modal.query_one("#new-project-create-review", Button).disabled
        status = modal.query_one("#new-project-create-status", Static)
        assert "unavailable" in status.render().plain


async def test_name_collision_blocks_review_but_occupied_checkout_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Button, Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "brandnew"
        modal.query_one(
            "#new-project-create-project-name", Input
        ).value = "existing-project"
        await pilot.pause(0.8)
        assert modal.query_one("#new-project-create-review", Button).disabled
        assert "existing-project" in (modal._create_identity_reason() or "")


async def test_late_form_completion_keeps_current_owner_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from textual.widgets import Input

    gates: dict[str, threading.Event] = {}
    describe_calls: list[str] = []

    def _gated_describe(workflow_type: str, namespace: str) -> RepoCreationForm | None:
        from dataclasses import replace as _replace

        gate = gates.setdefault(namespace, threading.Event())
        describe_calls.append(namespace)
        assert gate.wait(timeout=10)
        return _replace(_form(), namespace=namespace)

    app, modal, _, _ = _modal(monkeypatch)
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parsed)
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", _gated_describe)
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: _probe("not_found")
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        # Source-level create-support discovery describes the account namespace
        # on mount; drain it so the assertions below cover the create flow.
        await wait_for(pilot, lambda: "bbugyi200" in describe_calls)
        describe_calls.clear()
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org", "bbugyi200"],
            account="bbugyi200",
        )
        await pilot.pause()
        assert describe_calls == ["sase-org"]
        modal.query_one("#new-project-create-name", Input).value = "alpha"
        modal._on_create_owner_selected("bbugyi200")
        await pilot.pause()
        assert describe_calls == ["sase-org", "bbugyi200"]
        gates["bbugyi200"].set()
        await pilot.pause(0.5)
        assert modal._create_form is not None
        assert modal._create_form.namespace == "bbugyi200"
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "bbugyi200"
        gates["sase-org"].set()
        await pilot.pause(0.5)
        assert modal._create_form is not None
        assert modal._create_form.namespace == "bbugyi200"
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "bbugyi200"


async def test_stale_probe_and_preview_results_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "settled"
        await pilot.pause(0.8)
        assert modal._create_availability.status == "available"
        settled_plan = dict(modal._create_plan)
        assert settled_plan
        draft = modal._state.create_draft
        assert draft is not None
        stale_generation = modal._create_generation - 1
        await modal._run_create_check(
            generation=stale_generation,
            workflow_type="gh",
            owner="sase-org",
            identity=modal._create_identity,
            draft=draft,
            cached_probe=_probe("found"),
            provider_display="GitHub",
            storage_policy="",
        )
        await pilot.pause()
        assert modal._create_availability.status == "available"
        assert modal._create_plan == settled_plan


async def test_back_cancels_pending_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import Input

    from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure

    app, modal, probe_calls, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        widget = modal.query_one(NewProjectCreateConfigure)
        modal.query_one("#new-project-create-name", Input).value = "typed"
        # No awaits here: the debounce cannot fire without loop iterations,
        # so cancellation below deterministically wins the race.
        generation = modal._create_generation
        modal.action_cancel()
        assert modal._state.stage == "create-configure"
        modal.action_cancel()
        assert widget._check_timer is None
        await pilot.pause()
        assert modal._state.stage == "source"
        assert modal._state.wizard_mode == "add"
        assert modal._create_generation > generation
        assert "sase-org/typed" not in probe_calls
        modal.enter_create_configure(
            workflow_type="gh",
            owners=["sase-org"],
            account="",
        )
        await pilot.pause(0.8)
        assert "sase-org/typed" in probe_calls


async def test_unmount_cancels_pending_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        widget = modal.query_one(NewProjectCreateConfigure)
        widget.request_check()
        assert widget._check_timer is not None
        widget.on_unmount()
        assert widget._check_timer is None
        assert widget._check_due is False


async def test_paste_in_create_stage_leaves_source_filter_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace as _NS

    from textual.widgets import Input

    app, modal, _, _ = _modal(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await _enter(pilot, modal)
        source_filter = modal.query_one("#new-project-filter", Input)
        before = source_filter.value
        event = _NS(stop=lambda: None, prevent_default=lambda: None, text="pasted")
        modal._paste_anywhere(event)  # type: ignore[arg-type]
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == before


async def test_bare_git_entry_supports_empty_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.workspace_provider import WorkflowMetadata

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _parsed)
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda *args: _form()
    )
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: _probe("not_found")
    )
    from sase.ace.tui.modals.new_project_modal import NewProjectModal
    from sase.project_onboarding import Preferences

    modal = NewProjectModal(
        provider_metadata=(
            WorkflowMetadata(
                workflow_type="git",
                ref_pattern=r"^$",
                display_name="Bare git",
                pre_allocated_env_prefix="",
            ),
        ),
        candidate_inputs={},
        preferences=Preferences(),
    )
    app = _CreateApp()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.enter_create_configure(workflow_type="git", owners=[])
        await pilot.pause(0.6)
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == ""
        assert modal._state.create_draft.visibility == "private"
        assert modal._create_form_status == "ready"
