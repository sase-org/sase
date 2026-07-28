from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sase import project_aliases, project_display_names
from sase.xprompt import loader_sources
from sase.xprompt import project_identity
from sase.xprompt.project_identity import canonical_xprompt_project
from sase.xprompt.project_identity import known_project_namespaces
from tests.main.project_handler_helpers import (
    _disk_project_records,
    _write_project,
    projects_root,
)

__all__ = ["projects_root"]


@pytest.fixture(autouse=True)
def _clear_identity_cache() -> Iterator[None]:
    project_identity._identity_registry.cache_clear()
    project_identity._canonical_xprompt_project.cache_clear()
    yield
    project_identity._identity_registry.cache_clear()
    project_identity._canonical_xprompt_project.cache_clear()


@pytest.fixture
def _lifecycle_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_aliases, "list_project_records", _disk_project_records)
    monkeypatch.setattr(
        project_display_names, "list_project_records", _disk_project_records
    )
    monkeypatch.setattr(loader_sources, "list_project_records", _disk_project_records)


def _write_identity_project(
    projects_root: Path,
    key: str,
    workspace: Path,
    *,
    display_name: str | None = None,
    aliases: tuple[str, ...] = (),
    state: str = "enabled",
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    lines = [
        f"WORKSPACE_DIR: {workspace}",
        f"PROJECT_STATE: {state}",
    ]
    if display_name is not None:
        lines.append(f"PROJECT_NAME: {display_name}")
    if aliases:
        lines.append(f"PROJECT_ALIASES: {', '.join(aliases)}")
    _write_project(projects_root, key, "\n".join(lines) + "\n")


def test_canonical_xprompt_project_normalizes_known_spellings(
    projects_root: Path,
    _lifecycle_reader: None,
    tmp_path: Path,
) -> None:
    _write_identity_project(
        projects_root,
        "gh_acme__widgets",
        tmp_path / "widgets-ws",
        display_name="widgets",
        aliases=("docs", "w"),
    )
    _write_identity_project(projects_root, "plain", tmp_path / "plain-ws")

    assert canonical_xprompt_project("gh_acme__widgets") == "widgets"
    assert canonical_xprompt_project("widgets") == "widgets"
    assert canonical_xprompt_project("docs") == "widgets"
    assert canonical_xprompt_project("w") == "widgets"
    assert canonical_xprompt_project("plain") == "plain"


def test_canonical_xprompt_project_preserves_empty_and_unknown_refs(
    projects_root: Path,
    _lifecycle_reader: None,
    tmp_path: Path,
) -> None:
    _write_identity_project(
        projects_root,
        "gh_acme__widgets",
        tmp_path / "widgets-ws",
        display_name="widgets",
    )

    assert canonical_xprompt_project(None) is None
    assert canonical_xprompt_project("") is None
    assert canonical_xprompt_project("   ") is None
    assert canonical_xprompt_project("bd") == "bd"
    assert canonical_xprompt_project("research") == "research"


def test_canonical_xprompt_project_degrades_to_input_on_registry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_alias_map() -> dict[str, str]:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(project_identity, "load_project_alias_map", fail_alias_map)

    assert canonical_xprompt_project("widgets") == "widgets"


def test_known_project_namespaces_uses_user_facing_names(
    projects_root: Path,
    _lifecycle_reader: None,
    tmp_path: Path,
) -> None:
    widgets_ws = tmp_path / "widgets-ws"
    plain_ws = tmp_path / "plain-ws"
    disabled_ws = tmp_path / "disabled-ws"
    home_ws = tmp_path / "home-ws"
    _write_identity_project(
        projects_root,
        "gh_acme__widgets",
        widgets_ws,
        display_name="widgets",
        aliases=("docs",),
    )
    _write_identity_project(projects_root, "plain", plain_ws)
    _write_identity_project(
        projects_root,
        "inactive",
        disabled_ws,
        display_name="inactive_display",
        state="disabled",
    )
    _write_identity_project(projects_root, "home", home_ws, display_name="home")

    assert known_project_namespaces() == {
        "widgets": widgets_ws,
        "plain": plain_ws,
    }


def test_known_project_namespaces_degrades_to_directory_keys_on_registry_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(
        project_identity,
        "get_known_project_workspaces",
        lambda: {"gh_acme__widgets": workspace},
    )
    monkeypatch.setattr(project_identity, "load_project_alias_map", lambda: {})
    monkeypatch.setattr(
        project_identity,
        "load_project_display_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("registry unavailable")),
    )

    assert known_project_namespaces() == {"gh_acme__widgets": workspace}
