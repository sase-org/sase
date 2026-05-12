"""Unit tests for ``tools/last_workflow_set_status`` (Phase 1 surface).

The script has no ``.py`` suffix, so the test module loads it through
``importlib.machinery.SourceFileLoader`` and exposes it as a fixture.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "last_workflow_set_status"


def _load_script() -> types.ModuleType:
    """Load the suffix-less tool script as a module."""
    loader = importlib.machinery.SourceFileLoader(
        "last_workflow_set_status", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return _load_script()


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults(script: types.ModuleType) -> None:
    config = script.parse_args([])
    assert config.repo is None
    assert config.branch is None
    assert config.limit == script.DEFAULT_LIMIT
    assert config.tail == script.DEFAULT_TAIL
    assert config.events == script.DEFAULT_EVENTS
    assert config.require == ()
    assert config.json_output is False


def test_parse_args_overrides(script: types.ModuleType) -> None:
    config = script.parse_args(
        [
            "--repo",
            "sase-org/sase",
            "--branch",
            "master",
            "--limit",
            "100",
            "--tail",
            "10",
            "--event",
            "push",
            "--event",
            "merge_group",
            "--require",
            "CI, Deploy Docs ,",
            "--json",
        ]
    )
    assert config.repo == "sase-org/sase"
    assert config.branch == "master"
    assert config.limit == 100
    assert config.tail == 10
    assert config.events == ("push", "merge_group")
    assert config.require == ("CI", "Deploy Docs")
    assert config.json_output is True


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "0"],
        ["--limit", "-3"],
        ["--tail", "0"],
        ["--repo", "not-a-slash-form"],
    ],
)
def test_parse_args_rejects_bad_values(
    script: types.ModuleType, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as info:
        script.parse_args(argv)
    assert info.value.code == 2


# ---------------------------------------------------------------------------
# GhClient
# ---------------------------------------------------------------------------


def _fake_runner(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    capture: list[list[str]] | None = None,
):
    def _run(argv):
        if capture is not None:
            capture.append(list(argv))
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return _run


def test_gh_client_default_branch(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="sase-org/sase",
        executable=sys.executable,  # any existing executable resolves on PATH
        runner=_fake_runner(stdout='"master"\n', capture=capture),
    )
    assert client.default_branch() == "master"

    argv = capture[0]
    assert argv[0] == sys.executable
    assert argv[1:] == [
        "repo",
        "view",
        "--json",
        "defaultBranchRef",
        "--jq",
        ".defaultBranchRef.name",
        "--repo",
        "sase-org/sase",
    ]


def test_gh_client_propagates_repo(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=_fake_runner(stdout="[]", capture=capture),
    )
    client.run_json(["run", "list"])
    assert capture[0][-2:] == ["--repo", "o/r"]


def test_gh_client_omits_repo_when_unset(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo=None,
        executable=sys.executable,
        runner=_fake_runner(stdout="[]", capture=capture),
    )
    client.run_json(["run", "list"])
    assert "--repo" not in capture[0]


def test_gh_client_missing_executable(script: types.ModuleType) -> None:
    client = script.GhClient(executable="definitely-not-on-path-xyz")
    with pytest.raises(script.GhMissingError) as info:
        client.run_text(["repo", "view"])
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_nonzero_exit(script: types.ModuleType) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(returncode=1, stderr="auth required"),
    )
    with pytest.raises(script.GhCommandError) as info:
        client.run_text(["repo", "view"])
    assert info.value.returncode == 1
    assert "auth required" in str(info.value)
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_invalid_json(script: types.ModuleType) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(stdout="not-json"),
    )
    with pytest.raises(script.GhJsonError) as info:
        client.run_json(["repo", "view"])
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_empty_default_branch_is_error(
    script: types.ModuleType,
) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(stdout='""'),
    )
    with pytest.raises(script.GhJsonError):
        client.default_branch()


# ---------------------------------------------------------------------------
# resolve_branch + main flow
# ---------------------------------------------------------------------------


def test_resolve_branch_prefers_explicit(script: types.ModuleType) -> None:
    config = script.parse_args(["--branch", "topic"])

    class _Boom:
        def default_branch(self) -> str:  # pragma: no cover - must not be called
            raise AssertionError("default_branch should not be queried")

    assert script.resolve_branch(config, _Boom()) == "topic"


def test_resolve_branch_falls_back_to_default(script: types.ModuleType) -> None:
    config = script.parse_args([])

    class _Stub:
        def default_branch(self) -> str:
            return "main"

    assert script.resolve_branch(config, _Stub()) == "main"


def test_main_returns_no_complete_set_exit_code(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Phase 1 always exits with EXIT_NO_COMPLETE_SET after the placeholder."""

    class _Stub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def default_branch(self) -> str:
            return "master"

    monkeypatch.setattr(script, "GhClient", _Stub)
    code = script.main(["--repo", "sase-org/sase"])
    assert code == script.EXIT_NO_COMPLETE_SET
    out = capsys.readouterr().out
    assert "Phase 1 skeleton" in out
    assert "branch: master" in out


def test_main_json_output(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Stub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def default_branch(self) -> str:
            return "main"

    monkeypatch.setattr(script, "GhClient", _Stub)
    code = script.main(["--json"])
    assert code == script.EXIT_NO_COMPLETE_SET
    out = capsys.readouterr().out
    import json as _json

    payload = _json.loads(out)
    assert payload["branch"] == "main"
    assert payload["events"] == ["push"]


def test_main_surfaces_gh_errors(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Stub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def default_branch(self) -> str:
            raise script.GhMissingError(
                "gh not installed", exit_code=script.EXIT_CONFIG_ERROR
            )

    monkeypatch.setattr(script, "GhClient", _Stub)
    code = script.main([])
    assert code == script.EXIT_CONFIG_ERROR
    err = capsys.readouterr().err
    assert "gh not installed" in err
