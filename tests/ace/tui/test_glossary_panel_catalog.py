"""Tests for the ACE glossary panel's project ring and snapshot cache."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.ace.tui import glossary_panel_catalog as panel_catalog
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.xprompt import glossary_catalog as xprompt_catalog


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


def _write_config(workspace: Path, body: str) -> Path:
    config_path = workspace / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")
    return config_path


def _write_glossary_web(
    workspace: Path,
    *,
    alpha_body: str = "First term stands alone.\n",
    beta_body: str | None = None,
) -> Path:
    descriptor = workspace / "sase" / "memory" / "glossary.md"
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster: inline\n"
        "roster_label: GLOSSARY TERMS\n"
        "---\n\n"
        "Glossary descriptor.\n",
        encoding="utf-8",
    )
    strand_dir = descriptor.parent / "glossary"
    strand_dir.mkdir(parents=True, exist_ok=True)
    (strand_dir / "alpha.md").write_text(
        "---\nkeyword: Alpha\n---\n\n" + alpha_body,
        encoding="utf-8",
    )
    if beta_body is not None:
        (strand_dir / "beta.md").write_text(
            "---\nkeyword: Beta\n---\n\n" + beta_body,
            encoding="utf-8",
        )
    return descriptor


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


@pytest.fixture(autouse=True)
def _clear_snapshot_cache_fixture() -> None:
    panel_catalog._snapshot_cache.clear()


def test_ring_orders_by_display_name_and_includes_launch_project_without_glossary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zeta_ws = tmp_path / "zeta"
    zeta_ws.mkdir()
    _write_glossary_web(zeta_ws)

    alpha_ws = tmp_path / "alpha"
    alpha_ws.mkdir()
    _write_config(alpha_ws, "timezone: UTC\n")  # no glossary web declared

    mid_ws = tmp_path / "mid"
    mid_ws.mkdir()
    _write_glossary_web(mid_ws)

    records = [
        _record("gh_z__z", zeta_ws, display_name="Zeta"),
        _record("gh_a__a", alpha_ws, display_name="Alpha"),
        _record("gh_m__m", mid_ws, display_name="Mid"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_glossary_project_ring(str(alpha_ws))

    assert [ref.display_name for ref in ring] == ["Alpha", "Mid", "Zeta"]
    assert [ref.key for ref in ring] == ["gh_a__a", "gh_m__m", "gh_z__z"]
    by_key = {ref.key: ref for ref in ring}
    assert by_key["gh_a__a"].has_glossary is False
    assert by_key["gh_m__m"].has_glossary is True
    assert by_key["gh_z__z"].has_glossary is True
    # The user-facing field is the display name, never the ProjectSpec key.
    assert all(ref.display_name != ref.key for ref in ring)


def test_ring_includes_launch_project_from_numbered_workspace_without_glossary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch_primary = tmp_path / "launch"
    launch_primary.mkdir()
    _write_config(launch_primary, "timezone: UTC\n")

    other_ws = tmp_path / "other"
    other_ws.mkdir()
    _write_glossary_web(other_ws)

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

    ring = panel_catalog.build_glossary_project_ring(str(numbered))

    assert [ref.key for ref in ring] == ["gh_launch__launch", "gh_other__other"]
    by_key = {ref.key: ref for ref in ring}
    assert by_key["gh_launch__launch"].has_glossary is False
    assert by_key["gh_other__other"].has_glossary is True


def test_ring_excludes_no_glossary_project_when_not_the_launch_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_ws = tmp_path / "empty"
    empty_ws.mkdir()
    _write_config(empty_ws, "timezone: UTC\n")

    other_ws = tmp_path / "other"
    other_ws.mkdir()
    _write_glossary_web(other_ws)

    records = [
        _record("gh_empty__empty", empty_ws, display_name="Empty"),
        _record("gh_other__other", other_ws, display_name="Other"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_glossary_project_ring(str(other_ws))

    assert [ref.key for ref in ring] == ["gh_other__other"]


def test_ring_excludes_project_with_malformed_glossary_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    write_path = broken_ws / "sase" / "memory" / "glossary.md"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(
        "---\ntype: core\nweb: 'yes'\n---\n\nBroken.\n",
        encoding="utf-8",
    )

    launch_ws = tmp_path / "launch"
    launch_ws.mkdir()
    _write_glossary_web(launch_ws)

    records = [
        _record("gh_broken__broken", broken_ws, display_name="Broken"),
        _record("gh_launch__launch", launch_ws, display_name="Launch"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_glossary_project_ring(str(launch_ws))

    assert [ref.key for ref in ring] == ["gh_launch__launch"]


def test_load_snapshot_for_catalog_error_yields_diagnostics_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    _write_glossary_web(broken_ws)
    record = _record("gh_broken__broken", broken_ws, display_name="Broken")
    _install_records(monkeypatch, [record])
    monkeypatch.setattr(
        xprompt_catalog,
        "build_glossary_catalog",
        lambda _entries: (_ for _ in ()).throw(ValueError("bad glossary")),
    )

    ref = panel_catalog.GlossaryProjectRef(
        key="gh_broken__broken",
        display_name="Broken",
        workspace_dir=str(broken_ws),
        has_glossary=True,
    )
    snapshot = panel_catalog.load_glossary_project_snapshot(ref)

    assert snapshot.catalog is None
    assert snapshot.diagnostics
    assert "bad glossary" in snapshot.diagnostics[0]
    assert snapshot.reverse_references == {}


def test_snapshot_cache_rereads_only_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    descriptor_path = _write_glossary_web(workspace)
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.GlossaryProjectRef(
        key="gh_demo__demo",
        display_name="Demo",
        workspace_dir=str(workspace),
        has_glossary=True,
    )

    first = panel_catalog.load_glossary_project_snapshot(ref)
    assert first.catalog is not None
    assert [entry.term for entry in first.catalog.entries] == ["Alpha"]

    # Bypass the re-stat throttle without changing the file: the (mtime,
    # size) signature is unchanged, so the cached snapshot must come back.
    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0
    second = panel_catalog.load_glossary_project_snapshot(ref)
    assert second is first

    _write_glossary_web(workspace, beta_body="Second term added.\n")
    future_ns = descriptor_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(descriptor_path, ns=(future_ns, future_ns))
    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0

    third = panel_catalog.load_glossary_project_snapshot(ref)
    assert third is not first
    assert third.catalog is not None
    assert [entry.term for entry in third.catalog.entries] == ["Alpha", "Beta"]


def test_invalidate_glossary_project_drops_exactly_one_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_a = tmp_path / "a"
    ws_a.mkdir()
    _write_glossary_web(ws_a)
    ws_b = tmp_path / "b"
    ws_b.mkdir()
    _write_glossary_web(ws_b)

    records = [
        _record("gh_a__a", ws_a, display_name="A"),
        _record("gh_b__b", ws_b, display_name="B"),
    ]
    _install_records(monkeypatch, records)

    ref_a = panel_catalog.GlossaryProjectRef(
        key="gh_a__a", display_name="A", workspace_dir=str(ws_a), has_glossary=True
    )
    ref_b = panel_catalog.GlossaryProjectRef(
        key="gh_b__b", display_name="B", workspace_dir=str(ws_b), has_glossary=True
    )
    panel_catalog.load_glossary_project_snapshot(ref_a)
    panel_catalog.load_glossary_project_snapshot(ref_b)
    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_a__a", "gh_b__b"}

    panel_catalog.invalidate_glossary_project("gh_a__a")

    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_b__b"}


def test_invalidate_unknown_project_is_a_no_op() -> None:
    panel_catalog.invalidate_glossary_project("does-not-exist")


def test_glossary_entry_relations_returns_outbound_and_inbound_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_glossary_web(
        workspace,
        alpha_body="Alpha mentions Beta.\n",
        beta_body="A leaf term.\n",
    )
    strand_dir = workspace / "sase" / "memory" / "glossary"
    (strand_dir / "gamma.md").write_text(
        "---\nkeyword: Gamma\n---\n\nGamma also mentions Beta.\n",
        encoding="utf-8",
    )
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])

    ref = panel_catalog.GlossaryProjectRef(
        key="gh_demo__demo",
        display_name="Demo",
        workspace_dir=str(workspace),
        has_glossary=True,
    )
    snapshot = panel_catalog.load_glossary_project_snapshot(ref)
    assert snapshot.catalog is not None
    by_term = {entry.term: entry for entry in snapshot.catalog.entries}

    alpha_outbound, alpha_inbound = panel_catalog.glossary_entry_relations(
        snapshot, by_term["Alpha"]
    )
    assert [entry.term for entry in alpha_outbound] == ["Beta"]
    assert alpha_inbound == ()

    beta_outbound, beta_inbound = panel_catalog.glossary_entry_relations(
        snapshot, by_term["Beta"]
    )
    assert beta_outbound == ()
    assert [entry.term for entry in beta_inbound] == ["Alpha", "Gamma"]
