"""Tests for the ACE snippets panel's project ring and snapshot cache."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.ace.tui import snippets_panel_catalog as panel_catalog
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.snippet.models import SnippetCatalog
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


_ONE_SNIPPET = """ace:
  snippets:
    alpha: |-
      first$0
"""

_TWO_SNIPPETS = """ace:
  snippets:
    alpha: |-
      first$0
    beta: |-
      second$0
"""


def test_ring_orders_by_display_name_and_includes_every_enabled_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zeta_ws = tmp_path / "zeta"
    zeta_ws.mkdir()
    _write_config(zeta_ws, _ONE_SNIPPET)

    alpha_ws = tmp_path / "alpha"
    alpha_ws.mkdir()
    _write_config(alpha_ws, "timezone: UTC\n")

    mid_ws = tmp_path / "mid"
    mid_ws.mkdir()
    _write_config(mid_ws, _ONE_SNIPPET)

    records = [
        _record("gh_z__z", zeta_ws, display_name="Zeta"),
        _record("gh_a__a", alpha_ws, display_name="Alpha"),
        _record("gh_m__m", mid_ws, display_name="Mid"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_snippet_project_ring(str(alpha_ws))

    assert [ref.display_name for ref in ring] == ["Alpha", "Mid", "Zeta"]
    assert [ref.key for ref in ring] == ["gh_a__a", "gh_m__m", "gh_z__z"]
    assert all(ref.display_name != ref.key for ref in ring)


def test_ring_includes_launch_project_from_numbered_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch_primary = tmp_path / "launch"
    launch_primary.mkdir()
    _write_config(launch_primary, "timezone: UTC\n")

    other_ws = tmp_path / "other"
    other_ws.mkdir()
    _write_config(other_ws, _ONE_SNIPPET)

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

    ring = panel_catalog.build_snippet_project_ring(str(numbered))

    assert [ref.key for ref in ring] == ["gh_launch__launch", "gh_other__other"]


def test_ring_keeps_project_with_malformed_ace_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    _write_config(broken_ws, "ace: [not, a, mapping]\n")

    launch_ws = tmp_path / "launch"
    launch_ws.mkdir()
    _write_config(launch_ws, "timezone: UTC\n")

    records = [
        _record("gh_broken__broken", broken_ws, display_name="Broken"),
        _record("gh_launch__launch", launch_ws, display_name="Launch"),
    ]
    _install_records(monkeypatch, records)

    ring = panel_catalog.build_snippet_project_ring(str(launch_ws))

    assert {ref.key for ref in ring} == {"gh_broken__broken", "gh_launch__launch"}


def test_load_snapshot_for_malformed_ace_yields_diagnostics_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_ws = tmp_path / "broken"
    broken_ws.mkdir()
    _write_config(broken_ws, "ace: [not, a, mapping]\n")
    record = _record("gh_broken__broken", broken_ws, display_name="Broken")
    _install_records(monkeypatch, [record])
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )

    ref = panel_catalog.SnippetProjectRef(
        key="gh_broken__broken",
        display_name="Broken",
        workspace_dir=str(broken_ws),
    )
    snapshot = panel_catalog.load_snippet_project_snapshot(ref)

    assert snapshot.catalog is not None
    assert snapshot.catalog.entries == ()
    assert snapshot.diagnostics
    assert any("ace must be a YAML mapping" in item for item in snapshot.diagnostics)


def test_load_snapshot_exception_becomes_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: object, **_k: object) -> SnippetCatalog:
        raise RuntimeError("catalog exploded")

    monkeypatch.setattr(panel_catalog, "load_snippet_catalog", boom)
    ref = panel_catalog.SnippetProjectRef(
        key="gh_demo__demo", display_name="Demo", workspace_dir=""
    )
    snapshot = panel_catalog.load_snippet_project_snapshot(ref)

    assert snapshot.catalog is None
    assert snapshot.diagnostics
    assert "catalog exploded" in snapshot.diagnostics[0]
    assert "Demo" in snapshot.diagnostics[0]


def test_snapshot_cache_rereads_only_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    config_path = _write_config(workspace, _ONE_SNIPPET)
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )

    ref = panel_catalog.SnippetProjectRef(
        key="gh_demo__demo",
        display_name="Demo",
        workspace_dir=str(workspace),
    )

    first = panel_catalog.load_snippet_project_snapshot(ref)
    assert first.catalog is not None
    assert [entry.trigger for entry in first.catalog.entries] == ["alpha"]

    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0
    second = panel_catalog.load_snippet_project_snapshot(ref)
    assert second is first

    config_path.write_text(_TWO_SNIPPETS, encoding="utf-8")
    future_ns = config_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(config_path, ns=(future_ns, future_ns))
    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0

    third = panel_catalog.load_snippet_project_snapshot(ref)
    assert third is not first
    assert third.catalog is not None
    assert [entry.trigger for entry in third.catalog.entries] == ["alpha", "beta"]


def test_snapshot_cache_rereads_when_config_token_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    _write_config(workspace, _ONE_SNIPPET)
    record = _record("gh_demo__demo", workspace, display_name="Demo")
    _install_records(monkeypatch, [record])
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    tokens = iter([("token-a",), ("token-b",)])
    monkeypatch.setattr(panel_catalog, "_config_token", lambda: next(tokens))

    ref = panel_catalog.SnippetProjectRef(
        key="gh_demo__demo",
        display_name="Demo",
        workspace_dir=str(workspace),
    )
    first = panel_catalog.load_snippet_project_snapshot(ref)
    for entry in panel_catalog._snapshot_cache.values():
        entry.last_checked_monotonic = 0.0
    second = panel_catalog.load_snippet_project_snapshot(ref)
    assert second is not first


def test_invalidate_snippet_project_drops_exactly_one_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_a = tmp_path / "a"
    ws_a.mkdir()
    _write_config(ws_a, _ONE_SNIPPET)
    ws_b = tmp_path / "b"
    ws_b.mkdir()
    _write_config(ws_b, _ONE_SNIPPET)

    records = [
        _record("gh_a__a", ws_a, display_name="A"),
        _record("gh_b__b", ws_b, display_name="B"),
    ]
    _install_records(monkeypatch, records)
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )

    ref_a = panel_catalog.SnippetProjectRef(
        key="gh_a__a", display_name="A", workspace_dir=str(ws_a)
    )
    ref_b = panel_catalog.SnippetProjectRef(
        key="gh_b__b", display_name="B", workspace_dir=str(ws_b)
    )
    panel_catalog.load_snippet_project_snapshot(ref_a)
    panel_catalog.load_snippet_project_snapshot(ref_b)
    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_a__a", "gh_b__b"}

    panel_catalog.invalidate_snippet_project("gh_a__a")

    assert set(panel_catalog._snapshot_cache.keys()) == {"gh_b__b"}


def test_invalidate_unknown_project_is_a_no_op() -> None:
    panel_catalog.invalidate_snippet_project("does-not-exist")


def test_snippet_entry_relations_returns_outbound_and_inbound_entries() -> None:
    from tests.ace.tui.modals.snippets_panel_test_helpers import (
        project_ref,
        project_snapshot,
        snippet_entry,
    )

    ref = project_ref("sase", "sase")
    extra = snippet_entry("extra", outbound=("helper",))
    helper = snippet_entry("helper", inbound=("extra", "wrap"))
    wrap = snippet_entry("wrap", outbound=("helper",))
    snapshot = project_snapshot(ref, (extra, helper, wrap))
    assert snapshot.catalog is not None
    by_trigger = {entry.trigger: entry for entry in snapshot.catalog.entries}

    wrap_out, wrap_in = panel_catalog.snippet_entry_relations(
        snapshot, by_trigger["wrap"]
    )
    assert [entry.trigger for entry in wrap_out] == ["helper"]
    assert wrap_in == ()

    helper_out, helper_in = panel_catalog.snippet_entry_relations(
        snapshot, by_trigger["helper"]
    )
    assert helper_out == ()
    assert [entry.trigger for entry in helper_in] == ["extra", "wrap"]


def test_snippet_entry_relations_empty_without_catalog() -> None:
    from tests.ace.tui.modals.snippets_panel_test_helpers import (
        project_ref,
        project_snapshot,
        snippet_entry,
    )

    ref = project_ref("sase", "sase")
    snapshot = project_snapshot(ref, (), diagnostics=("boom",))
    outbound, inbound = panel_catalog.snippet_entry_relations(
        snapshot, snippet_entry("helper")
    )
    assert outbound == ()
    assert inbound == ()
