"""Tests for the Memory panel history entry points (phase `memory-panel`)."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.bindings import build_memory_bindings, memory_help_bindings
from sase.ace.tui.modals.memory_panel_history import (
    fetch_history_summary,
    history_cache_key,
    history_scope_for_panel_ref,
    history_value_text,
    selector_for_node,
)
from sase.ace.tui.modals.memory_panel_rendering import (
    _build_note_property_grid,
    build_note_card_meta,
    build_panel_footer,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)


def _version(
    ordinal: int,
    class_name: str = "authored",
    volume: int = 10,
    bead: str | None = "sase-1bc.12",
) -> dict:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": class_name,
        "hidden": False,
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": None,
            "created_words": None,
            "volume": volume,
        },
        "provenance": {"agent": "athena", "bead": bead},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": "abcd",
    }


def _summary(**override: object) -> dict:
    base: dict = {
        "selector": "sase/memory/gotchas.md",
        "core_selector": "sase/memory/gotchas.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "tip": "abc123",
        "now_epoch": 1790769600,
        "versions": [_version(1), _version(2)],
        "total": 2,
    }
    base.update(override)
    return base


def test_memory_bindings_include_history_and_changes() -> None:
    keymaps = MemoryPanelKeymaps()
    assert keymaps.open_history == "H"
    assert keymaps.open_changes == "C"
    actions = {binding.action for binding in build_memory_bindings(keymaps)}
    assert "open_history" in actions
    assert "open_changes" in actions
    descriptions = dict(memory_help_bindings(keymaps))
    # Help surfaces the effective keys for the new verbs.
    assert "H" in descriptions
    assert "C" in descriptions


def test_panel_footer_shows_history_only_when_enabled() -> None:
    keymaps = MemoryPanelKeymaps()
    hidden = build_panel_footer(
        keymaps, has_notes=True, has_source_path=True, ring_size=1
    )
    assert "H history" not in hidden
    assert "C changes" not in hidden
    shown = build_panel_footer(
        keymaps,
        has_notes=True,
        has_source_path=True,
        ring_size=1,
        history_enabled=True,
    )
    assert "H history" in shown
    assert "C changes" in shown
    empty = build_panel_footer(
        keymaps,
        has_notes=False,
        has_source_path=False,
        ring_size=1,
        history_enabled=True,
    )
    assert "history" not in empty


def test_history_row_format_uses_versions_and_provenance() -> None:
    value = history_value_text(_summary(), accent="#87D7FF")
    assert "2 versions" in value.plain
    assert "changed" in value.plain
    assert "sase-1bc.12" in value.plain
    # The mini sparkline reuses the pager sparkline cells.
    assert any(cell in value.plain for cell in "▁▂▃▄▅▆▇█")


def test_history_row_shows_amber_untracked_and_dim_loading() -> None:
    loading = history_value_text(None, accent="#87D7FF")
    assert loading.plain == "…"
    assert str(loading.style) == "dim"
    untracked = history_value_text(
        _summary(state="untracked", versions=[]), accent="#87D7FF"
    )
    assert untracked.plain == "untracked"
    assert str(untracked.style) == "yellow"


def test_history_value_reuses_pager_sparkline() -> None:
    value = history_value_text(_summary(), accent="#87D7FF")
    assert isinstance(value, Text)
    assert "2 versions" in value.plain
    assert any(cell in value.plain for cell in "▁▂▃▄▅▆▇█")


def test_note_property_grid_includes_history_row() -> None:
    note = memory_note("gotchas")
    grid = _build_note_property_grid(
        note,
        child_count=0,
        stats=None,
        digest=None,
        read_summary=None,
        source_path="/tmp/sase/memory/gotchas.md",
        accent="#fff",
        history=history_value_text(_summary(), accent="#fff"),
    )
    # Type, Parent, Children, History, Source.
    assert grid.row_count == 5
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(grid)
    text = capture.get()
    assert "History" in text
    assert "2 versions" in text


def test_note_card_meta_carries_history_for_notes() -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("gotchas", description="Gotchas.")
    snapshot = scope_snapshot(ref, (note,))
    rendered = build_note_card_meta(
        snapshot,
        note,
        accent="#87D7FF",
        history=history_value_text(_summary(), accent="#87D7FF"),
    )
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(rendered)
    assert "History" in capture.get()


def test_selector_for_node_covers_notes_and_strands() -> None:
    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    note = memory_note("gotchas")
    node = MemoryRailNode(note=note, depth=0)
    assert selector_for_node(node) == "sase/memory/gotchas.md"

    from tests.ace.tui.modals.memory_panel_test_helpers import (
        memory_web_with_mentioning_strands,
    )

    web = memory_web_with_mentioning_strands()
    strand = web.strands[0]
    strand_node = MemoryRailNode(
        note=note, depth=1, web=web, strand=strand, strand_scope="project"
    )
    selector = selector_for_node(strand_node)
    assert selector is not None
    assert selector.startswith(f"{web.slug}:")


def test_history_scope_uses_content_root_never_cwd(monkeypatch) -> None:
    import sase.ace.tui.modals.memory_panel_history as history_module

    seen: dict[str, str] = {}

    class _Service:
        def project_scope(self, root) -> object:
            seen["root"] = str(root)
            return object()

    ref = scope_ref("sase", "sase", content_root="/tmp/from-ring")
    monkeypatch.chdir("/tmp")
    result = history_scope_for_panel_ref(ref, _Service())
    assert result is not None
    assert seen["root"] == "/tmp/from-ring"


def test_history_cache_key_includes_scope_subject_and_tip() -> None:
    summary = _summary()
    assert history_cache_key(summary) == (
        "project:sase",
        "sase/memory/gotchas.md",
        "abc123",
    )


def test_history_summary_fetch_is_fail_open() -> None:
    class _FailingService:
        def sync(self, _scope):  # noqa: ANN001, ANN202
            raise RuntimeError("sync down")

        def timeline(self, _scope, _selector, **_kwargs):  # noqa: ANN001, ANN202
            raise RuntimeError("timeline down")

    class _Scope:
        scope_key = "project:sase"
        repo_root = "/tmp"

    assert fetch_history_summary(_FailingService(), _Scope(), "gotchas.md") is None


def test_history_row_loads_without_blocking() -> None:
    """The card render never calls the service synchronously."""
    from sase.ace.tui.modals.memory_pane import MemoryPane

    pane = MemoryPane.__new__(MemoryPane)
    pane._ring = (scope_ref("sase", "sase", content_root="/tmp/from-ring"),)
    pane._scope_index = 0
    pane._loading = False
    pane._accent = "#87D7FF"
    pane._history_latest = {}
    pane._history_request = None
    pane._history_worker = None
    pane._history_service = None
    calls: list[tuple[str, str]] = []

    def _fake_ensure(scope_key: str, selector: str) -> None:
        calls.append((scope_key, selector))

    pane._ensure_history_load = _fake_ensure  # type: ignore[method-assign]
    pane._history_enabled_for_panel = lambda: True  # type: ignore[method-assign]

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    node = MemoryRailNode(note=memory_note("gotchas"), depth=0)

    def _blocking_fetch(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("service must not be called on the render path")

    import sase.ace.tui.modals.memory_panel_history as history_module

    original = history_module.fetch_history_summary
    history_module.fetch_history_summary = _blocking_fetch  # type: ignore[assignment]
    try:
        rendered = pane._history_renderable_for_node(node)
    finally:
        history_module.fetch_history_summary = original
    assert isinstance(rendered, Text)
    assert rendered.plain == "…"
    assert calls == [("sase", "sase/memory/gotchas.md")]


def test_config_schema_accepts_history_keymaps() -> None:
    from jsonschema import Draft7Validator

    from tests._config_schema_helpers import schema

    Draft7Validator(schema()).validate(
        {"ace": {"keymaps": {"memory": {"open_history": "H", "open_changes": "C"}}}}
    )
