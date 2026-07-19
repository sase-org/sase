from __future__ import annotations

from pathlib import Path

import pytest

from sase.uv_tool.preflight import (
    _is_ephemeral_plugin_path,
    _missing_local_requirements,
    _requirement_local_path,
    ephemeral_install_source_error,
    missing_local_requirements_error,
)
from sase.uv_tool.receipt import Requirement, parse_receipt
from sase.workspace_provider.store import managed_workspace_root


def test_managed_workspace_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-workspaces"
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(root))

    assert managed_workspace_root() == str(root)
    assert _is_ephemeral_plugin_path(root / "owner" / "repo" / "sase_7")


@pytest.mark.parametrize(
    "repo_subdir",
    (("sase", "repos", "external"), ("sase", "repos", "linked")),
)
def test_ephemeral_plugin_path_detects_workspace_repo_clone_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo_subdir: tuple[str, ...],
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "different-root"))
    checkout = tmp_path / "host" / Path(*repo_subdir) / "plugin"

    assert _is_ephemeral_plugin_path(checkout)


def test_ephemeral_plugin_path_allows_durable_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "workspace-store"))

    assert not _is_ephemeral_plugin_path(tmp_path / "projects" / "plugin")


def test_ephemeral_plugin_path_resolves_symlinked_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = tmp_path / "workspace-store"
    source = store / "owner" / "repo" / "sase_7" / "plugin"
    source.mkdir(parents=True)
    alias = tmp_path / "durable-looking-plugin"
    alias.symlink_to(source, target_is_directory=True)
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(store))

    error = ephemeral_install_source_error(
        Requirement(name="sase-demo", editable=str(alias))
    )

    assert error is not None
    assert str(source) in str(error)


def test_requirement_local_path_supports_file_urls(tmp_path: Path) -> None:
    path = tmp_path / "plugin source"
    requirement = Requirement(name="plugin", url=path.as_uri())

    assert _requirement_local_path(requirement) == path
    assert (
        _requirement_local_path(
            Requirement(name="plugin", url="https://example.com/plugin.whl")
        )
        is None
    )


def test_missing_local_requirements_checks_reconstructed_plugins_only(
    tmp_path: Path,
) -> None:
    intact = tmp_path / "intact"
    intact.mkdir()
    missing = tmp_path / "missing"
    receipt = parse_receipt(
        f"""
[tool]
requirements = [
    {{ name = "sase", editable = "{tmp_path / "missing-primary"}" }},
    {{ name = "intact-plugin", directory = "{intact}" }},
    {{ name = "missing-plugin", directory = "{missing}" }},
    {{ name = "remote-plugin", url = "https://example.com/plugin.whl" }},
]
"""
    )

    entries = _missing_local_requirements(receipt.reconstruct())

    assert [(entry.requirement.name, entry.path) for entry in entries] == [
        ("missing-plugin", missing)
    ]
    error = missing_local_requirements_error(receipt.reconstruct())
    assert error is not None
    assert "plugin 'missing-plugin'" in str(error)
    assert str(missing) in str(error)
    assert "sase plugin uninstall missing-plugin" in str(error)
    assert "sase plugin install --git missing-plugin" in str(error)
