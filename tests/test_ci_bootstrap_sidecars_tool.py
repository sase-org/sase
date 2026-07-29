"""Unit tests for ``tools/ci_bootstrap_sidecars``.

These lock the derived ``.sase/sdd-store.json`` shape with tests instead of a
YAML heredoc in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

from collections.abc import Sequence
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
from typing import Any

import pytest

from sase.sdd.store import normalize_sdd_store_record


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "ci_bootstrap_sidecars"
PROJECT_REPO = "sase-org/sase"


def load_script() -> types.ModuleType:
    """Load the suffix-less tool script as a module."""

    loader = importlib.machinery.SourceFileLoader(
        "ci_bootstrap_sidecars", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(name="tool")
def tool_fixture() -> types.ModuleType:
    return load_script()


def _config(*names: str, **extra: Any) -> dict[str, Any]:
    entries: list[dict[str, Any]] = [{"name": name} for name in names]
    for name, fields in extra.items():
        entries.append({"name": name, **fields})
    return {"repos": {"sidecar": entries}}


def test_repo_project_config_drives_the_plan(tool: types.ModuleType) -> None:
    plan = tool.plan_sidecars(
        tool.load_config(ROOT / "sase" / "sase.yml"), PROJECT_REPO
    )

    assert [sidecar.role for sidecar in plan.sidecars] == [
        "plans",
        "research",
        "beads",
    ]
    assert [sidecar.repo for sidecar in plan.sidecars] == [
        "sase-org/sase--plans",
        "sase-org/sase--research",
        "sase-org/sase--beads",
    ]
    assert dict(plan.skipped)["agents"].startswith("hidden sidecar")


def test_hidden_disabled_and_unknown_sidecars_are_skipped(
    tool: types.ModuleType,
) -> None:
    config = _config(
        "plans",
        "research",
        "agents",
        beads={"disabled": True},
        docs={"description": "not a store kind"},
    )

    plan = tool.plan_sidecars(config, PROJECT_REPO)

    assert [sidecar.role for sidecar in plan.sidecars] == ["plans", "research"]
    assert dict(plan.skipped) == {
        "agents": "hidden sidecar; `sase init repo --check` only warns",
        "beads": "disabled in sase.yml",
        "docs": "not representable in the SDD store record",
    }


def test_explicit_repo_overrides_the_derived_slug(tool: types.ModuleType) -> None:
    config = _config("research", plans={"repo": "other-org/elsewhere"})

    plan = tool.plan_sidecars(config, PROJECT_REPO)

    assert {sidecar.role: sidecar.repo for sidecar in plan.sidecars} == {
        "plans": "other-org/elsewhere",
        "research": "sase-org/sase--research",
    }


def test_missing_repos_section_yields_no_sidecars(tool: types.ModuleType) -> None:
    assert tool.plan_sidecars({}, PROJECT_REPO).sidecars == ()


def test_repo_slug_requires_owner_and_name(tool: types.ModuleType) -> None:
    with pytest.raises(tool.BootstrapError):
        tool.sidecar_repo("sase", "plans")


def test_store_record_shape_is_locked(tool: types.ModuleType) -> None:
    plan = tool.plan_sidecars(_config("plans", "beads", "research"), PROJECT_REPO)

    assert tool.build_store_record(plan.sidecars) == {
        "schema_version": 3,
        "storage": "sidecar_repos",
        "host": "github.com",
        "provider": "github",
        "discovery": "found",
        "sidecars": {
            "plans": {
                "repo": "sase-org/sase--plans",
                "remote_url": "git@github.com:sase-org/sase--plans.git",
            },
            "research": {
                "repo": "sase-org/sase--research",
                "remote_url": "git@github.com:sase-org/sase--research.git",
            },
            "beads": {
                "repo": "sase-org/sase--beads",
                "remote_url": "git@github.com:sase-org/sase--beads.git",
            },
        },
    }


def test_store_record_without_beads_stays_on_schema_version_2(
    tool: types.ModuleType,
) -> None:
    plan = tool.plan_sidecars(_config("plans", "research"), PROJECT_REPO)
    record = tool.build_store_record(plan.sidecars)

    assert record["schema_version"] == 2
    assert set(record["sidecars"]) == {"plans", "research"}


def test_store_record_is_accepted_by_sase(tool: types.ModuleType) -> None:
    plan = tool.plan_sidecars(
        tool.load_config(ROOT / "sase" / "sase.yml"), PROJECT_REPO
    )

    normalized = normalize_sdd_store_record(tool.build_store_record(plan.sidecars))

    assert normalized.schema_version == 3
    assert normalized.storage == "sidecar_repos"
    assert normalized.plans is not None
    assert normalized.sidecar_for_kind("research") is not None
    assert normalized.beads is not None
    assert normalized.beads.repo == "sase-org/sase--beads"


def test_store_record_requires_plans_and_research(tool: types.ModuleType) -> None:
    plan = tool.plan_sidecars(_config("plans"), PROJECT_REPO)

    with pytest.raises(tool.BootstrapError, match="research"):
        tool.build_store_record(plan.sidecars)


def test_write_store_record_creates_the_dot_sase_directory(
    tool: types.ModuleType, tmp_path: Path
) -> None:
    plan = tool.plan_sidecars(_config("plans", "research", "beads"), PROJECT_REPO)
    record = tool.build_store_record(plan.sidecars)

    record_path = tool.write_store_record(tmp_path, record)

    assert record_path == tmp_path / ".sase" / "sdd-store.json"
    assert json.loads(record_path.read_text(encoding="utf-8")) == record


class _FakeGit:
    """Records git invocations and replays scripted results."""

    def __init__(self, returncodes: list[int]) -> None:
        self._returncodes = returncodes
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, args: Sequence[str], secret: str
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(args))
        returncode = (
            self._returncodes.pop(0) if self._returncodes and args[0] == "clone" else 0
        )
        stderr = "" if returncode == 0 else f"fatal: could not read from {secret}"
        return subprocess.CompletedProcess(
            args=list(args), returncode=returncode, stdout="", stderr=stderr
        )


def test_clone_retries_then_strips_the_token_from_the_remote(
    tool: types.ModuleType, tmp_path: Path
) -> None:
    sidecar = tool.Sidecar(role="plans", repo="sase-org/sase--plans")
    git = _FakeGit([1, 0])
    slept: list[float] = []

    tool.clone_sidecar(
        sidecar,
        workspace=tmp_path,
        token="s3cret",
        sleeper=slept.append,
        runner=git,
    )

    dest = str(tmp_path / "sase" / "repos" / "plans")
    assert git.calls[0] == (
        "clone",
        "--depth",
        "1",
        "https://x-access-token:s3cret@github.com/sase-org/sase--plans.git",
        dest,
    )
    assert git.calls[-1] == (
        "-C",
        dest,
        "remote",
        "set-url",
        "origin",
        "https://github.com/sase-org/sase--plans.git",
    )
    assert slept == [2.0]


def test_clone_failure_names_the_repository(
    tool: types.ModuleType, tmp_path: Path
) -> None:
    sidecar = tool.Sidecar(role="beads", repo="sase-org/sase--beads")
    git = _FakeGit([1, 1, 1])
    slept: list[float] = []

    with pytest.raises(tool.BootstrapError) as excinfo:
        tool.clone_sidecar(
            sidecar,
            workspace=tmp_path,
            token="s3cret",
            sleeper=slept.append,
            runner=git,
        )

    message = str(excinfo.value)
    assert "sase-org/sase--beads" in message
    assert "SASE_RELEASE_TOKEN" in message
    assert "s3cret" not in message


def test_clone_reuses_an_existing_checkout(
    tool: types.ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "sase" / "repos" / "plans" / ".git").mkdir(parents=True)
    git = _FakeGit([])

    tool.clone_sidecar(
        tool.Sidecar(role="plans", repo="sase-org/sase--plans"),
        workspace=tmp_path,
        token="s3cret",
        runner=git,
    )

    assert git.calls == []


def test_resolve_token_prefers_the_release_token(tool: types.ModuleType) -> None:
    assert tool.resolve_token({"SASE_RELEASE_TOKEN": "a", "GITHUB_TOKEN": "b"}) == "a"
    assert tool.resolve_token({"GITHUB_TOKEN": "b"}) == "b"
    with pytest.raises(tool.BootstrapError):
        tool.resolve_token({"SASE_RELEASE_TOKEN": "  "})


def test_dry_run_prints_the_record_without_cloning(
    tool: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = tool.main(
        [
            "--repo",
            PROJECT_REPO,
            "--workspace",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    printed = capsys.readouterr().out
    record = json.loads(printed[printed.index("{") :])
    assert record == tool.build_store_record(
        tool.plan_sidecars(
            tool.load_config(ROOT / "sase" / "sase.yml"), PROJECT_REPO
        ).sidecars
    )
    assert not (tmp_path / ".sase").exists()


def test_main_reports_a_missing_config(
    tool: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = tool.main(
        ["--config", str(tmp_path / "nope.yml"), "--repo", PROJECT_REPO, "--dry-run"]
    )

    assert exit_code == 1
    assert "missing SASE config" in capsys.readouterr().err
