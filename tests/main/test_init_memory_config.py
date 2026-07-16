from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.init_memory import config
from sase.workspace_provider import marker as marker_module


def test_nested_external_repo_ignores_ancestor_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_workspace = tmp_path / "host"
    external_root = host_workspace / "sase" / "repos" / "external" / "project"
    external_root.mkdir(parents=True)
    host_primary = tmp_path / "host-primary"

    monkeypatch.setattr(
        marker_module,
        "find_marker_from_cwd",
        lambda _cwd: (
            str(host_workspace),
            SimpleNamespace(
                project_name="host",
                primary_workspace_dir=str(host_primary),
            ),
        ),
    )

    def git_stdout(_root: Path, *args: str) -> str | None:
        if args == ("rev-parse", "--show-toplevel"):
            return str(external_root)
        if args == ("config", "--get", "remote.origin.url"):
            return "git@github.com:example/external.git"
        return None

    monkeypatch.setattr(config, "_run_git_stdout", git_stdout)

    assert config.project_memory_name(external_root) == "external"
    assert config.primary_workspace_root_for_memory(external_root) == external_root
