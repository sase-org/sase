"""Shared fixtures for the coverage-context ground-truth tests.

The suite lives in ``tests/test_test_selection_contexts_*.py``. Every module
there runs against the synthetic repository from
``tests._test_selection_fixtures`` and a coverage database it builds itself, so
nothing depends on the real repository's import graph or on a baseline
downloaded from CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests._test_selection import (
    Selection,
    SelectionOptions,
    select_tests,
)
from tests._test_selection_fixtures import (
    _git,
    _write,
    build_fixture_repo,
)


# The fixtures are registered under names that differ from their functions', so
# that importing them for discovery does not collide with the ``repo`` and
# ``contexts_dir`` parameters every test declares.


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path) -> Path:
    return build_fixture_repo(tmp_path)


@pytest.fixture(name="contexts_dir")
def contexts_dir_fixture(tmp_path: Path) -> Path:
    directory = tmp_path / "store" / "contexts"
    directory.mkdir(parents=True)
    return directory


def store_for(contexts_dir: Path) -> Path:
    """The health store whose sibling ``contexts/`` directory is ``contexts_dir``."""
    return contexts_dir.parent / "project"


def head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def add_dynamic_pair(repo: Path) -> None:
    """Add a src module and a test that never imports it, then commit both.

    This is the shape the static closure cannot see: the test reaches the
    module through something an ``import`` statement does not name.
    """
    _write(repo, "src/pkg/dynamic.py", "VALUE = 1\n")
    _write(repo, "tests/test_dynamic.py", "def test_it() -> None:\n    pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "dynamic pair")


def select(repo: Path, contexts_dir: Path, **kwargs: object) -> Selection:
    options = SelectionOptions(base_ref="HEAD", depth=2, max_ratio=1.0)
    return select_tests(
        repo,
        options,
        contexts_store=store_for(contexts_dir),
        **kwargs,  # type: ignore[arg-type]
    )
