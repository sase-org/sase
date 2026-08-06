"""Shared fixtures for the diff-scoped test selection engine's tests.

The suite lives in ``tests/test_test_selection_{graph,closure,rules,budget,
manifest}.py``. Every assertion there runs against the synthetic repository
from ``tests._test_selection_fixtures``, built under ``tmp_path``. Asserting
against the real repository's import graph would make these tests rot on every
commit that adds or removes an import.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests._test_selection import (
    Selection,
    SelectionOptions,
    select_tests,
)
from tests._test_selection_fixtures import (
    build_fixture_repo,
    install_fresh_baseline,
)
from tests._test_selection_timings import (
    MIN_COVERAGE_ENV,
    TIMINGS_DIR_ENV,
    TIMINGS_DISABLED_ENV,
    timings_directory,
    write_timings,
)


@pytest.fixture(autouse=True)
def neutral_timings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the host's own timing knobs out of this suite's assertions.

    The budget rule reads the ambient environment, so an agent running the
    suite with ``SASE_TEST_SELECTION_TIMINGS_DISABLED=1`` would otherwise
    silently turn every budget assertion here into an assertion about the
    file-count fallback.
    """
    for name in (TIMINGS_DIR_ENV, TIMINGS_DISABLED_ENV, MIN_COVERAGE_ENV):
        monkeypatch.delenv(name, raising=False)


# The fixture is registered under a name that differs from its function's, so
# that importing it for discovery does not collide with the ``repo`` parameter
# the tests declare.


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path) -> Path:
    """A committed synthetic repository with a known import shape."""
    root = build_fixture_repo(tmp_path)
    install_fresh_baseline(root)
    return root


def select(
    root: Path,
    *,
    depth: int = 2,
    max_ratio: float = 1.0,
    base_ref: str = "HEAD",
    max_serial_seconds: float = 1.0e9,
    **kwargs: object,
) -> Selection:
    """Select against a *fresh* baseline, so the closure walks the given depth.

    Without one, ``no-baseline-depth-boost`` would buy every selection here an
    extra hop and these assertions would be measuring the compensation rather
    than the closure. The compensation has its own tests, in
    ``tests/test_test_selection_contexts_depth_boost.py``.
    """
    options = SelectionOptions(
        base_ref=base_ref,
        depth=depth,
        max_ratio=max_ratio,
        max_serial_seconds=max_serial_seconds,
    )
    kwargs.setdefault("contexts_store", root.parent / "selection-store" / "project")
    # An empty timing store, unless a test says otherwise. Without it these
    # selections would be costed against whatever table the host running the
    # suite happens to have recorded, which is neither this synthetic
    # repository's cost nor reproducible on another machine.
    kwargs.setdefault("timings_store", root.parent / "selection-store" / "no-timings")
    return select_tests(root, options, **kwargs)  # type: ignore[arg-type]


def with_timings(
    repo: Path, seconds_per_file: float, *, minute: int = 1
) -> tuple[Path, Selection]:
    """A timings store covering everything a change to ``src/pkg/a.py`` selects.

    Returns the store and the un-budgeted selection it was built from, so a
    caller can assert against the selection the budget is about to judge.
    """
    store = repo.parent / "selection-store" / "timings"
    baseline = select(repo, timings_store=store)
    write_timings(
        timings_directory(store, {}),
        dict.fromkeys(baseline.selected, seconds_per_file),
        mode="fast",
        pid=1000 + minute,
        now=datetime(2026, 8, 6, 12, minute, 0, tzinfo=UTC),
    )
    return store, baseline
