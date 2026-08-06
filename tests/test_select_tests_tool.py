"""Tests for the `tools/select_tests` CLI wrapper.

The CLI is driven against the same synthetic repository the engine's unit tests
use, with its ``REPO_ROOT`` redirected, so nothing here depends on the real
repository's import graph.
"""

from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection import FULL_SUITE, MANIFEST_FILENAME, SELECTION_DIRECTORY
from tests._test_selection_contexts import CONTEXTS_DIR_ENV
from tests._test_selection_fixtures import (
    RING_SIZE,
    _touch,
    build_fixture_repo,
    install_fresh_baseline,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed synthetic repository with a known import shape."""
    return build_fixture_repo(tmp_path)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "select_tests"


def _load_tool(repo_root: Path) -> ModuleType:
    loader = SourceFileLoader("select_tests_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "select_tests_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = repo_root
    return module


@pytest.fixture
def tool(repo: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # A fresh baseline, so these assertions measure the closure at the depth
    # they ask for rather than the extra hop `no-baseline-depth-boost` buys.
    store = install_fresh_baseline(repo)
    monkeypatch.setenv(CONTEXTS_DIR_ENV, str(store.parent / "contexts"))
    monkeypatch.setenv("SASE_TEST_SELECTION_MAX_RATIO", "1.0")
    monkeypatch.delenv("SASE_TEST_SELECTION_DEPTH", raising=False)
    monkeypatch.delenv("SASE_CHECK_BASE", raising=False)
    return _load_tool(repo)


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_paths_format_prints_one_path_per_line(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/d.py")

    assert tool.main(["--base", "HEAD"]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["tests/test_d.py"]
    assert "selected 1 of " in captured.err


def test_paths_format_prints_the_full_suite_sentinel(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "Justfile")

    assert tool.main(["--base", "HEAD"]) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == FULL_SUITE
    assert "escalated to the full suite" in captured.err


def test_json_format_prints_the_manifest(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    assert tool.main(["--base", "HEAD", "--format", "json"]) == 0

    manifest = json.loads(capsys.readouterr().out)
    assert manifest["schema"] == 3
    assert manifest["changed_files"] == ["src/pkg/a.py"]
    assert manifest["selected_count"] == len(manifest["selected"])


def test_manifest_is_written_to_the_default_location(
    tool: ModuleType, repo: Path
) -> None:
    _touch(repo, "src/pkg/a.py")

    tool.main(["--base", "HEAD"])

    written = json.loads(
        (repo / SELECTION_DIRECTORY / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert written["changed_files"] == ["src/pkg/a.py"]


def test_manifest_destination_is_overridable(
    tool: ModuleType, repo: Path, tmp_path: Path
) -> None:
    _touch(repo, "src/pkg/a.py")
    destination = tmp_path / "elsewhere" / "manifest.json"

    tool.main(["--base", "HEAD", "--manifest", str(destination)])

    assert json.loads(destination.read_text(encoding="utf-8"))["schema"] == 3


def test_depth_and_max_ratio_flags_override_the_environment(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    tool.main(["--base", "HEAD", "--depth", "0", "--max-ratio", "1.0"])

    assert capsys.readouterr().out.splitlines() == ["tests/test_a.py"]


def test_ratio_flag_can_force_escalation(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    tool.main(["--base", "HEAD", "--max-ratio", "0.01"])

    assert capsys.readouterr().out.strip() == FULL_SUITE


def test_explain_names_the_seed_and_hop(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    tool.main(["--base", "HEAD", "--explain"])

    stderr = capsys.readouterr().err
    assert "rules fired:" in stderr
    assert "tests/test_c.py  <- seed pkg.a at hop 3" in stderr


def test_explain_reports_escalation_without_a_file_list(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "pyproject.toml")

    tool.main(["--base", "HEAD", "--explain"])

    stderr = capsys.readouterr().err
    assert "packaging-config" in stderr
    assert "escalates to the full suite" in stderr


def test_no_cache_rebuilds_the_graph(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool.main(["--base", "HEAD", "--format", "json"])
    capsys.readouterr()

    tool.main(["--base", "HEAD", "--format", "json", "--no-cache"])

    assert json.loads(capsys.readouterr().out)["graph"]["cache_hit"] is False


def test_warm_run_reports_a_cache_hit(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool.main(["--base", "HEAD", "--format", "json"])
    capsys.readouterr()

    tool.main(["--base", "HEAD", "--format", "json"])

    assert json.loads(capsys.readouterr().out)["graph"]["cache_hit"] is True


def test_invalid_environment_is_a_usage_error(
    tool: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_TEST_SELECTION_DEPTH", "banana")

    assert tool.main(["--base", "HEAD"]) == 2


def test_ring_shape_is_not_swallowed_by_the_cli(
    tool: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _touch(repo, "src/pkg/ring0.py")

    tool.main(["--base", "HEAD"])

    selected = capsys.readouterr().out.split()
    assert len([path for path in selected if "test_ring" in path]) < RING_SIZE
