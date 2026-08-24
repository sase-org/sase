"""Add/edit/delete through the Memory panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.memory_panel_catalog import MemoryScopeRef
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.ace.tui.modals.memory_panel_add import MemoryNoteFormModal
from sase.ace.tui.proc_producer_sites import PRODUCTION_PRODUCERS
from sase.memory.mutation import MemoryConflictError, MemoryMutationOutcome
from tests.ace.tui.modals.memory_panel_actions_test_helpers import (
    MemoryPanelActionsApp,
    fill_form,
    install_write_fakes,
    mutation_outcome,
    note_digest,
    skip_post_write_offers,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


def test_memory_write_producer_is_registered() -> None:
    ids = {site.site_id for site in PRODUCTION_PRODUCERS}
    assert "memory.write" in ids
    assert "memory.publish" in ids


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
        return mutation_outcome("beta", description="Middle.")

    install_write_fakes(monkeypatch, snapshots, create=fake_create)

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("a")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(app, stem="beta", description="Middle.")
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/beta.md")
        await skip_post_write_offers(pilot, app)
        assert "UNPUBLISHED" in panel_static_text(panel, "memory-panel-header")

    assert recorded[0]["stem"] == "beta"
    assert recorded[0]["note_type"] == "reference"
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
        "sase": scope_snapshot(
            ref, (note,), digests=note_digest("sase/memory/alpha.md")
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    recorded: list[dict[str, Any]] = []

    def fake_update(**kwargs: Any) -> MemoryMutationOutcome:
        recorded.append(kwargs)
        snapshots[ref.key] = scope_snapshot(
            ref,
            (memory_note("alpha", description="New."),),
            digests=note_digest("sase/memory/alpha.md"),
        )
        return mutation_outcome("alpha", description="New.")

    install_write_fakes(monkeypatch, snapshots, update=fake_update)

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("e")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryNoteFormModal))
        form = await fill_form(app, description="New.")
        form.action_submit()
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/alpha.md")
        await skip_post_write_offers(pilot, app)
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
                **note_digest("sase/memory/alpha.md"),
                **note_digest("sase/memory/beta.md", "def"),
                **note_digest("sase/memory/gamma.md", "ghi"),
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
        return mutation_outcome(
            Path(kwargs["relative_path"]).stem,
            backup_path=backup,
        )

    install_write_fakes(monkeypatch, snapshots, delete=fake_delete)

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
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
        assert "Tier: 2 (reference)" in confirm._subject
        await pilot.press("y")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/gamma.md")
        await skip_post_write_offers(pilot, app)

    assert app.session_calls == ["memory-delete"]
    assert any("Backup:" in message for message, _sev in app.notifications)
    assert any(str(backup) in message for message, _sev in app.notifications)


async def test_short_note_delete_warns_about_always_loaded_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("always", note_type="core", description="Always loaded.")
    snapshots = {
        "sase": scope_snapshot(
            ref, (note,), digests=note_digest("sase/memory/always.md")
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("d")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
        confirm = app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._subject is not None
        assert "Tier: 1 (core)" in confirm._subject
        assert "always-loaded agent context" in confirm._subject
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmActionModal))

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
        return mutation_outcome("hub")

    install_write_fakes(monkeypatch, snapshots, delete=fake_delete)

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
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
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmActionModal))

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

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
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
        assert not isinstance(app.screen, MemoryNoteFormModal)
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
            digests=note_digest("sase/memory/alpha.md"),
        )
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    loads = {"count": 0}

    def fake_delete(**_kwargs: Any) -> MemoryMutationOutcome:
        raise MemoryConflictError(Path("/tmp/memory/sase/memory/alpha.md"))

    def fake_scope_load(scope: MemoryScopeRef) -> Any:
        loads["count"] += 1
        return snapshots[scope.key]

    install_write_fakes(monkeypatch, snapshots, delete=fake_delete)
    monkeypatch.setattr(
        "sase.ace.tui.modals.memory_pane.load_memory_scope_snapshot",
        fake_scope_load,
    )

    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
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


async def test_footer_shows_edit_delete_for_writable_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPane()
    app = MemoryPanelActionsApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        footer = panel_static_text(panel, "memory-panel-footer")
        assert "e edit" in footer
        assert "d delete" in footer
        assert "I publish" not in footer
        assert "a add" not in footer
