"""Tests for tools/setup_required_plugins.

Every ``uv pip install`` / interpreter-verification subprocess is replaced by an
injected ``run_fn`` double, per the ``RunFn`` seam the tool exposes. Nothing here
touches the network or a real venv.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "setup_required_plugins"


def _load_tool() -> ModuleType:
    module_name = "setup_required_plugins_tool"
    loader = SourceFileLoader(module_name, str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(module_name, TOOL_PATH, loader=loader)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The tool's @dataclass decorators need to look themselves up in
    # sys.modules while exec_module runs, matching normal import behavior.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


def _result(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class _RunLog:
    """A fake ``run_fn`` that records calls and replays queued results."""

    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    def __call__(
        self, args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if not self._results:
            raise AssertionError(f"unexpected extra subprocess call: {args}")
        return self._results.pop(0)


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_env_name_mirrors_linked_repo_env_convention() -> None:
    assert TOOL.env_name("sase-github") == "SASE_GITHUB"
    assert TOOL.env_name("sase-research-artifacts") == "SASE_RESEARCH_ARTIFACTS"
    assert TOOL.env_name("weird!!name") == "WEIRD_NAME"


def test_import_module_name_normalizes_separators() -> None:
    assert TOOL.import_module_name("sase-github") == "sase_github"
    assert (
        TOOL.import_module_name("Sase.Research-Artifacts") == "sase_research_artifacts"
    )


def test_linked_checkout_dir_prefers_env_var_override(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout).mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    env = {"SASE_LINKED_REPO_SASE_GITHUB_DIR": str(checkout)}

    found = TOOL.linked_checkout_dir("sase-github", repo_root=tmp_path, env=env)

    assert found == checkout


def test_linked_checkout_dir_falls_back_to_workspace_path(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "sase" / "repos" / "linked" / "sase-research-artifacts"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "pyproject.toml").write_text(
        "[project]\nname='x'\n", encoding="utf-8"
    )

    found = TOOL.linked_checkout_dir(
        "sase-research-artifacts", repo_root=tmp_path, env={}
    )

    assert found == workspace_dir


def test_linked_checkout_dir_returns_none_when_dangling(tmp_path: Path) -> None:
    # A workspace dir that exists but has no pyproject.toml (the dangling repro).
    dangling = tmp_path / "sase" / "repos" / "linked" / "sase-research-artifacts"
    dangling.mkdir(parents=True)

    found = TOOL.linked_checkout_dir(
        "sase-research-artifacts", repo_root=tmp_path, env={}
    )

    assert found is None


def test_linked_repo_names_reads_repos_linked_entries() -> None:
    config = {
        "repos": {
            "linked": [
                {"name": "sase-core"},
                {"name": "sase-github"},
                {"path": "../no-name"},
            ]
        }
    }

    assert TOOL.linked_repo_names(config) == frozenset({"sase-core", "sase-github"})
    assert TOOL.linked_repo_names({}) == frozenset()
    assert TOOL.linked_repo_names(None) == frozenset()


def test_build_plan_splits_name_from_version_specifier() -> None:
    plan = TOOL.build_plan("sase-github>=0.2.5", frozenset({"sase-github"}))

    assert plan.raw == "sase-github>=0.2.5"
    assert plan.name == "sase-github"
    assert plan.module == "sase_github"
    assert plan.is_linked is True


def test_install_requirement_prefers_editable_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "sase-github"
    log = _RunLog(_result(0))
    plan = TOOL.RequirementPlan(
        raw="sase-github",
        name="sase-github",
        module="sase_github",
        checkout=checkout,
        is_linked=True,
    )

    outcome = TOOL.install_requirement(
        plan, "/venv/bin/python", reinstall=False, run_fn=log
    )

    assert outcome.ok
    assert len(log.calls) == 1
    assert "-e" in log.calls[0]
    assert str(checkout) in log.calls[0]


def test_install_requirement_falls_back_to_git_when_pypi_has_no_such_project() -> None:
    log = _RunLog(
        _result(1, stderr="... was not found in the package registry ..."),
        _result(0),
    )
    plan = TOOL.RequirementPlan(
        raw="sase-research-artifacts",
        name="sase-research-artifacts",
        module="sase_research_artifacts",
        checkout=None,
        is_linked=True,
    )

    outcome = TOOL.install_requirement(
        plan, "/venv/bin/python", reinstall=False, run_fn=log
    )

    assert outcome.ok
    assert len(log.calls) == 2
    assert (
        "git+https://github.com/sase-org/sase-research-artifacts@master" in log.calls[1]
    )


def test_install_requirement_does_not_mask_a_real_resolution_conflict() -> None:
    log = _RunLog(_result(1, stderr="no versions of sase-github satisfy >=99"))
    plan = TOOL.RequirementPlan(
        raw="sase-github>=99",
        name="sase-github",
        module="sase_github",
        checkout=None,
        is_linked=True,
    )

    outcome = TOOL.install_requirement(
        plan, "/venv/bin/python", reinstall=False, run_fn=log
    )

    assert not outcome.ok
    assert len(log.calls) == 1  # no git fallback for a real conflict, not "missing"


def test_verify_import_uses_a_fresh_subprocess_not_in_process_import() -> None:
    log = _RunLog(_result(0))

    error = TOOL.verify_import("/venv/bin/python", "sase_github", run_fn=log)

    assert error is None
    assert log.calls == [["/venv/bin/python", "-c", "import sase_github"]]


def test_verify_import_reports_the_failure_tail() -> None:
    log = _RunLog(_result(1, stderr="Traceback...\nModuleNotFoundError: no module\n"))

    error = TOOL.verify_import(
        "/venv/bin/python", "sase_research_artifacts", run_fn=log
    )

    assert error is not None
    assert "ModuleNotFoundError" in error


def test_ensure_requirement_repairs_a_dangling_install_on_verify_failure() -> None:
    # install (no-op success) -> verify fails (dangling) -> reinstall -> verify OK.
    log = _RunLog(
        _result(0),  # first install_requirement (uv's no-op fast path)
        _result(1, stderr="ModuleNotFoundError"),  # first verify
        _result(0),  # repair install_requirement (--reinstall-package)
        _result(0),  # second verify
    )
    plan = TOOL.RequirementPlan(
        raw="sase-research-artifacts",
        name="sase-research-artifacts",
        module="sase_research_artifacts",
        checkout=None,
        is_linked=True,
    )

    error = TOOL.ensure_requirement(plan, "/venv/bin/python", run_fn=log)

    assert error is None
    assert len(log.calls) == 4
    assert "--reinstall-package" in log.calls[2]


def test_ensure_requirement_fails_when_still_broken_after_reinstall() -> None:
    log = _RunLog(
        _result(0),
        _result(1, stderr="ModuleNotFoundError"),
        _result(0),
        _result(1, stderr="ModuleNotFoundError"),
    )
    plan = TOOL.RequirementPlan(
        raw="sase-research-artifacts",
        name="sase-research-artifacts",
        module="sase_research_artifacts",
        checkout=None,
        is_linked=True,
    )

    error = TOOL.ensure_requirement(plan, "/venv/bin/python", run_fn=log)

    assert error is not None
    assert "sase-research-artifacts" in error
    assert "still fails" in error


def test_failure_message_suggests_repo_open_for_a_linked_plugin() -> None:
    plan = TOOL.RequirementPlan(
        raw="sase-research-artifacts",
        name="sase-research-artifacts",
        module="sase_research_artifacts",
        checkout=None,
        is_linked=True,
    )

    message = TOOL.failure_message(
        plan, [TOOL.InstallOutcome(ok=False, source="PyPI", detail="404")]
    )

    assert "sase repo open sase-research-artifacts" in message


def test_failure_message_suggests_uv_install_for_an_unlinked_plugin() -> None:
    plan = TOOL.RequirementPlan(
        raw="some-plugin>=1",
        name="some-plugin",
        module="some_plugin",
        checkout=None,
        is_linked=False,
    )

    message = TOOL.failure_message(
        plan, [TOOL.InstallOutcome(ok=False, source="PyPI", detail="404")]
    )

    assert "uv pip install" in message
    assert "sase repo open" not in message


def test_main_returns_zero_without_installing_when_nothing_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.plugins.required as required_module

    monkeypatch.setattr(
        required_module,
        "load_project_required_plugins_config",
        lambda _root: ({}, None, None),
    )

    assert TOOL.main() == 0
