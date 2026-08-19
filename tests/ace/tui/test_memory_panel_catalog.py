"""Tests for the ACE memory panel's scope ring and snapshot cache."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.ace.tui import memory_panel_catalog as panel_catalog
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.memory.notes import AGENTS_PARENT
from sase.memory.read_log import MemoryReadPathSummary
from sase.xprompt import glossary_catalog as xprompt_catalog

_REAL_HOME_CONTENT_ROOT = panel_catalog._home_content_root


def _record(
    project_name: str,
    workspace: Path,
    *,
    display_name: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def _write_note(
    root: Path,
    stem: str,
    *,
    note_type: str = "long",
    parent: str = AGENTS_PARENT,
    description: str = "A note.",
    body: str = "# Body\n",
    memory_dir: str = "sase/memory",
) -> Path:
    path = root / memory_dir / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f"---\ntype: {note_type}\nparent: {parent}\n"
            f"description: {description}\n---\n{body}"
        ),
        encoding="utf-8",
    )
    return path


def _write_marker(
    checkout: Path,
    *,
    primary_workspace_dir: Path,
    project_name: str,
    project_key: str,
) -> Path:
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "checkout.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_key,
                "workspace_num": 7,
                "primary_workspace_dir": str(primary_workspace_dir),
                "registry_path": str(checkout / "registry.json"),
            }
        ),
        encoding="utf-8",
    )
    return marker_path


def _install_records(
    monkeypatch: pytest.MonkeyPatch, records: list[ProjectRecordWire]
) -> None:
    monkeypatch.setattr(
        xprompt_catalog, "list_project_records", lambda *_a, **_kw: records
    )


def _project_refs(
    ring: tuple[panel_catalog.MemoryScopeRef, ...],
) -> tuple[panel_catalog.MemoryScopeRef, ...]:
    return tuple(ref for ref in ring if ref.kind == "project")


def _home_ref(
    ring: tuple[panel_catalog.MemoryScopeRef, ...],
) -> panel_catalog.MemoryScopeRef:
    homes = [ref for ref in ring if ref.kind == "home"]
    assert len(homes) == 1
    assert homes[0] is ring[-1]
    return homes[0]


@pytest.fixture(autouse=True)
def _isolate_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    panel_catalog._snapshot_cache.clear()
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(panel_catalog, "_home_content_root", lambda: home)
    monkeypatch.setattr(panel_catalog, "get_use_chezmoi", lambda: False)


def test_ring_orders_projects_by_display_name_and_appends_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zeta_ws = tmp_path / "zeta"
    zeta_ws.mkdir()
    _write_note(zeta_ws, "zeta")

    alpha_ws = tmp_path / "alpha"
    alpha_ws.mkdir()
    # Launch project without a memory directory.

    mid_ws = tmp_path / "mid"
    mid_ws.mkdir()
    _write_note(mid_ws, "mid")

    records = [
        _record("gh_z__z", zeta_ws, display_name="Zeta"),
        _record("gh_a__a", alpha_ws, display_name="Alpha"),
        _record("gh_m__m", mid_ws, display_name="Mid"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_memory_scope_ring(str(alpha_ws))
    projects = _project_refs(ring)

    assert [ref.display_name for ref in projects] == ["Alpha", "Mid", "Zeta"]
    assert [ref.key for ref in projects] == ["gh_a__a", "gh_m__m", "gh_z__z"]
    by_key = {ref.key: ref for ref in projects}
    assert by_key["gh_a__a"].has_memory is False
    assert by_key["gh_m__m"].has_memory is True
    assert by_key["gh_z__z"].has_memory is True
    assert all(ref.display_name != ref.key for ref in projects)
    home = _home_ref(ring)
    assert home.key == "home"
    assert home.display_name == "Home"


def test_ring_includes_launch_project_from_numbered_workspace_without_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch_primary = tmp_path / "launch"
    launch_primary.mkdir()

    other_ws = tmp_path / "other"
    other_ws.mkdir()
    _write_note(other_ws, "other")

    numbered = tmp_path / "state" / "launch_7"
    numbered.mkdir(parents=True)
    _write_marker(
        numbered,
        primary_workspace_dir=launch_primary,
        project_name="Launch",
        project_key="gh_launch__launch",
    )

    records = [
        _record("gh_launch__launch", launch_primary, display_name="Launch"),
        _record("gh_other__other", other_ws, display_name="Other"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_memory_scope_ring(str(numbered))
    projects = _project_refs(ring)

    assert [ref.key for ref in projects] == ["gh_launch__launch", "gh_other__other"]
    by_key = {ref.key: ref for ref in projects}
    assert by_key["gh_launch__launch"].has_memory is False
    assert by_key["gh_other__other"].has_memory is True


def test_ring_deduplicates_launch_project_that_already_has_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_note(workspace, "alpha")
    records = [_record("gh_demo__demo", workspace, display_name="Demo")]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_memory_scope_ring(str(workspace))
    projects = _project_refs(ring)
    assert [ref.key for ref in projects] == ["gh_demo__demo"]


def test_ring_excludes_no_memory_project_when_not_the_launch_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_ws = tmp_path / "empty"
    empty_ws.mkdir()

    other_ws = tmp_path / "other"
    other_ws.mkdir()
    _write_note(other_ws, "other")

    records = [
        _record("gh_empty__empty", empty_ws, display_name="Empty"),
        _record("gh_other__other", other_ws, display_name="Other"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_memory_scope_ring(str(other_ws))

    assert [ref.key for ref in _project_refs(ring)] == ["gh_other__other"]


def test_ring_keeps_project_with_canonical_legacy_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    _write_note(broken_ws, "canonical")
    _write_note(broken_ws, "legacy", memory_dir="memory")

    launch_ws = tmp_path / "launch"
    launch_ws.mkdir()
    _write_note(launch_ws, "launch")

    records = [
        _record("gh_broken__broken", broken_ws, display_name="Broken"),
        _record("gh_launch__launch", launch_ws, display_name="Launch"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_memory_scope_ring(str(launch_ws))
    by_key = {ref.key: ref for ref in _project_refs(ring)}
    assert set(by_key) == {"gh_broken__broken", "gh_launch__launch"}
    assert by_key["gh_broken__broken"].has_memory is True


def test_home_scope_uses_chezmoi_root_and_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chezmoi = tmp_path / "chezmoi-home"
    chezmoi.mkdir()
    _write_note(chezmoi, "home-note")
    monkeypatch.setattr(panel_catalog, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(panel_catalog, "CHEZMOI_HOME", chezmoi)
    monkeypatch.setattr(panel_catalog, "_home_content_root", lambda: chezmoi)

    _install_records(monkeypatch, [])
    ring = panel_catalog.build_memory_scope_ring(None)
    home = _home_ref(ring)

    assert home.display_name == "Home (chezmoi)"
    assert home.content_root == str(chezmoi)
    assert home.has_memory is True


def test_home_scope_uses_path_home_when_chezmoi_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "plain-home"
    fake_home.mkdir()
    monkeypatch.setattr(panel_catalog, "_home_content_root", _REAL_HOME_CONTENT_ROOT)
    monkeypatch.setattr(panel_catalog, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(panel_catalog, "CHEZMOI_HOME", tmp_path / "unused-chezmoi")
    monkeypatch.setattr(panel_catalog.Path, "home", classmethod(lambda cls: fake_home))

    assert panel_catalog._home_content_root() == fake_home
    ref = panel_catalog._home_scope_ref()
    assert ref.display_name == "Home"
    assert ref.content_root == str(fake_home)


def test_load_snapshot_for_collision_yields_diagnostics_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    _write_note(broken_ws, "canonical")
    _write_note(broken_ws, "legacy", memory_dir="memory")
    record = _record("gh_broken__broken", broken_ws, display_name="Broken")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_broken__broken",
        display_name="Broken",
        content_root=str(broken_ws),
        memory_read_root=None,
        has_memory=True,
    )
    snapshot = panel_catalog.load_memory_scope_snapshot(ref)

    assert snapshot.notes == ()
    assert snapshot.diagnostics
    assert "canonical" in snapshot.diagnostics[0] or "legacy" in snapshot.diagnostics[0]


def test_load_snapshot_for_unreadable_root_yields_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_note(workspace, "alpha")
    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(workspace),
        memory_read_root=str(workspace / "sase" / "memory"),
        has_memory=True,
    )

    def boom(*_a: object, **_k: object) -> tuple[object, ...]:
        raise OSError("permission denied")

    monkeypatch.setattr(panel_catalog, "discover_memory_notes", boom)
    snapshot = panel_catalog.load_memory_scope_snapshot(ref)

    assert snapshot.notes == ()
    assert snapshot.diagnostics == ("permission denied",)


def test_snapshot_tree_nests_child_under_long_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_note(workspace, "short", note_type="short", description="Always loaded.")
    _write_note(workspace, "hub", description="Hub.")
    _write_note(
        workspace,
        "child",
        parent="sase/memory/hub.md",
        description="Child.",
    )
    _write_note(workspace, "zeta", description="Later root.")
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(workspace),
        memory_read_root=str(workspace / "sase" / "memory"),
        has_memory=True,
    )
    snapshot = panel_catalog.load_memory_scope_snapshot(ref)
    rows = [(node.note.path.stem, node.depth) for node in snapshot.tree]
    assert rows == [
        ("short", 0),
        ("hub", 0),
        ("child", 1),
        ("zeta", 0),
    ]

    hub = next(note for note in snapshot.notes if note.path.stem == "hub")
    child = next(note for note in snapshot.notes if note.path.stem == "child")
    parent, children = panel_catalog.memory_note_relations(snapshot, hub)
    assert parent == ()
    assert [note.path.stem for note in children] == ["child"]
    child_parent, child_children = panel_catalog.memory_note_relations(snapshot, child)
    assert [note.path.stem for note in child_parent] == ["hub"]
    assert child_children == ()

    short = next(note for note in snapshot.notes if note.path.stem == "short")
    short_parent, short_children = panel_catalog.memory_note_relations(snapshot, short)
    assert short_parent == ()
    assert short_children == ()


def test_snapshot_marks_generated_and_shadowed_stems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "isolated-home"
    _write_note(home, "shared")
    _write_note(home, "home-only")

    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_note(workspace, "shared")
    _write_note(workspace, "sase", note_type="short")
    _write_note(workspace, "task_types", note_type="short")
    _write_note(workspace, "glossary", note_type="short")
    _write_note(workspace, "sase_beads")
    _write_note(workspace, "sase_sizes", parent="sase/memory/sase_beads.md")
    _write_note(workspace, "local")
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(workspace),
        memory_read_root=str(workspace / "sase" / "memory"),
        has_memory=True,
    )
    snapshot = panel_catalog.load_memory_scope_snapshot(ref)

    assert snapshot.shadowed_stems == frozenset({"shared"})
    assert "sase/memory/sase.md" in snapshot.generated_paths
    assert "sase/memory/task_types.md" in snapshot.generated_paths
    assert "sase/memory/glossary.md" in snapshot.generated_paths
    assert "sase/memory/sase_beads.md" in snapshot.generated_paths
    assert "sase/memory/sase_sizes.md" in snapshot.generated_paths
    assert "sase/memory/local.md" not in snapshot.generated_paths


def test_home_snapshot_does_not_mark_project_only_generated_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "isolated-home"
    _write_note(home, "sase", note_type="short")
    _write_note(home, "glossary", note_type="short")
    _write_note(home, "sase_beads")
    monkeypatch.setattr(panel_catalog, "_home_content_root", lambda: home)

    snapshot = panel_catalog.load_memory_scope_snapshot(panel_catalog._home_scope_ref())
    assert "sase/memory/sase.md" in snapshot.generated_paths
    assert "sase/memory/task_types.md" in snapshot.generated_paths
    assert "sase/memory/glossary.md" not in snapshot.generated_paths
    assert "sase/memory/sase_beads.md" not in snapshot.generated_paths
    assert snapshot.shadowed_stems == frozenset()


def test_snapshot_includes_audited_read_summaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_note(workspace, "hub")
    summary = MemoryReadPathSummary(
        canonical_path="hub.md",
        read_count=2,
        distinct_agent_count=1,
        last_read_at="2026-08-19T12:00:00+00:00",
        last_agent="athena.ov",
        last_reason="Need hub context",
    )
    monkeypatch.setattr(
        panel_catalog, "read_memory_read_events", lambda **_k: (object(),)
    )
    monkeypatch.setattr(
        panel_catalog, "summarize_memory_reads_by_path", lambda _events: (summary,)
    )
    monkeypatch.setattr(panel_catalog, "project_memory_name", lambda _root: "Demo")

    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(workspace),
        memory_read_root=str(workspace / "sase" / "memory"),
        has_memory=True,
    )
    snapshot = panel_catalog.load_memory_scope_snapshot(ref)
    assert snapshot.read_summaries["hub.md"].last_agent == "athena.ov"
    assert snapshot.digests["sase/memory/hub.md"].sha256
    assert snapshot.stats["sase/memory/hub.md"].line_count > 0


def test_snapshot_cache_rereads_only_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    note_path = _write_note(workspace, "alpha", description="First.")
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_demo__demo",
        display_name="Demo",
        content_root=str(workspace),
        memory_read_root=str(workspace / "sase" / "memory"),
        has_memory=True,
    )

    first = panel_catalog.load_memory_scope_snapshot(ref)
    assert [note.path.stem for note in first.notes] == ["alpha"]

    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0
    second = panel_catalog.load_memory_scope_snapshot(ref)
    assert second is first

    _write_note(workspace, "beta", description="Second.")
    future_ns = note_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(workspace / "sase" / "memory", ns=(future_ns, future_ns))
    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0

    third = panel_catalog.load_memory_scope_snapshot(ref)
    assert third is not first
    assert [note.path.stem for note in third.notes] == ["alpha", "beta"]


def test_invalidate_memory_scope_drops_exactly_one_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_a = tmp_path / "a"
    ws_a.mkdir()
    _write_note(ws_a, "a")
    ws_b = tmp_path / "b"
    ws_b.mkdir()
    _write_note(ws_b, "b")

    records = [
        _record("gh_a__a", ws_a, display_name="A"),
        _record("gh_b__b", ws_b, display_name="B"),
    ]
    _install_records(monkeypatch, records)

    ref_a = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_a__a",
        display_name="A",
        content_root=str(ws_a),
        memory_read_root=str(ws_a / "sase" / "memory"),
        has_memory=True,
    )
    ref_b = panel_catalog.MemoryScopeRef(
        kind="project",
        key="gh_b__b",
        display_name="B",
        content_root=str(ws_b),
        memory_read_root=str(ws_b / "sase" / "memory"),
        has_memory=True,
    )
    panel_catalog.load_memory_scope_snapshot(ref_a)
    panel_catalog.load_memory_scope_snapshot(ref_b)
    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_a__a", "gh_b__b"}

    panel_catalog.invalidate_memory_scope("gh_a__a")

    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_b__b"}


def test_invalidate_unknown_scope_is_a_no_op() -> None:
    panel_catalog.invalidate_memory_scope("does-not-exist")
