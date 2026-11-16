"""Pinned Artifacts descriptor snapshots isolate TUI consumers from cache."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.testing import _startup as ace_startup
from sase.ace.tui._artifact_tab_descriptors import _assign_artifacts_digit_shortcuts
from sase.ace.tui.actions.artifacts_navigation import ArtifactsNavigationActionsMixin
from sase.ace.tui.artifact_tabs import (
    ArtifactsDescriptorSnapshot,
    ArtifactsDiscoveryStatus,
    ArtifactsTabDescriptor,
    artifacts_snapshot_of,
    bootstrap_artifacts_snapshot,
    snapshot_from_descriptors,
)
from sase.ace.tui.commands.catalog import build_command_catalog
from sase.ace.tui.commands.execute import execute_command
from sase.ace.tui.commands.types import CommandExecutor, CommandSpec
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.keymaps.bindings import build_app_bindings


def _descriptor(
    id_: str,
    *,
    digit: str | None = None,
    is_provider: bool = False,
) -> ArtifactsTabDescriptor:
    return ArtifactsTabDescriptor(
        id=id_,
        label=id_.title(),
        accent="#000000",
        pane_id=f"{id_}-pane",
        provider_kind="ref" if is_provider else None,
        digit_shortcut=digit,
    )


def _snapshot(
    *ids: str,
    generation: int = 1,
    status: ArtifactsDiscoveryStatus = ArtifactsDiscoveryStatus.COMPLETED,
    providers: tuple[str, ...] = (),
) -> ArtifactsDescriptorSnapshot:
    rows = [_descriptor(pane_id) for pane_id in ids]
    rows.extend(_descriptor(pane_id, is_provider=True) for pane_id in providers)
    return snapshot_from_descriptors(
        _assign_artifacts_digit_shortcuts(tuple(rows)),
        generation=generation,
        status=status,
        source_token=("test", generation),
        source_epoch=generation,
    )


def test_bootstrap_pending_completed_zero_and_failed_are_distinct() -> None:
    bootstrap = bootstrap_artifacts_snapshot(generation=0)
    assert bootstrap.is_pending
    assert not bootstrap.is_completed_zero_providers
    assert not bootstrap.is_failed

    completed_zero = _snapshot("stitches", "patches", "beads", generation=2)
    assert completed_zero.status is ArtifactsDiscoveryStatus.COMPLETED
    assert completed_zero.is_completed_zero_providers
    assert not completed_zero.is_pending
    assert not completed_zero.is_failed

    failed = snapshot_from_descriptors(
        completed_zero.descriptors,
        generation=3,
        status=ArtifactsDiscoveryStatus.FAILED,
    )
    assert failed.is_failed
    assert not failed.is_completed_zero_providers
    assert not failed.is_pending


def test_bootstrap_does_not_call_synchronous_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import artifact_tabs

    monkeypatch.setattr(
        artifact_tabs,
        "resolve_artifacts_subtabs",
        lambda: (_ for _ in ()).throw(AssertionError("discovery")),
    )
    snapshot = bootstrap_artifacts_snapshot()
    assert snapshot.status is ArtifactsDiscoveryStatus.BOOTSTRAP
    assert snapshot.ordered_ids


def test_standalone_discover_wraps_configured_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import artifact_tabs
    from sase.ace.tui.artifact_tabs import discover_artifacts_snapshot

    descriptors = _assign_artifacts_digit_shortcuts(
        (
            _descriptor("stitches"),
            _descriptor("patches"),
            _descriptor("ref:plan", is_provider=True),
        )
    )
    monkeypatch.setattr(artifact_tabs, "resolve_artifacts_subtabs", lambda: descriptors)
    monkeypatch.setattr(artifact_tabs, "artifacts_tab_cache_epoch", lambda: 7)
    monkeypatch.setattr(
        "sase.ace.tui._artifact_tab_discovery.provider_source_token",
        lambda: ("token",),
    )

    snapshot = discover_artifacts_snapshot()
    assert snapshot.status is ArtifactsDiscoveryStatus.COMPLETED
    assert snapshot.provider_ids == ("ref:plan",)
    assert snapshot.lookup("ref:plan") is not None


def test_discovery_cache_refresh_does_not_mutate_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import artifact_tabs

    committed = _snapshot(
        "stitches",
        "patches",
        "beads",
        providers=("ref:alpha",),
        generation=1,
    )
    later = _snapshot(
        "stitches",
        "patches",
        "beads",
        providers=("ref:beta",),
        generation=2,
    )
    monkeypatch.setattr(
        artifact_tabs, "resolve_artifacts_subtabs", lambda: later.descriptors
    )

    registry = load_keymap_registry({})
    catalog = build_command_catalog(registry, snapshot=committed)
    bindings = build_app_bindings(registry.app, snapshot=committed)
    catalog_ids = {
        spec.id: spec for spec in catalog if spec.id.startswith("artifacts.")
    }

    assert committed.lookup("ref:alpha") is not None
    assert committed.lookup("ref:beta") is None
    assert "artifacts.ref:alpha" in catalog_ids
    assert "artifacts.ref:beta" not in catalog_ids
    assert any(
        binding.action == "show_artifacts_digit(4)" and "Alpha" in binding.description
        for binding in bindings
    )
    assert artifact_tabs.resolve_artifacts_subtabs() is later.descriptors


def test_two_apps_keep_isolated_snapshots() -> None:
    snap_a = _snapshot("stitches", "patches", providers=("ref:a",), generation=11)
    snap_b = _snapshot("stitches", "patches", providers=("ref:b",), generation=12)
    app_a = SimpleNamespace(artifacts_descriptor_snapshot=snap_a)
    app_b = SimpleNamespace(artifacts_descriptor_snapshot=snap_b)

    assert artifacts_snapshot_of(app_a) is snap_a
    assert artifacts_snapshot_of(app_b) is snap_b
    assert snap_a.lookup("ref:a") is not None
    assert snap_a.lookup("ref:b") is None
    assert snap_b.lookup("ref:b") is not None
    assert snap_b.lookup("ref:a") is None


def test_catalog_executes_by_pane_id_and_keeps_digit_display_only() -> None:
    snapshot = _snapshot(
        "stitches",
        "patches",
        "beads",
        providers=("ref:plan",),
        generation=4,
    )
    catalog = {
        spec.id: spec
        for spec in build_command_catalog(load_keymap_registry({}), snapshot=snapshot)
        if spec.id.startswith("artifacts.")
    }
    plan = catalog["artifacts.ref:plan"]
    patches = catalog["artifacts.patches"]

    assert plan.executor.action == "show_artifacts_pane"
    assert plan.executor.pane_id == "ref:plan"
    assert plan.executor.digit is None
    plan_descriptor = snapshot.lookup("ref:plan")
    assert plan_descriptor is not None
    assert plan.key_display == plan_descriptor.digit_shortcut
    assert patches.executor.pane_id == "patches"
    assert patches.id == "artifacts.patches"


def test_stale_catalog_row_cannot_jump_to_a_different_pane() -> None:
    class _App:
        def __init__(self) -> None:
            self.pane_calls: list[str] = []
            self.digit_calls: list[int] = []

        def action_show_artifacts_pane(self, pane_id: str) -> None:
            self.pane_calls.append(pane_id)

        def action_show_artifacts_digit(self, digit: int) -> None:
            self.digit_calls.append(digit)

    app = _App()
    spec = CommandSpec(
        id="artifacts.ref:gone",
        label="Show Artifacts: Gone",
        key_sequence=("5",),
        key_display="5",
        category="Tabs",
        tabs=("artifacts",),
        executor=CommandExecutor(
            kind="app_action",
            action="show_artifacts_pane",
            pane_id="ref:gone",
            digit=5,
        ),
    )
    execute_command(app, spec)  # type: ignore[arg-type]
    assert app.pane_calls == ["ref:gone"]
    assert app.digit_calls == []


def test_missing_pane_notifies_unavailable() -> None:
    snapshot = _snapshot("stitches", "patches", "beads", generation=5)

    class _Harness(ArtifactsNavigationActionsMixin):
        def __init__(self) -> None:
            self.artifacts_descriptor_snapshot = snapshot
            self.notes: list[tuple[str, str]] = []
            self.switched: list[str] = []
            self.current_tab = "artifacts"
            self.current_artifacts_subtab = "patches"
            self.current_files_subtab = "files"

        def notify(self, message: str, severity: str = "information") -> None:
            self.notes.append((message, severity))

        def _switch_artifacts_subtab(self, subtab: str) -> None:
            self.switched.append(subtab)

    harness = _Harness()
    harness.action_show_artifacts_pane("ref:gone")
    assert harness.switched == []
    assert harness.notes == [("Artifacts pane Gone is unavailable", "warning")]

    harness.action_show_artifacts_pane("patches")
    assert harness.switched == ["patches"]


def test_acepage_fast_startup_patches_one_snapshot_factory() -> None:
    source = inspect.getsource(ace_startup._install_fast_startup_overrides)
    assert '_artifact_tabs, "discover_artifacts_snapshot"' in source
    assert '_artifact_tabs, "resolve_artifacts_subtabs"' in source
    for forbidden in (
        "commands.catalog",
        "keymaps.bindings",
        "help_modal",
        "commands.types",
        "widgets.artifacts.view",
    ):
        assert forbidden not in source


def test_acepage_digit_prefers_app_snapshot() -> None:
    snapshot = _snapshot("stitches", "patches", "beads", generation=9)
    page = AcePage.__new__(AcePage)
    page._app = SimpleNamespace(artifacts_descriptor_snapshot=snapshot)  # type: ignore[attr-defined]
    patches = snapshot.lookup("patches")
    assert patches is not None
    assert page.artifacts_digit("patches") == patches.digit_shortcut
