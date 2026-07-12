"""Tests for diff cache keys and read-only workspace resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from tests.ace.tui.widgets.file_panel._diff_cache_helpers import (
    _FakeProvider,
    _make_running_agent,
    _setup_workspace,
    _write_project_file,
)


def test_compute_diff_cache_key_includes_provider_name(tmp_path: Path) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(workspace)
    assert key[2] == "_FakeProvider"
    assert key[3] is not None  # git index signature present
    assert isinstance(key[4], int)  # TTL bucket always present


def test_compute_diff_cache_key_ttl_bucket_present_without_git_index(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "myproj_1"
    workspace.mkdir()
    # No .git directory → fingerprint is None; TTL bucket still present.
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[3] is None
    assert isinstance(key[4], int)


def test_compute_diff_cache_key_returns_none_without_provider(
    tmp_path: Path,
) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))

    from sase.vcs_provider import VCSProviderNotFoundError

    def raise_not_found(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        raise VCSProviderNotFoundError("none")

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", side_effect=raise_not_found):
            assert diff_mod._compute_diff_cache_key(agent) is None


def test_compute_diff_cache_key_derives_numbered_workspace_adjacent_policy(
    tmp_path: Path,
) -> None:
    """Legacy ``adjacent`` policy still resolves to ``{primary}_{N}``."""
    diff_mod._workspace_store_cache.clear()
    primary_workspace = _setup_workspace(tmp_path, "primary")
    derived_workspace = _setup_workspace(tmp_path, "primary_3")
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(derived_workspace)


def test_get_agent_diff_returns_none_without_read_only_workspace_metadata(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    project_file = tmp_path / "projects" / "myproj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: my-feature\n", encoding="utf-8")
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
            assert diff_mod.get_agent_diff(agent) is None

    mock_get_provider.assert_not_called()


def test_compute_diff_cache_key_returns_none_when_explicit_workspace_is_missing(
    tmp_path: Path,
) -> None:
    primary_workspace = _setup_workspace(tmp_path, "primary")
    _setup_workspace(tmp_path, "primary_3")
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(
        workspace_num=3,
        workspace_dir=str(tmp_path / "missing_3"),
        project_file=str(project_file),
    )

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
            assert diff_mod._compute_diff_cache_key(agent) is None

    mock_get_provider.assert_not_called()


def _xdg_state_config() -> dict[str, object]:
    return {"workspace": {"root": "xdg-state", "project_key": "k"}}


def _make_xdg_managed_dir(tmp_path: Path) -> Path:
    """Create a managed ``xdg-state`` checkout (with ``.git/index``)."""
    managed = tmp_path / "state" / "sase" / "workspaces" / "k" / "primary_3"
    (managed / ".git").mkdir(parents=True)
    (managed / ".git" / "index").write_bytes(b"\x00" * 16)
    return managed


def test_resolve_managed_workspace_dir_none_is_primary() -> None:
    # ``workspace_num is None`` short-circuits to the primary dir without
    # constructing a store or loading config.
    assert (
        diff_mod._resolve_managed_workspace_dir("/proj/primary", None)
        == "/proj/primary"
    )


def test_resolve_managed_workspace_dir_zero_is_primary() -> None:
    diff_mod._workspace_store_cache.clear()
    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 0)
    assert resolved == "/proj/primary"


def test_resolve_managed_workspace_dir_adjacent_policy() -> None:
    diff_mod._workspace_store_cache.clear()
    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 3)
    assert resolved is not None
    assert resolved.rstrip("/") == "/proj/primary_3"


def test_resolve_managed_workspace_dir_xdg_state_is_not_adjacent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._workspace_store_cache.clear()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 3)

    assert resolved is not None
    expected = tmp_path / "state" / "sase" / "workspaces" / "k" / "primary_3"
    assert resolved.rstrip("/") == str(expected)
    # The whole point of the fix: the managed path is NOT the adjacent one.
    assert resolved.rstrip("/") != "/proj/primary_3"


def test_resolve_managed_workspace_dir_invalid_config_returns_none() -> None:
    diff_mod._workspace_store_cache.clear()
    # A non-absolute, non-policy ``workspace.root`` makes WorkspaceStore raise;
    # the resolver degrades to None instead of propagating.
    with patch.object(
        diff_mod,
        "load_merged_config",
        return_value={"workspace": {"root": "not-a-policy"}},
    ):
        assert diff_mod._resolve_managed_workspace_dir("/proj/primary", 3) is None


def test_get_workspace_store_constructed_once_per_primary() -> None:
    diff_mod._workspace_store_cache.clear()
    calls = {"n": 0}
    real_store_cls = diff_mod.WorkspaceStore

    def counting(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return real_store_cls(*args, **kwargs)

    with patch.object(diff_mod, "WorkspaceStore", side_effect=counting):
        with patch.object(
            diff_mod,
            "load_merged_config",
            return_value={"workspace": {"root": "adjacent"}},
        ):
            first = diff_mod._get_workspace_store("/proj/primary")
            second = diff_mod._get_workspace_store("/proj/primary")

    assert first is second
    assert calls["n"] == 1


def test_compute_diff_cache_key_xdg_state_prefers_managed_over_stale_adjacent(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: a stale ``{primary}_{N}`` leftover must not win under xdg-state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._diff_cache.clear()
    diff_mod._workspace_store_cache.clear()

    primary_workspace = _setup_workspace(tmp_path, "primary")
    stale_adjacent = _setup_workspace(tmp_path, "primary_3")
    managed = _make_xdg_managed_dir(tmp_path)
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(managed)
    assert key[1] != str(stale_adjacent)


def test_get_agent_diff_runs_in_managed_workspace_not_stale(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: the live diff is taken from the managed checkout, not the
    stale adjacent leftover that the old heuristic would have picked."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._diff_cache.clear()
    diff_mod._workspace_store_cache.clear()

    primary_workspace = _setup_workspace(tmp_path, "primary")
    _setup_workspace(tmp_path, "primary_3")  # stale adjacent leftover
    managed = _make_xdg_managed_dir(tmp_path)
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(
            diff_mod, "load_merged_config", return_value=_xdg_state_config()
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                result = diff_mod.get_agent_diff(agent)

    assert result == "diff for call 1"
    assert provider.cwd_calls == [str(managed)]


def test_resolve_managed_workspace_dir_one_is_primary(
    tmp_path: Path, monkeypatch
) -> None:
    # Legacy metadata uses 0 and 1 interchangeably for the primary checkout.
    # Under the default xdg-state policy resolve(1) would return a managed
    # clone path, so the resolver must normalize 1 -> 0 exactly like the
    # runner-side resolvers do.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._workspace_store_cache.clear()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 1)

    assert resolved is not None
    assert resolved.rstrip("/") == "/proj/primary"
