"""Add/edit/delete/publish surfaces for the Memory panel."""

from __future__ import annotations

from pathlib import Path
import subprocess
import threading
from typing import Any

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static, TextArea

from sase.ace.testing import wait_for
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.memory_panel_catalog import MemoryNoteDigest, MemoryScopeRef
from sase.ace.tui.modals import memory_panel_actions as actions_mod
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.memory_panel import MemoryPanel
from sase.ace.tui.modals.memory_panel_add import (
    MemoryNoteFormDraft,
    MemoryNoteFormModal,
)
from sase.ace.tui.modals.memory_panel_publish import (
    MemoryPublishModal,
    memory_publish_argv,
    memory_publish_cwd,
    memory_publish_subject,
)
from sase.ace.tui.proc_producer_sites import PRODUCTION_PRODUCERS
from sase.memory.mutation import MemoryConflictError, MemoryMutationOutcome
from sase.memory.notes import AGENTS_PARENT
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)

_UNSET = object()


class _FormApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: MemoryNoteFormModal) -> None:
        super().__init__()
        self.modal = modal
        self.result: MemoryNoteFormDraft | None | object = _UNSET

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal, self._capture)

    def _capture(self, result: MemoryNoteFormDraft | None) -> None:
        self.result = result


class _ActionsApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, panel: MemoryPanel) -> None:
        super().__init__()
        self.panel = panel
        self.session_calls: list[str] = []
        self.session_kwargs: list[dict[str, Any]] = []
        self.notifications: list[tuple[str, str]] = []
        self.catalog_refreshes: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)

    def notify(
        self, message: str, *, severity: str = "information", **kwargs: Any
    ) -> None:
        self.notifications.append((message, severity))

    def _schedule_prompt_catalog_rebuild(
        self, *, reason: str, force: bool = False
    ) -> None:
        del force
        self.catalog_refreshes.append(reason)

    def _submit_session_worker(
        self,
        proc_type: str,
        body: Any,
        *,
        on_complete: Any = None,
        **kwargs: Any,
    ) -> object:
        self.session_calls.append(proc_type)
        self.session_kwargs.append(kwargs)
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


def _plain(renderable: object) -> str:
    if isinstance(renderable, str):
        return renderable
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _digest(relative_path: str, sha: str = "abc") -> dict[str, MemoryNoteDigest]:
    return {relative_path: MemoryNoteDigest(mtime_ns=1, size=10, sha256=sha)}


def _outcome(
    stem: str,
    *,
    scope_key: str = "sase",
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    backup_path: Path | None = None,
) -> MemoryMutationOutcome:
    return MemoryMutationOutcome(
        scope_key=scope_key,
        content_root=Path("/tmp/memory"),
        relative_path=f"sase/memory/{stem}.md",
        stem=stem,
        type=note_type,  # type: ignore[arg-type]
        parent=parent,
        description=description,
        backup_path=backup_path,
    )


def _install_write_fakes(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: dict[str, Any],
    *,
    create: Any = None,
    update: Any = None,
    delete: Any = None,
) -> None:
    monkeypatch.setattr(
        actions_mod,
        "load_memory_scope_snapshot",
        lambda scope: snapshots[scope.key],
    )
    monkeypatch.setattr(actions_mod, "invalidate_memory_scope", lambda _key: None)
    if create is not None:
        monkeypatch.setattr(actions_mod, "create_memory_note", create)
    if update is not None:
        monkeypatch.setattr(actions_mod, "update_memory_note", update)
    if delete is not None:
        monkeypatch.setattr(actions_mod, "delete_memory_note", delete)


async def _fill_form(
    app: App[None],
    *,
    stem: str | None = None,
    note_type: str | None = None,
    parent: str | None = None,
    description: str | None = None,
) -> MemoryNoteFormModal:
    modal = app.screen
    assert isinstance(modal, MemoryNoteFormModal)
    if stem is not None:
        modal.query_one("#memory-note-form-stem", Input).value = stem
    if note_type is not None:
        modal.query_one("#memory-note-form-type", Select).value = note_type
    if parent is not None:
        modal.query_one("#memory-note-form-parent", Select).value = parent
    if description is not None:
        modal.query_one("#memory-note-form-description", TextArea).text = description
    return modal


async def _skip_post_write_offers(pilot: Any, app: App[None]) -> None:
    if isinstance(app.screen, ConfirmActionModal):
        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: (
                isinstance(app.screen, MemoryPublishModal) or app.screen is app.panel
            ),  # type: ignore[attr-defined]
        )
    if isinstance(app.screen, MemoryPublishModal):
        await pilot.press("escape")
        await wait_for(pilot, lambda: app.screen is app.panel)  # type: ignore[attr-defined]


