"""A ToolRun is recorded under the identity of the repo that owns its catalog."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.config.tools import tool_project_identity
from sase.core.paths import sase_projects_dir
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.query import ToolRunsCliRequest, handle_runs


AGENT_PROJECT = "gh_host-org__host"


def _git_init(path: Path, *, remote: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.example"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    if remote is not None:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)
    return path


def _with_catalog(root: Path) -> Path:
    (root / "sase").mkdir(exist_ok=True)
    (root / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "probe": {
                        "argv": [sys.executable, "-c", "pass"],
                        "description": "probe",
                        "args": "deny",
                        "fingerprint": {"repos": [], "toolchain": {}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def _agent_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An agent shell: SASE_PROJECT names the agent's own project, not the repo."""

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("SASE_PROJECT", AGENT_PROJECT)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_PROC_ID", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()


def _run(*argv: str) -> int:
    return execute_tool_run(
        ToolRunCliRequest(quiet=False, verbose=False, tail_lines=200, words=argv)
    )


def _newest_run() -> dict[str, object]:
    listed = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    return dict(tool_run_show(listed["run_id"])["run"])


def _register_project(name: str, primary: Path) -> None:
    project_dir = sase_projects_dir() / name
    project_dir.mkdir(parents=True)
    (project_dir / f"{name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n", encoding="utf-8"
    )


def _write_marker(checkout: Path, *, name: str, primary: Path) -> None:
    marker = checkout / ".sase" / "checkout.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": name,
                "project_key": name,
                "workspace_num": 3,
                "primary_workspace_dir": str(primary),
                "registry_path": str(primary / "registry.json"),
            }
        ),
        encoding="utf-8",
    )


def test_identity_ignores_the_agent_project_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    project = tmp_path / "named-project"
    (project / "sase").mkdir(parents=True)
    (project / "sase" / "sase.yml").write_text("tools: {}\n", encoding="utf-8")
    monkeypatch.chdir(project)

    assert tool_project_identity() == "named-project"
    assert tool_project_identity(project) == "named-project"


def test_identity_is_unknown_outside_any_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    (tmp_path / "loose").mkdir()
    monkeypatch.chdir(tmp_path / "loose")

    assert tool_project_identity() == "unknown"


def test_identity_of_an_unregistered_repo_is_stable_across_checkouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    remote = "git@github.com:acme/widgets.git"
    first = _git_init(tmp_path / "one", remote=remote)
    second = _git_init(tmp_path / "widgets_7", remote=remote)
    unhosted_first = _git_init(tmp_path / "gadgets_3")
    unhosted_second = _git_init(tmp_path / "gadgets_12")

    assert tool_project_identity(first) == "gh_acme__widgets"
    assert tool_project_identity(second) == "gh_acme__widgets"
    assert tool_project_identity(unhosted_first) == "gadgets"
    assert tool_project_identity(unhosted_second) == "gadgets"


def test_identity_uses_the_registered_project_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    primary = _git_init(tmp_path / "primary" / "zorg", remote="git@github.com:o/z.git")
    _register_project("zorg", primary)

    assert tool_project_identity(primary) == "zorg"


def test_nested_repo_is_not_claimed_by_the_enclosing_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    primary = tmp_path / "primary" / "zorg"
    _git_init(primary)
    _register_project("zorg", primary)
    checkout = _git_init(tmp_path / "state" / "zorg" / "zorg_5")
    _write_marker(checkout, name="zorg", primary=primary)
    nested_in_checkout = _git_init(checkout / "sase" / "repos" / "linked" / "core")
    nested_in_primary = _git_init(primary / "sase" / "repos" / "linked" / "core")

    assert tool_project_identity(checkout) == "zorg"
    assert tool_project_identity(primary) == "zorg"
    assert tool_project_identity(nested_in_checkout) == "core"
    assert tool_project_identity(nested_in_primary) == "core"


def test_named_run_in_a_second_repo_records_that_repos_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    host = _with_catalog(
        _git_init(tmp_path / "host", remote="git@github.com:h/host.git")
    )
    guest = _with_catalog(
        _git_init(
            host / "sase" / "repos" / "linked" / "guest",
            remote="git@github.com:acme/guest.git",
        )
    )
    monkeypatch.chdir(guest)

    assert _run("probe") == 0

    run = _newest_run()
    assert run["tool_name"] == "probe"
    assert run["project"] == "gh_acme__guest"
    for key in ("fingerprint_before", "fingerprint_after"):
        fingerprint = run[key]
        assert isinstance(fingerprint, dict)
        assert fingerprint["project_identity"] == "gh_acme__guest"
    before = run["fingerprint_before"]
    assert isinstance(before, dict)
    assert before["repos"][0]["identity"] == "gh_acme__guest"
    assert before["repos"][0]["head"]


def test_named_run_keeps_the_catalog_repos_identity_from_a_subdirectory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    repo = _with_catalog(
        _git_init(tmp_path / "solo", remote="git@github.com:a/solo.git")
    )
    (repo / "pkg" / "deep").mkdir(parents=True)
    monkeypatch.chdir(repo / "pkg" / "deep")

    assert _run("probe") == 0

    assert _newest_run()["project"] == "gh_a__solo"


def test_adhoc_run_records_its_cwd_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    repo = _git_init(tmp_path / "adhoc", remote="git@github.com:acme/adhoc.git")
    monkeypatch.chdir(repo)

    assert _run("--", "true") == 0

    run = _newest_run()
    assert run.get("tool_name") is None
    assert run["project"] == "gh_acme__adhoc"
    before = run["fingerprint_before"]
    assert isinstance(before, dict)
    assert before["project_identity"] == "gh_acme__adhoc"
    assert before["repos"][0]["identity"] == "gh_acme__adhoc"


def _listed_projects(
    capsys: pytest.CaptureFixture[str], *, include_all: bool
) -> set[str]:
    capsys.readouterr()
    code = handle_runs(
        ToolRunsCliRequest(
            include_all=include_all,
            agent=None,
            cursor=None,
            json=True,
            limit=50,
            state=None,
            tool=None,
        )
    )
    assert code == 0
    return {run["project"] for run in json.loads(capsys.readouterr().out)["runs"]}


def test_runs_scoping_follows_the_cwd_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _agent_environment(monkeypatch, tmp_path)
    left = _git_init(tmp_path / "left", remote="git@github.com:acme/left.git")
    right = _git_init(tmp_path / "right", remote="git@github.com:acme/right.git")
    monkeypatch.chdir(left)
    assert _run("--", "true") == 0
    monkeypatch.chdir(right)
    assert _run("--", "true") == 0

    assert _listed_projects(capsys, include_all=False) == {"gh_acme__right"}
    monkeypatch.chdir(left)
    assert _listed_projects(capsys, include_all=False) == {"gh_acme__left"}
    assert _listed_projects(capsys, include_all=True) == {
        "gh_acme__left",
        "gh_acme__right",
    }
