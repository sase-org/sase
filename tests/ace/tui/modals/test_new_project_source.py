"""Source-stage model and user-path coverage for the New Project wizard."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from sase import workspace_provider
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_source_model import (
    build_source_view,
    hidden_footer,
)
from sase.project_onboarding import CandidateInputs, OwnerResult, Preferences
from sase.workspace_provider import ParsedRepoRef, WorkflowMetadata


def _parsed(workflow_type: str, ref: str) -> ParsedRepoRef:
    owner, name = ref.split("/", 1)
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"github.com/{ref}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"~/projects/github/{owner}/{name}/",
    )


def _provider(workflow_type: str, display_name: str) -> WorkflowMetadata:
    return WorkflowMetadata(
        workflow_type=workflow_type,
        ref_pattern=r"^$",
        display_name=display_name,
        pre_allocated_env_prefix="",
    )


def _inputs(
    *,
    owners: list[OwnerResult] | None = None,
    account: str = "bbugyi200",
) -> CandidateInputs:
    return CandidateInputs(
        workflow_type="gh",
        display="GitHub",
        account=account,
        owners=owners if owners is not None else [OwnerResult(name="sase-org")],
        remote=[
            {
                "identity_key": "github.com/sase-org/new",
                "ref": "sase-org/new",
                "display": "sase-org/new",
                "owner": "sase-org",
                "name": "new",
                "description": "A suggested repository",
                "visibility": "public",
                "pushed_at": "2026-10-11T14:00:00Z",
                "is_fork": False,
            },
            {
                "identity_key": "github.com/sase-org/fork",
                "ref": "sase-org/fork",
                "display": "sase-org/fork",
                "owner": "sase-org",
                "name": "fork",
                "description": "",
                "visibility": "public",
                "is_fork": True,
            },
            {
                "identity_key": "github.com/sase-org/hidden",
                "ref": "sase-org/hidden",
                "display": "sase-org/hidden",
                "owner": "sase-org",
                "name": "hidden",
                "description": "Already registered",
                "visibility": "private",
                "is_fork": False,
            },
        ],
        local=[
            {
                "identity_key": "github.com/sase-org/clone",
                "ref": "sase-org/clone",
                "display": "sase-org/clone",
                "owner": "sase-org",
                "name": "clone",
                "path": "/tmp/clone",
                "numbered_copy": False,
            }
        ],
        projects=[
            {
                "key": "old-project",
                "name": "old-project",
                "aliases": [],
                "state": "disabled",
                "identity_keys": ["github.com/sase-org/old"],
            },
            {
                "key": "existing-project",
                "name": "existing-project",
                "aliases": [],
                "state": "enabled",
                "identity_keys": ["github.com/sase-org/hidden"],
            },
        ],
        inventory=[
            {
                "identity_key": "github.com/sase-org/sase--plans",
                "kind": "sidecar",
                "project_key": "sase",
            }
        ],
        journals=[
            {
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "status": "failed",
                "stopped_at": "2026-10-11T14:00:00Z",
            }
        ],
        owned_namespaces=["sase-org", "bbugyi200"],
        sidecar_roles=["plans", "beads", "agents", "attachments", "research", "sdd"],
    )


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


def test_source_groups_hidden_counts_and_hidden_filter() -> None:
    inputs = _inputs()
    view = build_source_view(inputs)

    assert [group.group_id for group in view.groups] == [
        "resume",
        "local",
        "suggested",
        "disabled",
    ]
    assert view.groups[0].rows[0].display == "sase-org/forge"
    assert dict(view.hidden_counts)["fork"] == 1
    assert hidden_footer(view) == (
        "┄ 1 project · 1 sidecar · 1 fork hidden · f forks · . all"
    )

    matching_hidden = build_source_view(inputs, filter_text="hidden")
    assert matching_hidden.groups[-1].group_id == "search_only"
    assert matching_hidden.groups[-1].rows[0].display == "sase-org/hidden"

    all_rows = build_source_view(inputs, reveal_forks=True)
    assert all_rows.groups[-1].rows[0].hidden_reason == "fork"


def test_source_paste_ref_becomes_a_synthetic_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, "sase-org/pasted")
            if text == "https://github.com/sase-org/pasted"
            else None
        ),
    )

    view = build_source_view(
        _inputs(), filter_text="https://github.com/sase-org/pasted"
    )

    assert view.parsed_ref.ref == "sase-org/pasted"
    assert view.groups[0].group_id == "paste"
    assert view.groups[0].rows[0].display == "Add sase-org/pasted"


async def test_filter_and_enter_advance_the_modal_without_an_entry_point(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, text) if text == "sase-org/new" else None
        ),
    )
    metadata = (_provider("gh", "GitHub"),)
    modal = NewProjectModal(
        provider_metadata=metadata,
        candidate_inputs={"gh": _inputs()},
        preferences=Preferences(last_provider="gh"),
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#new-project-filter", Input)
        filter_input.focus()
        await pilot.press("s", "a", "s", "e", "-", "o", "r", "g", "/", "n", "e", "w")
        await pilot.pause()
        assert modal.query_one("#new-project-filter", Input).value == "sase-org/new"
        assert (
            "sase-org/new"
            in modal.query_one("#new-project-source-detail", Static).render().plain
        )

        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert (
            modal.query_one("#new-project-stepper", Static)
            .render()
            .plain.startswith("✓ Source")
        )


async def test_tab_selection_persists_last_provider_off_thread(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    metadata = (
        _provider("gh", "GitHub"),
        _provider("git", "Git (bare)"),
    )
    modal = NewProjectModal(provider_metadata=metadata, preferences=Preferences())
    modal._provided_inputs.update(
        {
            "gh": _inputs(),
            "git": CandidateInputs("git", "Git (bare)", ""),
        }
    )
    app = _ModalApp()
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal.select_provider("git")
        await pilot.pause(0.1)

    import json

    payload = json.loads(
        (tmp_path / "project_onboarding" / "preferences.json").read_text()
    )
    assert payload["last_provider"] == "git"
