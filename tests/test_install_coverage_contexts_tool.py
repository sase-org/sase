"""Tests for the `tools/install_coverage_contexts` local baseline producer.

The tool is driven against the synthetic repository the selection engine's
tests use, with its ``REPO_ROOT`` redirected and the contexts cache pointed at a
temporary directory, so nothing here touches the host's real baseline cache.
"""

from __future__ import annotations

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest
from coverage import CoverageData

from tests._test_selection_contexts import (
    CONTEXTS_DIR_ENV,
    baseline_path,
    breadth_path,
    cached_baselines,
    resolve_baseline,
)
from tests._test_selection_fixtures import RING_SIZE, _write, build_fixture_repo


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "install_coverage_contexts"
MEASURED = "src/pkg/a.py"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return build_fixture_repo(tmp_path)


@pytest.fixture
def contexts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "contexts"
    directory.mkdir()
    monkeypatch.setenv(CONTEXTS_DIR_ENV, str(directory))
    return directory


def _load_tool(repo_root: Path) -> ModuleType:
    loader = SourceFileLoader("install_coverage_contexts_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "install_coverage_contexts_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = repo_root
    return module


@pytest.fixture
def tool(repo: Path) -> ModuleType:
    return _load_tool(repo)


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write_database(
    path: Path, *, test_files: int, measured_files: int = 1, dense: bool = True
) -> Path:
    """A coverage database whose contexts name ``test_files`` ring tests.

    ``dense`` is what separates the two ways a *complete* run can turn out. A
    ctrace-cored run credits every test that reached a file, so each measured
    file carries one ``(file, test)`` pair per test; a sysmon-cored one credits
    only the first, leaving the same tests and the same files with a fraction
    of the attribution.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    measured = [MEASURED] + [
        f"src/pkg/ring{index}.py" for index in range(measured_files - 1)
    ]
    data = CoverageData(basename=str(path))
    for index in range(test_files):
        data.set_context(f"tests/test_ring{index}.py::test_it|run")
        touched = measured if dense else [measured[index % len(measured)]]
        data.add_lines({name: [1] for name in touched})
    data.write()
    return path


def _full_database(repo: Path) -> Path:
    """A database that looks like a whole-suite `cov-contexts` run."""
    return _write_database(repo / ".coverage", test_files=RING_SIZE)


def test_a_full_local_run_becomes_a_resolvable_baseline(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """The point of the tool: a local run supplies what only CI used to."""
    _full_database(repo)

    assert tool.main([]) == 0

    head = _head(repo)
    assert baseline_path(contexts_dir, head).is_file()
    baseline = resolve_baseline(repo, contexts_dir)
    assert baseline is not None
    assert baseline.sha == head


def test_the_installed_baseline_carries_the_recorded_contexts(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    _full_database(repo)
    assert tool.main([]) == 0

    installed = CoverageData(basename=str(baseline_path(contexts_dir, _head(repo))))
    installed.read()

    assert MEASURED in installed.measured_files()
    assert "tests/test_ring0.py::test_it|run" in installed.measured_contexts()


def test_a_missing_database_is_an_error_not_an_empty_baseline(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    assert tool.main([]) == 1
    assert cached_baselines(contexts_dir) == []


def test_a_database_without_contexts_is_refused(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """`just test-cov` writes `.coverage` too, and it is not a baseline.

    Caching it would silence `context-baseline-missing` while contributing no
    tests at all — strictly worse than having no baseline.
    """
    data = CoverageData(basename=str(repo / ".coverage"))
    data.add_lines({MEASURED: [1]})
    data.write()

    assert tool.main([]) == 1
    assert cached_baselines(contexts_dir) == []


def test_a_thinly_attributed_run_is_refused_but_can_be_forced(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """The whole suite, the same files, an order of magnitude less ground truth.

    Neither existing guard sees this one: the run is complete and the tree is
    clean. Only the recorded attribution density tells it apart from the cached
    baseline it would otherwise sit beside.
    """
    _write_database(
        baseline_path(contexts_dir, "0" * 40), test_files=RING_SIZE, measured_files=6
    )
    _write_database(
        repo / ".coverage", test_files=RING_SIZE, measured_files=6, dense=False
    )

    assert tool.main([]) == 1
    assert [entry.sha for entry in cached_baselines(contexts_dir)] == ["0" * 40]

    assert tool.main(["--allow-thin"]) == 0
    assert baseline_path(contexts_dir, _head(repo)).is_file()


def test_a_first_baseline_is_never_called_thin(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """With nothing cached there is no reference, and some ground truth beats none."""
    _write_database(
        repo / ".coverage", test_files=RING_SIZE, measured_files=6, dense=False
    )

    assert tool.main([]) == 0
    assert baseline_path(contexts_dir, _head(repo)).is_file()


def test_the_installed_baseline_carries_its_measured_breadth(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """Measuring is the producer's cost, not every later `just check`'s."""
    _full_database(repo)

    assert tool.main([]) == 0

    installed = cached_baselines(contexts_dir)[0]
    assert breadth_path(installed.path).is_file()
    assert installed.breadth is not None
    assert installed.breadth.attributions == RING_SIZE


def test_a_partial_run_is_refused_but_can_be_forced(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """Contexts from a handful of test files are not a suite baseline."""
    _write_database(repo / ".coverage", test_files=2)

    assert tool.main([]) == 1
    assert cached_baselines(contexts_dir) == []

    assert tool.main(["--allow-partial"]) == 0
    assert baseline_path(contexts_dir, _head(repo)).is_file()


def test_an_uncommitted_src_change_is_refused_but_can_be_forced(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """Line numbers recorded off an edited tree do not describe HEAD."""
    _full_database(repo)
    _write(repo, "src/pkg/a.py", "VALUE = 1\nEXTRA = 2\n")

    assert tool.main([]) == 1
    assert cached_baselines(contexts_dir) == []

    assert tool.main(["--allow-dirty"]) == 0
    assert baseline_path(contexts_dir, _head(repo)).is_file()


def test_an_uncommitted_docs_change_does_not_block_the_install(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """Only instrumented code can desynchronize the database from HEAD."""
    _full_database(repo)
    _write(repo, "docs/development.md", "# docs\n\nedited\n")

    assert tool.main([]) == 0
    assert baseline_path(contexts_dir, _head(repo)).is_file()


def test_the_sha_can_be_named_explicitly(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    _full_database(repo)
    sha = "0" * 40

    assert tool.main(["--sha", sha]) == 0

    assert baseline_path(contexts_dir, sha).is_file()


def test_installing_prunes_the_cache_to_the_keep_limit(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    for index in range(4):
        _write_database(contexts_dir / f"{index:040x}.sqlite", test_files=1)
    _full_database(repo)

    assert tool.main(["--keep", "2"]) == 0

    remaining = cached_baselines(contexts_dir)
    assert len(remaining) == 2
    assert remaining[0].sha == _head(repo)


def test_installing_leaves_no_partial_file_behind(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """A sibling workspace may read this directory mid-install."""
    _full_database(repo)

    assert tool.main([]) == 0

    target = baseline_path(contexts_dir, _head(repo))
    assert sorted(entry.name for entry in contexts_dir.iterdir()) == sorted(
        [target.name, breadth_path(target).name]
    )


def test_if_enabled_respects_the_opt_out(
    tool: ModuleType, repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _full_database(repo)
    monkeypatch.setenv(tool.INSTALL_ENV, "0")

    assert tool.main(["--if-enabled"]) == 0
    assert cached_baselines(contexts_dir) == []


def test_if_enabled_never_fails_the_recording_recipe(
    tool: ModuleType, repo: Path, contexts_dir: Path
) -> None:
    """`just test-contexts` recorded a database; that much succeeded."""
    _write_database(repo / ".coverage", test_files=1)

    assert tool.main(["--if-enabled"]) == 0
    assert cached_baselines(contexts_dir) == []
