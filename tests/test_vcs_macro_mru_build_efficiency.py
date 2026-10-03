"""Per-build efficiency tests for sase.history.vcs_macro_mru.

One launchable-MRU build lists project records once (or a small constant
independent of entry count) and detects each project's provider once per
distinct project, using per-call state only.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.history import vcs_macro_mru as mru
from sase.history.vcs_macro_mru import load_launchable_vcs_macro_mru_pairs
from tests._vcs_macro_mru_helpers import (
    patch_discovered_workflow_type_as_git,
    patched_mru_file,
    write_named_project,
    write_project,
)
from tests.conftest import redirect_sase_home

_LIST_SEAMS = (
    "sase.core.project_lifecycle_facade.list_project_records",
    "sase.project_aliases.list_project_records",
    "sase.project_display_names.list_project_records",
    "sase.ace.tui.modals.project_discovery.list_project_records",
    "sase.macro.loader_sources.list_project_records",
)


def _count_list_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Count every lifecycle-inventory read behind any import seam."""
    calls: list[str] = []
    for seam in _LIST_SEAMS:
        module_name, attr = seam.rsplit(".", 1)
        try:
            module = __import__(module_name, fromlist=[attr])
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            continue

        def _make_wrapper(
            seam_name: str, original_fn: Callable[..., object]
        ) -> Callable[..., object]:
            def _wrapper(*args: object, **kwargs: object) -> object:
                calls.append(seam_name)
                return original_fn(*args, **kwargs)

            return _wrapper

        monkeypatch.setattr(f"{module_name}.{attr}", _make_wrapper(seam, original))
    return calls


def _count_detect_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[str]]:
    """Count provider detections behind each mockable seam."""
    calls: dict[str, list[str]] = {"discovery": [], "provider": []}
    import sase.ace.tui.modals.project_discovery as discovery
    import sase.workspace_provider as provider

    original_discovery = discovery.detect_workflow_type
    original_provider = provider.detect_workflow_type

    def _discovery_wrapper(project_file: str) -> str:
        calls["discovery"].append(project_file)
        return original_discovery(project_file)

    def _provider_wrapper(project_file: str) -> str:
        calls["provider"].append(project_file)
        return original_provider(project_file)

    monkeypatch.setattr(discovery, "detect_workflow_type", _discovery_wrapper)
    monkeypatch.setattr(provider, "detect_workflow_type", _provider_wrapper)
    return calls


def _write_projects(projects_dir: Path, workspace_parent: Path, count: int) -> None:
    for i in range(count):
        workspace = workspace_parent / f"ws-{i}"
        workspace.mkdir(exist_ok=True)
        write_named_project(projects_dir, f"dir_{i}", f"proj{i}", workspace)


def test_build_lists_project_records_once_for_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit-root build reads the inventory once, whatever the entries."""
    projects_dir = tmp_path / "projects"
    _write_projects(projects_dir, tmp_path, 6)
    write_project(projects_dir, "stale", tmp_path / "missing-workspace")
    entries = [
        "#git:dir_0",
        "#git:proj1",
        "#git:dir_2",
        "#git:proj3",
        "#git:stale",
        "#git:gone",
        "#git:dir_4",
        "#git:proj5",
    ]
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": entries}))
    patch_discovered_workflow_type_as_git(monkeypatch)

    list_calls = _count_list_calls(monkeypatch)
    with patched_mru_file(fake):
        first = load_launchable_vcs_macro_mru_pairs(projects_dir, prune=False)
        first_list_calls = len(list_calls)
        doubled = load_launchable_vcs_macro_mru_pairs(projects_dir, prune=False)

    assert first == doubled
    assert len(first) == 7
    assert first_list_calls == 1
    assert len(list_calls) == 2


def test_build_detects_each_project_once_for_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated refs to one project detect its provider a single time."""
    projects_dir = tmp_path / "projects"
    _write_projects(projects_dir, tmp_path, 3)
    entries = [
        "#git:dir_0",
        "#git:proj0",
        "#git:dir_0",
        "#git:dir_1",
        "#git:proj1",
        "#git:dir_2",
    ]
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": entries}))
    patch_discovered_workflow_type_as_git(monkeypatch)

    detect_calls = _count_detect_calls(monkeypatch)
    with patched_mru_file(fake):
        pairs = load_launchable_vcs_macro_mru_pairs(projects_dir, prune=False)

    assert [canonical for canonical, _ in pairs] == [
        "#git:dir_0",
        "#git:dir_1",
        "#git:dir_2",
    ]
    assert len(detect_calls["discovery"]) == 3
    assert len(set(detect_calls["discovery"])) == 3
    assert detect_calls["provider"] == []


def test_build_bounds_reads_and_detections_for_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default-root build stays at a small constant independent of entries."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    projects_dir = sase_home / "projects"
    _write_projects(projects_dir, tmp_path, 4)
    mru_file = sase_home / "vcs_xprompt_mru.json"
    entries = [
        "#git:dir_0",
        "#git:proj1",
        "#git:dir_2",
        "#git:proj3",
        "#git:gone",
    ]
    mru_file.write_text(json.dumps({"entries": entries}))

    workspaces = {f"dir_{i}": tmp_path / f"ws-{i}" for i in range(4)}
    monkeypatch.setattr(
        "sase.macro.loader.get_known_project_workspaces",
        lambda *a, **k: dict(workspaces),
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    patch_discovered_workflow_type_as_git(monkeypatch)
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "git",
    )

    list_calls = _count_list_calls(monkeypatch)
    detect_calls = _count_detect_calls(monkeypatch)
    # Re-wrap after the constant mocks above so the counters see every call.
    result = load_launchable_vcs_macro_mru_pairs(None, prune=False)

    # The unresolvable ``#git:gone`` ref is pruned on the default root.
    assert [canonical for canonical, _ in result] == entries[:-1]
    assert len(list_calls) <= 3
    for seam_calls in detect_calls.values():
        assert len(seam_calls) == len(set(seam_calls))


def test_build_state_is_per_call_not_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two builds do not share memo state through the module."""
    projects_dir = tmp_path / "projects"
    _write_projects(projects_dir, tmp_path, 2)
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#git:dir_0", "#git:dir_1"]}))
    patch_discovered_workflow_type_as_git(monkeypatch)

    with patched_mru_file(fake):
        first = mru._mru_build_state(projects_dir)
        second = mru._mru_build_state(projects_dir)

    assert first is not second
    assert first.detect_cache is not second.detect_cache
    assert first.records == second.records
    assert [r.project_name for r in first.records or []] == ["dir_0", "dir_1"]
