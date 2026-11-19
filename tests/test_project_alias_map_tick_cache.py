"""Tick-managed project alias-map cache (sase-1tz.2.1.11, phase ui_io_offload).

The TUI opts in through ``set_project_alias_map_tick_managed``. Then warm
lookups are memory-only, and ``refresh_project_display_snapshot`` (a worker
or tick boundary) revalidates the map through the ProjectSpec freshness
token. Processes that never opt in keep loading the map fresh on every call.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from sase import _project_display_cache as display_cache
from sase import project_aliases
from sase import project_display_names as pdn
from sase.core.project_lifecycle_wire import ProjectRecordWire
from tests._main_thread_fs_guard import main_thread_fs_guard


def _write_spec(root: Path, key: str, aliases: str | None = None) -> Path:
    project_dir = root / key
    project_dir.mkdir(parents=True, exist_ok=True)
    workspace = root.parent / "workspaces" / key
    workspace.mkdir(parents=True, exist_ok=True)
    spec = project_dir / f"{key}.sase"
    lines = []
    if aliases is not None:
        lines.append(f"PROJECT_ALIASES: {aliases}")
    lines.append(f"WORKSPACE_DIR: {workspace}")
    spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return spec


@pytest.fixture
def root(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    _write_spec(projects, "bob-cli", "bob")
    _write_spec(projects, "widgets")
    return projects


@pytest.fixture
def clean_display_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(display_cache, "_PROJECT_DISPLAY_NAME_CACHE", None)
    monkeypatch.setattr(display_cache, "_PROJECT_DISPLAY_FRESHNESS_TOKENS", None)
    display_cache.set_project_alias_map_tick_managed(False)
    yield
    display_cache.set_project_alias_map_tick_managed(False)


@pytest.fixture
def tick_managed(clean_display_cache: None) -> Iterator[None]:
    display_cache.set_project_alias_map_tick_managed(True)
    yield


def _count_list_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _wrap(module: ModuleType, label: str) -> None:
        real = module.list_project_records

        def counting(*args: object, **kwargs: object) -> list[ProjectRecordWire]:
            calls.append(label)
            return real(*args, **kwargs)

        monkeypatch.setattr(module, "list_project_records", counting)

    _wrap(project_aliases, "aliases")
    _wrap(display_cache, "display")
    return calls


def test_unmanaged_process_loads_fresh_on_every_call(
    root: Path, clean_display_cache: None
) -> None:
    assert project_aliases.load_project_alias_map(root) == {"bob": "bob-cli"}
    _write_spec(root, "bob-cli", "robert")

    assert project_aliases.resolve_project_alias_ref("robert", root) == "bob-cli"
    assert project_aliases.load_project_alias_map(root) == {"robert": "bob-cli"}
    assert display_cache._PROJECT_ALIAS_MAPS == {}


def test_guard_catches_the_uncached_lookup(
    root: Path, clean_display_cache: None
) -> None:
    """Negative control: the unmanaged path stats ProjectSpecs on this thread."""
    with main_thread_fs_guard() as violations:
        with pytest.raises(AssertionError):
            project_aliases.resolve_project_alias_ref("bob", root)
    assert violations


def test_warm_lookup_does_no_main_thread_filesystem_io(
    root: Path, tick_managed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob-cli"
    calls = _count_list_calls(monkeypatch)

    with main_thread_fs_guard() as violations:
        resolved = project_aliases.resolve_project_alias_ref("bob", root)
        unknown = project_aliases.resolve_project_alias_ref("nobody", root)
        alias_map = project_aliases.load_project_alias_map(root)

    assert violations == []
    assert calls == []
    assert resolved == "bob-cli"
    assert unknown == "nobody"
    assert alias_map == {"bob": "bob-cli"}
    # Callers get a copy; mutating it never corrupts the shared cache.
    alias_map["mutated"] = "oops"
    assert project_aliases.load_project_alias_map(root) == {"bob": "bob-cli"}


def test_refresh_revalidates_alias_map_when_project_spec_changes(
    root: Path, tick_managed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity_invalidations: list[int] = []
    monkeypatch.setattr(
        "sase.macro.project_identity.invalidate_macro_project_identity",
        lambda: identity_invalidations.append(1),
    )
    assert pdn.refresh_project_display_snapshot(root) is True
    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob-cli"
    identity_invalidations.clear()

    _write_spec(root, "bob-cli", "robert")
    # Between refresh boundaries the warm map is served from memory.
    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob-cli"

    pdn.refresh_project_display_snapshot(root)

    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob"
    assert project_aliases.resolve_project_alias_ref("robert", root) == "bob-cli"
    assert identity_invalidations, "a changed alias map must invalidate identity"


def test_refresh_with_unchanged_token_reloads_nothing(
    root: Path, tick_managed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdn.refresh_project_display_snapshot(root)
    calls = _count_list_calls(monkeypatch)

    assert pdn.refresh_project_display_snapshot(root) is False
    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob-cli"
    assert calls == []


def test_refresh_prewarms_a_cold_alias_map(
    root: Path, tick_managed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Display snapshot already current, alias map still cold.
    pdn.refresh_project_display_snapshot(root)
    project_aliases._invalidate_macro_project_identity()
    assert display_cache._PROJECT_ALIAS_MAPS == {}

    pdn.refresh_project_display_snapshot(root)
    calls = _count_list_calls(monkeypatch)
    with main_thread_fs_guard() as violations:
        resolved = project_aliases.resolve_project_alias_ref("bob", root)

    assert violations == []
    assert calls == []
    assert resolved == "bob-cli"


def test_refresh_built_map_matches_uncached_loader(
    root: Path, tick_managed: None
) -> None:
    _write_spec(root, "home", "house")
    _write_spec(root, "gadgets", "gizmo")

    pdn.refresh_project_display_snapshot(root)
    cache_key = display_cache._projects_root_cache_key(root)
    refreshed, _token = display_cache._PROJECT_ALIAS_MAPS[cache_key]

    assert dict(refreshed) == project_aliases._load_project_alias_map_uncached(root)
    assert dict(refreshed) == {"bob": "bob-cli", "gizmo": "gadgets"}


def test_in_process_invalidation_drops_the_cached_map(
    root: Path, tick_managed: None
) -> None:
    assert project_aliases.resolve_project_alias_ref("bob", root) == "bob-cli"
    _write_spec(root, "bob-cli", "robert")

    pdn.invalidate_project_display_snapshot(root)
    assert project_aliases.resolve_project_alias_ref("robert", root) == "bob-cli"

    _write_spec(root, "bob-cli", "bobby")
    # Alias mutation funnels invalidate through the identity helper.
    project_aliases._invalidate_macro_project_identity()
    assert project_aliases.resolve_project_alias_ref("bobby", root) == "bob-cli"


def test_cold_load_errors_propagate_and_cache_nothing(
    root: Path, tick_managed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_args: object, **_kwargs: object) -> list[ProjectRecordWire]:
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(project_aliases, "list_project_records", _fail)
    with pytest.raises(RuntimeError):
        project_aliases.load_project_alias_map(root)
    assert display_cache._PROJECT_ALIAS_MAPS == {}


def test_opting_out_drops_cached_maps(root: Path, tick_managed: None) -> None:
    project_aliases.resolve_project_alias_ref("bob", root)
    assert display_cache._PROJECT_ALIAS_MAPS

    display_cache.set_project_alias_map_tick_managed(False)

    assert display_cache._PROJECT_ALIAS_MAPS == {}
    assert display_cache.tick_managed_project_alias_map(root, lambda _r: {}) is None