async def test_form_parent_options_and_path_preview() -> None:
    notes = (
        memory_note("always", note_type="short"),
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md"),
    )
    modal = MemoryNoteFormModal(
        existing_notes=notes,
        scope_display_name="sase",
    )
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = app.screen
        assert isinstance(form, MemoryNoteFormModal)
        parent = form.query_one("#memory-note-form-parent", Select)
        parent.value = "sase/memory/hub.md"
        assert parent.value == "sase/memory/hub.md"
        form.query_one("#memory-note-form-stem", Input).value = "hub.md"
        form._update_path_preview()
        assert "sase/memory/hub.md" in _plain(
            form.query_one("#memory-note-form-path", Static).content
        )


def test_publish_argv_for_both_branches() -> None:
    assert memory_publish_argv(commit=True, subject="Add memory note beta") == [
        "sase",
        "memory",
        "init",
        "--message",
        "Add memory note beta",
    ]
    assert memory_publish_argv(commit=False, subject="ignored") == [
        "sase",
        "memory",
        "init",
        "--no-commit",
    ]


def test_publish_cwd_uses_home_for_home_scope() -> None:
    project = scope_ref("sase", "sase", content_root="/tmp/project")
    home = scope_ref(
        "home",
        "Home (chezmoi)",
        kind="home",
        content_root="/tmp/chezmoi",
    )
    assert memory_publish_cwd(project) == Path("/tmp/project")
    assert memory_publish_cwd(home) == Path.home()


def test_publish_subject_prefills_from_write_kind() -> None:
    assert memory_publish_subject("sase", kind="add", stem="beta") == (
        "Add memory note beta"
    )
    assert memory_publish_subject("sase") == "Publish memory notes for sase"


def test_memory_write_producer_is_registered() -> None:
    ids = {site.site_id for site in PRODUCTION_PRODUCERS}
    assert "memory.write" in ids
    assert "memory.publish" in ids


async def test_add_form_refuses_each_validation_branch() -> None:
    existing = (memory_note("alpha"),)
    modal = MemoryNoteFormModal(
        existing_notes=existing,
        scope_display_name="sase",
        include_project_memory=True,
    )
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(app, stem="", description="")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.blocking))
        assert app.result is _UNSET
        stem_error = _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )
        assert "required" in stem_error
        desc_error = _plain(
            form.query_one("#memory-note-form-description-error", Static).content
        )
        assert "description" in desc_error

        form = await _fill_form(app, stem="README", description="A note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "README" in _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await _fill_form(app, stem="../escape", description="A note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "traversal" in _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await _fill_form(app, stem="alpha", description="A colliding note.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "already exists" in _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )

        form = await _fill_form(app, stem="sase", description="Generated collision.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.stem))
        assert "read-only" in _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )


async def test_add_form_refuses_illegal_parent_and_cycle() -> None:
    notes = (
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md", description="Child."),
    )
    modal = MemoryNoteFormModal(
        mode="edit",
        existing_notes=notes,
        scope_display_name="sase",
        initial_stem="hub",
        initial_type="long",
        initial_parent=AGENTS_PARENT,
        initial_description="Hub.",
        current_relative_path="sase/memory/hub.md",
    )
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        assert app.screen.query_one("#memory-note-form-stem", Input).disabled is True
        form = await _fill_form(app, parent="sase/memory/child.md", description="Hub.")
        form.action_submit()
        await wait_for(pilot, lambda: bool(form._errors.parent))
        assert "cycle" in _plain(
            form.query_one("#memory-note-form-parent-error", Static).content
        )


async def test_add_form_valid_submit_returns_draft() -> None:
    modal = MemoryNoteFormModal(scope_display_name="sase")
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(
            app, stem="beta", note_type="long", description="The middle note."
        )
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.result, MemoryNoteFormDraft))
    assert app.result == MemoryNoteFormDraft(
        stem="beta",
        note_type="long",
        parent=AGENTS_PARENT,
        description="The middle note.",
    )


