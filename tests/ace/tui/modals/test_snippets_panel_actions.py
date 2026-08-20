"""Add/edit/delete surfaces for the Snippets panel."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static, TextArea

from sase.ace.testing import wait_for
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.modals import snippets_panel_write as write_mod
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.snippets_panel import SnippetsPane, SnippetsPanel
from sase.ace.tui.modals.snippets_panel_add import SnippetFormModal
from sase.ace.tui.modals.snippets_panel_delete import (
    build_snippet_delete_subject,
    neighbor_trigger_after_delete,
)
from sase.ace.tui.proc_producer_sites import PRODUCTION_PRODUCERS
from sase.ace.tui.snippets_panel_catalog import SnippetDestination, SnippetProjectRef
from sase.snippet.models import SnippetMutationOutcome
from sase.snippet.mutation import SnippetConflictError
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
    snippet_entry,
)


class _ActionsApp(App[None]):
    def __init__(self, panel: SnippetsPanel) -> None:
        super().__init__()
        self.panel = panel
        self.session_calls: list[str] = []
        self.notifications: list[tuple[str, str]] = []
        self.invalidated: list[str] = []
        self.refreshed_surfaces = 0
        self._pending_snippet_saves: dict[str, str] = {}
        self._snippets_cache: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)

    def notify(
        self, message: str, *, severity: str = "information", **kwargs: Any
    ) -> None:
        self.notifications.append((message, severity))

    def _request_prompt_catalog_config_refresh(self, *, reason: str) -> None:
        self.invalidated.append(reason)

    def _refresh_visible_prompt_catalog_surfaces(self) -> None:
        self.refreshed_surfaces += 1

    def _push_post_write_actions(self, *args: Any, **kwargs: Any) -> None:
        return None

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


def _destination(path: str = "/tmp/sase.yml") -> SnippetDestination:
    return SnippetDestination(
        label="Project",
        path=path,
        display_path=path,
        digest="abc",
        selectable=True,
    )


def _snapshot_with_dest(
    ref: SnippetProjectRef,
    entries: tuple[Any, ...],
) -> Any:
    return project_snapshot(
        ref,
        entries,
        destinations=(_destination(),),
        default_destination_path="/tmp/sase.yml",
    )


def _outcome(
    trigger: str,
    *,
    template: str = "body$0",
    action: str = "created",
    restore_command: str = "sase snippet add todo 'body$0'",
) -> SnippetMutationOutcome:
    return SnippetMutationOutcome(
        project_name="sase",
        trigger=trigger,
        template=template,
        action=action,  # type: ignore[arg-type]
        read_path="/tmp/sase.yml",
        write_path="/tmp/sase.yml",
        apply_target=None,
        source_kind="project",
        via_chezmoi=False,
        restore_command=restore_command,
        affected_backlinks=(),
        revealed=None,
        removed_paths=("/tmp/sase.yml",) if action == "deleted" else (),
        dry_run=False,
        content_digest="abc",
        created=action == "created",
    )


def test_snippet_write_producer_is_registered() -> None:
    ids = {site.site_id for site in PRODUCTION_PRODUCERS}
    assert "snippet.write" in ids


def test_delete_subject_lists_backlinks_and_reveal() -> None:
    hidden = snippet_entry(
        "todo",
        kind="xprompt",
        path="/tmp/xprompt.md",
        writable=False,
        xprompt_name="todo",
    )
    winning = snippet_entry(
        "todo",
        inbound=("greet",),
        contributions=(
            hidden.origin,
            snippet_entry("todo", path="/tmp/sase.yml").origin,
        ),
    )
    subject = build_snippet_delete_subject(winning)
    assert "Trigger: todo" in subject
    assert "File: /tmp/sase.yml" in subject
    assert "1 snippet calls this trigger: greet" in subject
    assert "Reveals: /tmp/xprompt.md" in subject


def test_neighbor_trigger_after_delete_middle_and_last() -> None:
    triggers = ("alpha", "beta", "gamma")
    assert neighbor_trigger_after_delete(triggers, "beta") == "gamma"
    assert neighbor_trigger_after_delete(triggers, "gamma") == "beta"
    assert neighbor_trigger_after_delete(("solo",), "solo") is None


async def test_valid_add_writes_through_engine_and_selects_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    snapshots = {
        "sase": _snapshot_with_dest(ref, (snippet_entry("alpha"),)),
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[tuple[Any, ...]] = []

    def fake_add(
        project_ref: str | None,
        trigger: str,
        template: str,
        **kwargs: Any,
    ) -> SnippetMutationOutcome:
        recorded.append((project_ref, trigger, template, kwargs.get("force")))
        snapshots[ref.key] = _snapshot_with_dest(
            ref, (snippet_entry("alpha"), snippet_entry(trigger, raw=template))
        )
        return _outcome(trigger, template=template)

    monkeypatch.setattr(write_mod, "add_snippet", fake_add)
    monkeypatch.setattr(
        write_mod,
        "load_snippet_project_snapshot",
        lambda project: snapshots[project.key],
    )
    monkeypatch.setattr(write_mod, "invalidate_snippet_project", lambda _key: None)
    monkeypatch.setattr(write_mod, "build_post_write_action_offers", lambda *a, **k: ())

    panel = SnippetsPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, SnippetFormModal))
        form = app.screen
        assert isinstance(form, SnippetFormModal)
        form.query_one("#snippets-form-trigger", Input).value = "beta"
        form.query_one("#snippets-form-template", TextArea).text = "BETA$0"
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_trigger == "beta")

    assert recorded == [("sase", "beta", "BETA$0", False)]
    assert app.session_calls == ["snippet-add"]
    assert app.invalidated == ["snippets-panel-write"]
    assert app._pending_snippet_saves["beta"] == "BETA$0"
    assert app.refreshed_surfaces >= 1
    assert any("Added" in message for message, _sev in app.notifications)


async def test_edit_on_xprompt_opens_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entry = snippet_entry(
        "helper",
        kind="xprompt",
        path="/tmp/helper.md",
        writable=False,
        xprompt_name="helper",
    )
    install_fixed_load(
        monkeypatch, (ref,), {"sase": _snapshot_with_dest(ref, (entry,))}
    )
    opened: list[str] = []

    def fake_open(self: SnippetsPane) -> None:
        del self
        opened.append("source")

    monkeypatch.setattr(SnippetsPane, "action_open_source", fake_open)
    panel = SnippetsPanel()
    app = _ActionsApp(panel)

    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("e")
        await wait_for(pilot, lambda: opened == ["source"])
        assert isinstance(app.screen, SnippetsPanel)
        assert not isinstance(app.screen, SnippetFormModal)

    assert app.session_calls == []


async def test_delete_selects_neighbor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("alpha"),
        snippet_entry("beta"),
        snippet_entry("gamma"),
    )
    snapshots = {"sase": _snapshot_with_dest(ref, entries)}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    def fake_delete(
        _project: str | None, trigger: str, **kwargs: Any
    ) -> SnippetMutationOutcome:
        remaining = tuple(
            item
            for item in snapshots[ref.key].catalog.entries
            if item.trigger != trigger
        )
        snapshots[ref.key] = _snapshot_with_dest(ref, remaining)
        return _outcome(trigger, action="deleted")

    monkeypatch.setattr(write_mod, "delete_snippet", fake_delete)
    monkeypatch.setattr(
        write_mod,
        "load_snippet_project_snapshot",
        lambda project: snapshots[project.key],
    )
    monkeypatch.setattr(write_mod, "invalidate_snippet_project", lambda _key: None)
    monkeypatch.setattr(write_mod, "build_post_write_action_offers", lambda *a, **k: ())

    panel = SnippetsPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_trigger == "beta")
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        await pilot.press("y")
        await wait_for(pilot, lambda: panel._current_trigger == "gamma")

    assert app.session_calls == ["snippet-delete"]
    assert "beta" not in app._pending_snippet_saves
    assert any("Restore with:" in message for message, _sev in app.notifications)


async def test_conflict_retains_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    snapshots = {"sase": _snapshot_with_dest(ref, (snippet_entry("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    def fake_add(*_a: Any, **_k: Any) -> SnippetMutationOutcome:
        raise SnippetConflictError(Path("/tmp/sase.yml"))

    monkeypatch.setattr(write_mod, "add_snippet", fake_add)
    monkeypatch.setattr(write_mod, "invalidate_snippet_project", lambda _key: None)

    panel = SnippetsPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, SnippetFormModal))
        form = app.screen
        assert isinstance(form, SnippetFormModal)
        form.query_one("#snippets-form-trigger", Input).value = "beta"
        form.query_one("#snippets-form-template", TextArea).text = "BETA$0"
        form.action_submit()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._title == "Snippet config changed"
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, SnippetFormModal))
        kept = app.screen
        assert isinstance(kept, SnippetFormModal)
        assert kept.query_one("#snippets-form-trigger", Input).value == "beta"

    assert app.session_calls == ["snippet-add"]
    assert app.invalidated == []
    assert any(sev == "error" for _msg, sev in app.notifications)


async def test_footer_shows_conditional_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": _snapshot_with_dest(ref, (snippet_entry("alpha"),))},
    )
    panel = SnippetsPanel()
    app = _ActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        footer = panel_static_text(panel, "snippets-panel-footer")
        assert "d delete" in footer
        assert "e edit" in footer
        assert "a add" not in footer
