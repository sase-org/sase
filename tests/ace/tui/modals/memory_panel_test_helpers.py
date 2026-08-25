"""Shared app harness and catalog builders for Memory panel tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from rich.console import Console, RenderableType
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui import memory_panel_catalog as panel_catalog
from sase.ace.tui.memory_panel_catalog import (
    MemoryNoteDigest,
    MemoryScopeRef,
    MemoryScopeSnapshot,
)
from sase.ace.tui.modals import memory_pane as memory_pane_module
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.ace.tui.modals.memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryPanelStrandRead,
    MemoryScopeChoice,
)
from sase.memory.inventory import MemoryStats
from sase.memory.notes import AGENTS_PARENT, MemoryNote
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    MemoryReadPathSummary,
)
from sase.memory.web.models import MemoryStrand, MemoryWeb


class MemoryPanelTestApp(App[None]):
    # The real ACE app disables the command palette; without this, its
    # default ``ctrl+p`` binding would shadow the Memory panel's own
    # ``ctrl+p`` (pick scope) binding in tests.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, panel: MemoryPane) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield self.panel


def _plain(renderable: RenderableType) -> str:
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def panel_static_text(panel: MemoryPane, widget_id: str) -> str:
    return _plain(panel.query_one(f"#{widget_id}", Static).content)


def note_row_text(panel: MemoryPane, index: int) -> str:
    option = panel._note_list().get_option_at_index(index)
    return _plain(option.prompt)


def scope_ref(
    key: str,
    display_name: str,
    *,
    kind: str = "project",
    has_memory: bool = True,
    memory_read_root: str | None = "/tmp/memory/sase/memory",
    content_root: str = "/tmp/memory",
) -> MemoryScopeRef:
    return MemoryScopeRef(
        kind=kind,  # type: ignore[arg-type]
        key=key,
        display_name=display_name,
        content_root=content_root,
        memory_read_root=memory_read_root,
        has_memory=has_memory,
    )


def memory_note(
    stem: str,
    *,
    note_type: str | None = "reference",
    parent: str = AGENTS_PARENT,
    priority: int = 20,
    description: str | None = None,
    body: str = "",
    type_source: str = "frontmatter",
    parent_source: str | None = None,
) -> MemoryNote:
    relative_path = f"sase/memory/{stem}.md"
    if parent_source is None:
        parent_source = "frontmatter" if parent != AGENTS_PARENT else "missing"
    return MemoryNote(
        path=Path(relative_path),
        type=note_type,
        parent=parent,
        description=description,
        body=body,
        frontmatter={},
        type_source=type_source,  # type: ignore[arg-type]
        parent_source=parent_source,  # type: ignore[arg-type]
        source_path=Path(relative_path),
        priority=priority,
    )


def memory_web_with_mentioning_strands(root: Path = Path("/tmp/memory")) -> MemoryWeb:
    """A ``closure: mentions`` web whose ``alpha`` strand mentions ``beta``."""
    memory_root = root / "sase" / "memory"

    def _strand(slug: str, keyword: str, body: str) -> MemoryStrand:
        relative_path = f"sase/memory/glossary/{slug}.md"
        return MemoryStrand(
            root=root,
            memory_root=memory_root,
            web_slug="glossary",
            slug=slug,
            path=memory_root / "glossary" / f"{slug}.md",
            relative_path=relative_path,
            keyword=keyword,
            aliases=(),
            summary=None,
            metadata={},
            body=body,
            raw_text=f"---\nkeyword: {keyword}\n---\n{body}",
            body_start=0,
            frontmatter={"keyword": keyword},
        )

    alpha = _strand("alpha", "Alpha Term", "Alpha body mentions Beta Term.")
    beta = _strand("beta", "Beta Term", "Beta body, unrelated.")
    return MemoryWeb(
        root=root,
        memory_root=memory_root,
        slug="glossary",
        path=memory_root / "glossary.md",
        relative_path="sase/memory/glossary.md",
        rendering_type="core",
        description="Glossary.",
        roster="inline",
        roster_label="GLOSSARY TERMS",
        strand_noun="term",
        closure="mentions",
        metadata={},
        body="Glossary body.",
        raw_text="---\ntype: core\nweb: true\nclosure: mentions\n---\nGlossary body.",
        body_start=0,
        frontmatter={"type": "core", "web": True, "closure": "mentions"},
        strands=(alpha, beta),
    )


def scope_snapshot(
    ref: MemoryScopeRef,
    notes: tuple[MemoryNote, ...] = (),
    *,
    webs: tuple[MemoryWeb, ...] = (),
    diagnostics: tuple[str, ...] = (),
    generated_paths: frozenset[str] = frozenset(),
    shadowed_stems: frozenset[str] = frozenset(),
    digests: dict[str, MemoryNoteDigest] | None = None,
    stats: dict[str, MemoryStats] | None = None,
    read_summaries: dict[str, MemoryReadPathSummary] | None = None,
) -> MemoryScopeSnapshot:
    return MemoryScopeSnapshot(
        scope=ref,
        notes=notes,
        tree=panel_catalog._build_note_tree(notes, webs),
        digests=digests or {},
        stats=stats or {},
        shadowed_stems=shadowed_stems,
        generated_paths=generated_paths,
        read_summaries=read_summaries or {},
        diagnostics=diagnostics,
        webs=webs,
        mention_catalogs=panel_catalog._mention_catalogs_for(webs),
    )


def install_fixed_load(
    monkeypatch: pytest.MonkeyPatch,
    ring: tuple[MemoryScopeRef, ...],
    snapshots: dict[str, MemoryScopeSnapshot],
    *,
    scope_index: int = 0,
) -> list[bool]:
    """Patch the panel's off-thread loaders and record which thread called them."""
    off_main_thread: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        session_scope_key: str | None = None,
        seed_from_current_project: bool = True,
    ) -> MemoryPanelInitialLoad:
        del launch_workspace, seed_from_current_project
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        index = scope_index
        for key in (initial_scope_key, session_scope_key):
            if key is None:
                continue
            matched = next(
                (i for i, candidate in enumerate(ring) if candidate.key == key),
                None,
            )
            if matched is not None:
                index = matched
                break
        if not ring:
            return MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None)
        return MemoryPanelInitialLoad(
            ring=ring, scope_index=index, snapshot=snapshots[ring[index].key]
        )

    def fake_scope_load(ref: MemoryScopeRef) -> MemoryScopeSnapshot:
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        return snapshots[ref.key]

    monkeypatch.setattr(
        memory_pane_module, "load_memory_panel_initial_state", fake_initial_load
    )
    monkeypatch.setattr(
        memory_pane_module, "load_memory_scope_snapshot", fake_scope_load
    )
    return off_main_thread


