"""Add/delete surfaces for the Glossary panel."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static, TextArea

from rich.console import Console

from sase.ace.testing import wait_for
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
)
from sase.ace.tui.modals import glossary_pane as glossary_pane_module
from sase.ace.tui.modals import glossary_panel_actions as actions_mod
from sase.ace.tui.modals.config_commit import ConfigCommitOffer
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from sase.ace.tui.modals.glossary_panel_add import (
    GlossaryAddDraft,
    GlossaryTermAddModal,
)
from sase.ace.tui.modals.glossary_panel_delete import (
    build_glossary_delete_subject,
    neighbor_term_after_delete,
)
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.glossary.mutation import GlossaryConflictError, GlossaryMutationOutcome
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)
from tests.test_glossary_mutation import _SORTED_GLOSSARY, _install_project

_UNSET = object()


class _AddFormApp(App[None]):
    def __init__(self, modal: GlossaryTermAddModal) -> None:
        super().__init__()
        self.modal = modal
        self.result: GlossaryAddDraft | None | object = _UNSET

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal, self._capture)

    def _capture(self, result: GlossaryAddDraft | None) -> None:
        self.result = result


class _ActionsApp(App[None]):
    def __init__(self, panel: GlossaryPane) -> None:
        super().__init__()
        self.panel = panel
        self.session_calls: list[str] = []
        self.notifications: list[tuple[str, str]] = []
        self.invalidated: list[str] = []
        self.commit_prompts: list[ConfigCommitOffer] = []

    def compose(self) -> ComposeResult:
        yield self.panel

    def notify(
        self, message: str, *, severity: str = "information", **kwargs: Any
    ) -> None:
        self.notifications.append((message, severity))

    def _invalidate_prompt_glossary_catalogs(self, *, reason: str) -> None:
        self.invalidated.append(reason)

    def _submit_session_worker(
        self,
        proc_type: str,
        body: Any,
        *,
        on_complete: Any = None,
        **kwargs: Any,
    ) -> object:
        self.session_calls.append(proc_type)
        box: dict[str, TrackedProcResult[Any]] = {}

        def run() -> None:
            box["result"] = body()

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        result = box["result"]
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=None,  # type: ignore[arg-type]
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return object()


def _ref(
    key: str,
    display_name: str,
    *,
    has_glossary: bool = True,
    workspace_dir: str = "",
) -> GlossaryProjectRef:
    return GlossaryProjectRef(
        key=key,
        display_name=display_name,
        workspace_dir=workspace_dir,
        has_glossary=has_glossary,
    )


def _entry(
    index: int, term: str, *, definition: str = "", aliases: tuple[str, ...] = ()
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition or f"Definition of {term}.",
        configured_aliases=aliases,
        display_aliases=aliases,
        effective_aliases=(term.casefold(), *aliases),
        source={"config_path": f"/tmp/{term}/sase.yml"},
    )


class _CompiledGlossary:
    def scan(self, _text: str) -> list[dict[str, Any]]:
        return []


def _catalog(
    ref: GlossaryProjectRef, entries: tuple[GlossaryEntry, ...]
) -> EditorGlossaryCatalog:
    config_path = Path(ref.workspace_dir or f"/tmp/{ref.key}") / "sase" / "sase.yml"
    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key=ref.key,
            name=ref.display_name,
            aliases=(),
            workspace_dir=Path(ref.workspace_dir or "."),
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path), mtime_ns=1, size=1
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_CompiledGlossary(),
    )


def _snapshot(
    ref: GlossaryProjectRef,
    entries: tuple[GlossaryEntry, ...] = (),
    *,
    diagnostics: tuple[str, ...] = (),
    reverse_references: dict[int, tuple[str, ...]] | None = None,
) -> GlossaryProjectSnapshot:
    catalog = _catalog(ref, entries) if entries else None
    return GlossaryProjectSnapshot(
        project=ref,
        catalog=catalog,
        reverse_references=reverse_references or {},
        diagnostics=diagnostics,
    )


def _install_fixed_load(
    monkeypatch: pytest.MonkeyPatch,
    ring: tuple[GlossaryProjectRef, ...],
    snapshots: dict[str, GlossaryProjectSnapshot],
) -> None:
    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
        session_project_key: str | None = None,
    ) -> GlossaryPanelInitialLoad:
        del launch_workspace, initial_project_key, seed_from_current_project
        del session_project_key
        if not ring:
            return GlossaryPanelInitialLoad(ring=(), project_index=0, snapshot=None)
        return GlossaryPanelInitialLoad(
            ring=ring, project_index=0, snapshot=snapshots[ring[0].key]
        )

    def fake_project_load(ref: GlossaryProjectRef) -> GlossaryProjectSnapshot:
        return snapshots[ref.key]

    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_panel_initial_state", fake_initial_load
    )
    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_project_snapshot", fake_project_load
    )


def _outcome(
    term: str,
    *,
    aliases: tuple[str, ...] = (),
    definition: str = "A definition.",
    config_path: str = "/tmp/sase.yml",
    restore_command: str = 'sase glossary add "Term" "A definition." -p demo',
) -> GlossaryMutationOutcome:
    return GlossaryMutationOutcome(
        project_name="demo",
        config_path=config_path,
        workspace_dir="/tmp",
        term=term,
        aliases=aliases,
        definition=definition,
        created_section=False,
        restore_command=restore_command,
        referenced_by=(),
    )


def _plain(renderable: object) -> str:
    if isinstance(renderable, str):
        return renderable
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


async def _fill_add_form(
    app: App[None],
    *,
    term: str,
    definition: str,
    aliases: str = "",
) -> GlossaryTermAddModal:
    modal = app.screen
    assert isinstance(modal, GlossaryTermAddModal)
    modal.query_one("#glossary-add-term", Input).value = term
    modal.query_one("#glossary-add-aliases", Input).value = aliases
    modal.query_one("#glossary-add-definition", TextArea).text = definition
    return modal


def test_delete_subject_lists_inbound_count_and_terms() -> None:
    subject = build_glossary_delete_subject(
        term="Agent Hood",
        aliases=("hood", "agent neighborhood"),
        definition="An agent hood is a group of agents.\nMore detail.",
        config_path="/tmp/sase/sase.yml",
        referenced_by=("Agent Neighbor", "Agent Clan", "Sase Agent"),
    )
    assert "Term: Agent Hood" in subject
    assert "hood, agent neighborhood" in subject
    assert "An agent hood is a group of agents." in subject
    assert (
        "3 definitions reference this term: Agent Neighbor, Agent Clan, Sase Agent"
        in subject
    )


def test_neighbor_term_after_delete_middle_and_last() -> None:
    terms = ("Alpha", "Beta", "Gamma")
    assert neighbor_term_after_delete(terms, "Beta") == "Gamma"
    assert neighbor_term_after_delete(terms, "Gamma") == "Beta"
    assert neighbor_term_after_delete(terms, "Alpha") == "Beta"
    assert neighbor_term_after_delete(("Solo",), "Solo") is None


async def test_add_form_refuses_duplicate_and_colliding_alias() -> None:
    existing = (_entry(0, "Alpha"),)
    modal = GlossaryTermAddModal(existing_entries=existing, project_display_name="demo")
    app = _AddFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, GlossaryTermAddModal))
        form = await _fill_add_form(
            app, term="Alpha", definition="A colliding definition."
        )
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.blocking))
        assert app.result is _UNSET
        assert isinstance(app.screen, GlossaryTermAddModal)
        term_error = _plain(form.query_one("#glossary-add-term-error", Static).content)
        assert "conflict" in term_error.lower()

        form.query_one("#glossary-add-term", Input).value = "Other"
        form.query_one("#glossary-add-aliases", Input).value = "Alpha"
        form.query_one(
            "#glossary-add-definition", TextArea
        ).text = "Collides via alias."
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.aliases or form._errors.term))
        assert isinstance(app.screen, GlossaryTermAddModal)
        alias_error = _plain(
            form.query_one("#glossary-add-aliases-error", Static).content
        )
        assert "conflict" in alias_error.lower()


async def test_add_form_valid_submit_returns_draft() -> None:
    modal = GlossaryTermAddModal(existing_entries=(), project_display_name="demo")
    app = _AddFormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, GlossaryTermAddModal))
        form = await _fill_add_form(
            app, term="Widget Box", definition="A container.", aliases="box, wb"
        )
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.result, GlossaryAddDraft))
    assert app.result == GlossaryAddDraft(
        term="Widget Box", aliases=("box", "wb"), definition="A container."
    )


async def test_valid_add_writes_through_engine_and_selects_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("gh_demo__app", "demo")
    snapshots = {"gh_demo__app": _snapshot(ref, (_entry(0, "Alpha"),))}
    _install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[Any, ...]] = []
    offer_threads: list[bool] = []

    def fake_add(
        project_ref: str | None,
        term: str,
        definition: str,
        aliases: Any = (),
    ) -> GlossaryMutationOutcome:
        recorded.append((project_ref, term, definition, tuple(aliases)))
        snapshots[ref.key] = _snapshot(ref, (_entry(0, "Alpha"), _entry(1, term)))
        return _outcome(term, aliases=tuple(aliases), definition=definition)

    def fake_load(project: GlossaryProjectRef) -> GlossaryProjectSnapshot:
        return snapshots[project.key]

    def fake_offer(path: str, *, subject: str) -> ConfigCommitOffer:
        offer_threads.append(threading.current_thread() is not threading.main_thread())
        return ConfigCommitOffer(
            git_root="/tmp",
            file_path=path,
            rel_path="sase/sase.yml",
            message=subject,
        )

    monkeypatch.setattr(actions_mod, "add_glossary_term", fake_add)
    monkeypatch.setattr(actions_mod, "load_glossary_project_snapshot", fake_load)
    monkeypatch.setattr(actions_mod, "invalidate_glossary_project", lambda _key: None)
    monkeypatch.setattr(actions_mod, "build_config_commit_offer", fake_offer)
    monkeypatch.setattr(
        actions_mod, "push_config_commit_prompt", lambda *_a, **_k: None
    )

    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, GlossaryTermAddModal))
        form = await _fill_add_form(
            app, term="Beta", definition="The middle term.", aliases="b"
        )
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_term == "Beta")

    assert recorded == [("gh_demo__app", "Beta", "The middle term.", ("b",))]
    assert app.session_calls == ["glossary-add"]
    assert app.invalidated == ["glossary-panel-write"]
    assert any("Added" in message for message, _sev in app.notifications)
    assert any("sase memory init" in message for message, _sev in app.notifications)
    assert offer_threads == [True]


async def test_delete_confirmation_lists_inbound_and_cancel_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("sase", "sase")
    entries = (
        _entry(0, "Agent Hood"),
        _entry(1, "Sase Agent"),
    )
    snapshots = {
        "sase": _snapshot(
            ref,
            entries,
            reverse_references={0: ("Sase Agent", "Agent Neighbor")},
        )
    }
    _install_fixed_load(monkeypatch, (ref,), snapshots)
    called: list[str] = []

    def fake_delete(*_a: Any, **_k: Any) -> GlossaryMutationOutcome:
        called.append("delete")
        return _outcome("Agent Hood")

    monkeypatch.setattr(actions_mod, "delete_glossary_term", fake_delete)

    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._subject is not None
        assert (
            "2 definitions reference this term: Sase Agent, Agent Neighbor"
            in confirm._subject
        )
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmActionModal))

    assert called == []
    assert app.session_calls == []


async def test_delete_selects_neighbor_including_last_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref("gh_demo__app", "demo")
    entries = (_entry(0, "Alpha"), _entry(1, "Beta"), _entry(2, "Gamma"))
    snapshots = {"gh_demo__app": _snapshot(ref, entries)}
    _install_fixed_load(monkeypatch, (ref,), snapshots)

    def fake_delete(_project: str | None, term: str) -> GlossaryMutationOutcome:
        catalog = snapshots[ref.key].catalog
        assert catalog is not None
        remaining = tuple(entry for entry in catalog.entries if entry.term != term)
        snapshots[ref.key] = _snapshot(ref, remaining)
        return _outcome(
            term,
            restore_command=f"sase glossary add {term} 'Definition of {term}.' -p demo",
        )

    monkeypatch.setattr(actions_mod, "delete_glossary_term", fake_delete)
    monkeypatch.setattr(
        actions_mod,
        "load_glossary_project_snapshot",
        lambda project: snapshots[project.key],
    )
    monkeypatch.setattr(actions_mod, "invalidate_glossary_project", lambda _key: None)
    monkeypatch.setattr(
        actions_mod, "build_config_commit_offer", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        actions_mod, "push_config_commit_prompt", lambda *_a, **_k: None
    )

    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_term == "Beta")
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("y")
        await wait_for(pilot, lambda: panel._current_term == "Gamma")
        assert app.session_calls == ["glossary-delete"]

        await pilot.press("G")
        await wait_for(pilot, lambda: panel._current_term == "Gamma")
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("y")
        await wait_for(pilot, lambda: panel._current_term == "Alpha")

    assert app.session_calls == ["glossary-delete", "glossary-delete"]
    assert any("Restore with:" in message for message, _sev in app.notifications)


async def test_conflict_toasts_and_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _ref("sase", "sase")
    snapshots = {"sase": _snapshot(ref, (_entry(0, "Alpha"),))}
    _install_fixed_load(monkeypatch, (ref,), snapshots)
    loads = {"count": 0}

    def fake_delete(*_a: Any, **_k: Any) -> GlossaryMutationOutcome:
        raise GlossaryConflictError(Path("/tmp/sase.yml"))

    def fake_project_load(project: GlossaryProjectRef) -> GlossaryProjectSnapshot:
        loads["count"] += 1
        return snapshots[project.key]

    monkeypatch.setattr(actions_mod, "delete_glossary_term", fake_delete)
    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_project_snapshot", fake_project_load
    )
    monkeypatch.setattr(actions_mod, "invalidate_glossary_project", lambda _key: None)

    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        before = loads["count"]
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("y")
        await wait_for(
            pilot,
            lambda: any(
                "changed after preview" in msg for msg, _sev in app.notifications
            ),
        )
        await wait_for(pilot, lambda: loads["count"] > before)

    assert app.session_calls == ["glossary-delete"]
    assert any(sev == "error" for _msg, sev in app.notifications)
    assert app.invalidated == []


async def test_validation_error_toasts_and_leaves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    original = config_path.read_bytes()
    workspace = str(tmp_path / "workspace")
    ref = _ref("gh_demo__app", "demo", workspace_dir=workspace)
    snapshots = {
        "gh_demo__app": _snapshot(
            ref, (_entry(0, "Alpha"), _entry(1, "Gamma", aliases=("g",)))
        )
    }
    _install_fixed_load(monkeypatch, (ref,), snapshots)
    monkeypatch.setattr(
        actions_mod, "load_glossary_project_snapshot", lambda _p: snapshots[ref.key]
    )
    monkeypatch.setattr(actions_mod, "invalidate_glossary_project", lambda _key: None)
    monkeypatch.setattr(
        actions_mod, "build_config_commit_offer", lambda *_a, **_k: None
    )

    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        # Bypass the form so this exercises the write-path toast, not live
        # client-side refusal (covered separately).
        panel._submit_glossary_write(
            kind="add",
            term="Alpha",
            definition="A colliding definition.",
            preferred_term="Alpha",
        )
        await wait_for(
            pilot,
            lambda: any(
                "alias_conflict" in msg or "used by more than one" in msg
                for msg, _sev in app.notifications
            ),
        )

    assert config_path.read_bytes() == original
    assert any(sev == "error" for _msg, sev in app.notifications)
    assert app.invalidated == []
    assert panel._current_term == "Alpha"


async def test_footer_shows_conditional_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _ref("sase", "sase")
    _install_fixed_load(
        monkeypatch, (ref,), {"sase": _snapshot(ref, (_entry(0, "Alpha"),))}
    )
    panel = GlossaryPane()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        footer = panel.query_one("#glossary-panel-footer", Static)
        text = _plain(footer.content)
        assert "d delete" in text
        assert "a add" not in text
        assert "filter" not in text
        assert "help" not in text
        assert "esc" not in text
        assert footer.display is True