async def test_add_form_suppresses_required_errors_until_submit() -> None:
    modal = MemoryNoteFormModal(scope_display_name="sase")
    app = _FormApp(modal)
    async with app.run_test(size=(100, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(app, stem="tmp", description="x")
        form = await _fill_form(app, stem="", description="")
        form._validate_now()
        stem_error = _plain(
            form.query_one("#memory-note-form-stem-error", Static).content
        )
        desc_error = _plain(
            form.query_one("#memory-note-form-description-error", Static).content
        )
        assert stem_error == ""
        assert desc_error == ""


async def test_valid_add_writes_through_engine_and_selects_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[dict[str, Any]] = []

    def fake_create(**kwargs: Any) -> MemoryMutationOutcome:
        recorded.append(kwargs)
        snapshots[ref.key] = scope_snapshot(
            ref, (memory_note("alpha"), memory_note("beta", description="Middle."))
        )
        return _outcome("beta", description="Middle.")

    _install_write_fakes(monkeypatch, snapshots, create=fake_create)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(app, stem="beta", description="Middle.")
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/beta.md")
        await _skip_post_write_offers(pilot, app)
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")

    assert recorded[0]["stem"] == "beta"
    assert recorded[0]["note_type"] == "long"
    assert recorded[0]["scope_key"] == "sase"
    assert app.session_calls == ["memory-add"]
    assert app.session_kwargs[0]["dedup_key"] == "memory-write:sase"
    assert app.catalog_refreshes == ["memory-panel-write"]
    assert any("Added" in message for message, _sev in app.notifications)
    assert "sase" in panel._unpublished_scopes


async def test_edit_rewrites_frontmatter_and_reselects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("alpha", description="Old.")
    snapshots = {
        "sase": scope_snapshot(ref, (note,), digests=_digest("sase/memory/alpha.md"))
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[dict[str, Any]] = []

    def fake_update(**kwargs: Any) -> MemoryMutationOutcome:
        recorded.append(kwargs)
        snapshots[ref.key] = scope_snapshot(
            ref,
            (memory_note("alpha", description="New."),),
            digests=_digest("sase/memory/alpha.md"),
        )
        return _outcome("alpha", description="New.")

    _install_write_fakes(monkeypatch, snapshots, update=fake_update)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("e")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(app, description="New.")
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/alpha.md")
        await _skip_post_write_offers(pilot, app)
        assert panel._current_note == "sase/memory/alpha.md"

    assert recorded[0]["relative_path"] == "sase/memory/alpha.md"
    assert recorded[0]["expected_digest"] == "abc"
    assert recorded[0]["description"] == "New."
    assert app.session_calls == ["memory-edit"]
    assert panel._current_note == "sase/memory/alpha.md"


async def test_delete_selects_neighbor_and_names_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("alpha"),
        memory_note("beta"),
        memory_note("gamma"),
    )
    snapshots = {
        "sase": scope_snapshot(
            ref,
            notes,
            digests={
                **_digest("sase/memory/alpha.md"),
                **_digest("sase/memory/beta.md", "def"),
                **_digest("sase/memory/gamma.md", "ghi"),
            },
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    backup = Path("/tmp/memory/.sase/memory-backups/beta-20260819.md")

    def fake_delete(**kwargs: Any) -> MemoryMutationOutcome:
        remaining = tuple(
            note
            for note in snapshots[ref.key].notes
            if note.relative_path != kwargs["relative_path"]
        )
        snapshots[ref.key] = scope_snapshot(ref, remaining)
        return _outcome(
            Path(kwargs["relative_path"]).stem,
            backup_path=backup,
        )

    _install_write_fakes(monkeypatch, snapshots, delete=fake_delete)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/beta.md")
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._subject is not None
        assert "sase/memory/beta.md" in confirm._subject
        assert "Tier: 2 (long)" in confirm._subject
        await pilot.press("y")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/gamma.md")
        await _skip_post_write_offers(pilot, app)

    assert app.session_calls == ["memory-delete"]
    assert any("Backup:" in message for message, _sev in app.notifications)
    assert any(str(backup) in message for message, _sev in app.notifications)


async def test_short_note_delete_warns_about_always_loaded_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("always", note_type="short", description="Always loaded.")
    snapshots = {
        "sase": scope_snapshot(ref, (note,), digests=_digest("sase/memory/always.md"))
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._subject is not None
        assert "Tier: 1 (short)" in confirm._subject
        assert "always-loaded agent context" in confirm._subject
        await pilot.press("escape")
        await wait_for(pilot, lambda: app.screen is panel)

    assert app.session_calls == []


async def test_child_blocked_delete_explains_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md", description="Child."),
    )
    snapshots = {"sase": scope_snapshot(ref, notes)}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    called: list[str] = []

    def fake_delete(**_kwargs: Any) -> MemoryMutationOutcome:
        called.append("delete")
        return _outcome("hub")

    _install_write_fakes(monkeypatch, snapshots, delete=fake_delete)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert "reparented" in confirm._message
        assert "sase/memory/child.md" in (confirm._subject or "")
        await pilot.press("escape")
        await wait_for(pilot, lambda: app.screen is panel)

    assert called == []
    assert app.session_calls == []


async def test_generated_note_refuses_edit_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("sase")
    snapshots = {
        "sase": scope_snapshot(
            ref, (note,), generated_paths=frozenset({"sase/memory/sase.md"})
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        footer = panel_static_text(panel, "memory-panel-footer")
        assert "e edit" not in footer
        assert "d delete" not in footer
        await pilot.press("e")
        await wait_for(
            pilot,
            lambda: any("read-only" in msg for msg, _sev in app.notifications),
        )
        assert isinstance(app.screen, MemoryPanel)
        await pilot.press("d")
        await wait_for(pilot, lambda: len(app.notifications) >= 2)

    assert app.session_calls == []
    assert all("read-only" in msg for msg, _sev in app.notifications)


async def test_conflict_toasts_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(
            ref,
            (memory_note("alpha"),),
            digests=_digest("sase/memory/alpha.md"),
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    loads = {"count": 0}

    def fake_delete(**_kwargs: Any) -> MemoryMutationOutcome:
        raise MemoryConflictError(Path("/tmp/memory/sase/memory/alpha.md"))

    def fake_scope_load(scope: MemoryScopeRef) -> Any:
        loads["count"] += 1
        return snapshots[scope.key]

    _install_write_fakes(monkeypatch, snapshots, delete=fake_delete)
    monkeypatch.setattr(
        "sase.ace.tui.modals.memory_panel.load_memory_scope_snapshot",
        fake_scope_load,
    )

    panel = MemoryPanel()
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

    assert app.session_calls == ["memory-delete"]
    assert any(sev == "error" for _msg, sev in app.notifications)
    assert app.catalog_refreshes == []
    assert "sase" not in panel._unpublished_scopes


async def test_publish_runs_init_and_clears_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase", content_root="/tmp/project")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[list[str], str]] = []

    def fake_create(**_kwargs: Any) -> MemoryMutationOutcome:
        snapshots[ref.key] = scope_snapshot(
            ref, (memory_note("alpha"), memory_note("beta", description="New."))
        )
        return _outcome("beta")

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(argv), str(cwd)))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    _install_write_fakes(monkeypatch, snapshots, create=fake_create)
    monkeypatch.setattr(actions_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await _fill_form(app, stem="beta", description="New.")
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")
        publish = app.screen
        assert isinstance(publish, MemoryPublishModal)
        assert publish.query_one("#memory-publish-subject", Input).value == (
            "Add memory note beta"
        )
        publish.action_publish_commit()
        await wait_for(pilot, lambda: "memory-publish" in app.session_calls)
        await wait_for(pilot, lambda: "sase" not in panel._unpublished_scopes)
        assert "UNPUBLISHED" not in panel_static_text(panel, "memory-panel-header")

    assert recorded == [
        (
            ["sase", "memory", "init", "--message", "Add memory note beta"],
            "/tmp/project",
        )
    ]


async def test_publish_only_and_home_scope_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref(
        "home",
        "Home (chezmoi)",
        kind="home",
        content_root="/tmp/chezmoi",
    )
    snapshots = {"home": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[list[str], str]] = []

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(argv), str(cwd)))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    monkeypatch.setattr(actions_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._mark_scope_unpublished()
        await wait_for(
            pilot,
            lambda: "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header"),
        )
        await pilot.press("I")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        app.screen.action_publish_only()
        await wait_for(pilot, lambda: "memory-publish" in app.session_calls)
        await wait_for(pilot, lambda: "home" not in panel._unpublished_scopes)

    assert recorded == [(["sase", "memory", "init", "--no-commit"], str(Path.home()))]


async def test_publish_failure_keeps_unpublished_and_surfaces_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    def fake_run(
        argv: Any, *, cwd: Any = None, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(argv), 1, "", "fold failed\ncommit subject required\n"
        )

    monkeypatch.setattr(actions_mod, "run_noninteractive", fake_run)

    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._mark_scope_unpublished()
        await pilot.press("I")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPublishModal))
        app.screen.action_publish_only()
        await wait_for(
            pilot,
            lambda: any(
                "commit subject required" in msg for msg, _sev in app.notifications
            ),
        )
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")

    assert "sase" in panel._unpublished_scopes
    assert any(sev == "error" for _msg, sev in app.notifications)


async def test_footer_shows_edit_delete_for_writable_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        footer = panel_static_text(panel, "memory-panel-footer")
        assert "e edit" in footer
        assert "d delete" in footer
        assert "I publish" not in footer
        assert "a add" not in footer