def install_fake_strand_read(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the panel's audited strand-read recorder with an instant fake.

    The real recorder resolves an interactive identity and does real disk
    I/O when no agent env is present, so this fake exists purely for test
    speed and determinism, not because selecting a strand row requires
    agent-identity env.
    """
    reads: list[str] = []

    def fake_record(
        _scope: MemoryScopeRef, *, web_slug: str, strand_slug: str
    ) -> MemoryPanelStrandRead:
        identity = f"{web_slug}:{strand_slug}"
        reads.append(identity)
        event = MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id=f"read-{identity}",
            timestamp="2026-08-24T12:00:00+00:00",
            project="demo",
            cwd="/tmp/demo",
            canonical_path=identity,
            resolved_path="",
            agent_name="agent-a",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir=None,
            reason=f"ACE MemoryPane previewed {identity}",
            byte_count=10,
            frontmatter_stripped=False,
            kind="strand",
            selectors=(identity,),
            resolved_targets=(identity,),
        )
        return MemoryPanelStrandRead(identity=identity, event=event)

    monkeypatch.setattr(
        memory_pane_module, "record_memory_panel_strand_read", fake_record
    )
    return reads


def install_fixed_scope_choices(
    monkeypatch: pytest.MonkeyPatch,
    choices: tuple[MemoryScopeChoice, ...],
) -> list[bool]:
    """Patch the panel's scope-picker loader with a fixed set of choices."""
    off_main_thread: list[bool] = []

    def fake_choices(
        _ring: tuple[MemoryScopeRef, ...],
    ) -> tuple[MemoryScopeChoice, ...]:
        off_main_thread.append(
            threading.current_thread() is not threading.main_thread()
        )
        return choices

    monkeypatch.setattr(memory_pane_module, "load_memory_scope_choices", fake_choices)
    return off_main_thread


__all__ = [
    "MemoryPanelTestApp",
    "install_fixed_load",
    "install_fixed_scope_choices",
    "memory_note",
    "note_row_text",
    "panel_static_text",
    "scope_ref",
    "scope_snapshot",
]
