from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests._suite_gate_lease import WorkerTokenLease
from tests._test_selection_gear import (
    REFUSED_TOKENS_UNAVAILABLE,
    SCOPED_WORKER_FLOOR,
)
from tests._test_selection_timings import TIMINGS_SCHEMA, recording_host


_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _ROOT / "tools" / "run_pytest"
# Preserve the idle-host waits as floors, then scale the slow-host budgets from
# the measured time to launch and admit the initially granted children.
_ADMISSION_DEADLINE_FLOOR_SECONDS = 20.0


_SCOPED_CONFTEST = """\
from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests._suite_gate import configure_suite_gate, unconfigure_suite_gate


def pytest_configure(config: pytest.Config) -> None:
    configure_suite_gate(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    unconfigure_suite_gate(config)
"""
_SCOPED_FILLER_COUNT = 9


def _tests_module_file(name: str) -> Path | None:
    """Resolve a dotted ``tests.*`` name to a file in this checkout."""
    if name != "tests" and not name.startswith("tests."):
        return None
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        relative = Path(*parts[:end])
        py_file = _ROOT / f"{relative}.py"
        if py_file.is_file():
            return py_file
        init_file = _ROOT / relative / "__init__.py"
        if init_file.is_file():
            return init_file
    return None


def _runner_import_closure_files() -> list[Path]:
    """tests/ modules the real runner imports, including ``-p`` plugin strings."""
    from tests._test_selection_graph import parse_import_targets

    pending: list[Path] = [_RUNNER]
    seen: set[Path] = set()
    files: list[Path] = []
    tests_root = _ROOT / "tests"
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if path != _RUNNER:
            files.append(path)
        source = path.read_text(encoding="utf-8")
        parse_path = (
            "tools/run_pytest.py" if path == _RUNNER else str(path.relative_to(_ROOT))
        )
        names = set(parse_import_targets(source, parse_path))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    names.add(node.value)
        for name in names:
            resolved = _tests_module_file(name)
            if resolved is not None:
                pending.append(resolved)
        if path == _RUNNER or tests_root not in path.parents:
            continue
        current = path.parent
        while tests_root in current.parents or current == tests_root:
            init_file = current / "__init__.py"
            if init_file.is_file():
                pending.append(init_file)
            if current == tests_root:
                break
            current = current.parent
    return sorted(files)


def _copy_runner_import_closure(root: Path) -> None:
    """Copy the runner's real tests.* import closure into a miniature repo."""
    for source in _runner_import_closure_files():
        destination = root / source.relative_to(_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, destination)


def _build_scoped_repo(root: Path) -> None:
    """Lay out a miniature repository the real runner can select tests in.

    The runner resolves its own ``REPO_ROOT`` from ``__file__``, so the runner
    and the modules it imports are *copied*, never symlinked. The copied tests
    modules are derived from the runner's actual import closure so a new helper
    cannot drop out of the miniature again.
    """
    (root / "tools").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "src" / "pkg").mkdir(parents=True)

    shutil.copy(_RUNNER, root / "tools" / "run_pytest")
    _copy_runner_import_closure(root)

    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(_SCOPED_CONFTEST, encoding="utf-8")
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "thing.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_thing.py").write_text(
        "from pkg import thing\n\n\ndef test_value() -> None:\n"
        "    assert thing.VALUE == 1\n",
        encoding="utf-8",
    )
    # Filler keeps the selection well under the default 25% escalation ratio, so
    # the run under test is a genuine scoped run rather than an escalation.
    for index in range(_SCOPED_FILLER_COUNT):
        (root / "tests" / f"test_filler_{index}.py").write_text(
            "def test_filler() -> None:\n    assert True\n", encoding="utf-8"
        )

    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gate@example.invalid")
    _git(root, "config", "user.name", "Suite Gate")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # An uncommitted edit is the change set the selector walks from.
    (root / "src" / "pkg" / "thing.py").write_text("VALUE = 1  # edited\n", "utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _miniature_pool_environment(
    root: Path,
    pool_dir: Path,
    *,
    slots: int = 1,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("PYTEST_"):
            environment.pop(name, None)
    for name in (
        "SASE_PYTEST_WORKERS",
        "SASE_TEST_GATE_DISABLED",
        "SASE_TEST_GATE_GOVERNED",
        "SASE_TEST_SELECTION_DEPTH",
        "SASE_TEST_SELECTION_MAX_RATIO",
        "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS",
        "SASE_TEST_SELECTION_SCOPED_WORKER_CEILING",
        "SASE_TEST_SELECTION_TIMINGS_DIR",
        "SASE_TEST_SELECTION_TIMINGS_DISABLED",
        "SASE_TEST_SHARD",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "SASE_CHECK_BASE": "HEAD",
            # Keep the runner's selection-health records inside the miniature
            # repo instead of the developer's real ``~/.sase`` store.
            "SASE_HOME": str(root / "sase-home"),
            "SASE_PYTEST_TMPDIR": str(root / "scratch"),
            "SASE_TEST_GATE_DIR": str(pool_dir),
            "SASE_TEST_GATE_SLOTS": str(slots),
            # Zero seconds turns any acquisition attempt into an immediate,
            # loud failure instead of a 45-minute queue.
            "SASE_TEST_GATE_TIMEOUT": "0",
        }
    )
    environment.update(extra or {})
    return environment


def _run_miniature_runner(
    root: Path,
    pool_dir: Path,
    mode: str,
    *,
    slots: int = 1,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "run_pytest"), mode, "-q"],
        cwd=root,
        env=_miniature_pool_environment(root, pool_dir, slots=slots, extra=extra),
        capture_output=True,
        text=True,
    )


def _over_budget_environment(root: Path) -> dict[str, str]:
    """Price the miniature repo's one real test above the serial budget.

    The gear only ever sees a selection ``RULE_SERIAL_BUDGET_EXCEEDED``
    rejected, so reaching it end to end means giving the selector a duration
    table and a budget the table's answer exceeds.
    """
    directory = root / "timings"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "20260806T000000Z-1.json").write_text(
        json.dumps(
            {
                "schema": TIMINGS_SCHEMA,
                "recorded_at": "2026-08-06T00:00:00+00:00",
                "host": recording_host(),
                "mode": "fast",
                "worker_count": 1,
                "file_count": 1,
                "durations": {"tests/test_thing.py": 900.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "SASE_TEST_SELECTION_TIMINGS_DIR": str(directory),
        "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "10",
    }


def _scoped_manifest(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / ".pytest_cache" / "sase-selection" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_runner_import_closure_includes_selection_layer_helpers() -> None:
    """The miniature copies the selection layer's real imports, not a hand list."""
    names = {path.name for path in _runner_import_closure_files()}
    assert "_agent_artifact_marker_audit_helpers.py" in names
    assert "_test_selection_rules.py" in names


def test_scoped_run_takes_no_token_while_the_pool_is_exhausted(
    tmp_path: Path,
) -> None:
    """The property this whole lane exists to deliver: no queueing, ever."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    holder = WorkerTokenLease(
        directory=pool_dir, budget=1, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    try:
        scoped = _run_miniature_runner(root, pool_dir, "scoped")
        # The control: the same exhausted pool genuinely blocks a governed run,
        # so the scoped success above cannot be a mis-configured pool.
        governed = _run_miniature_runner(root, pool_dir, "fast")
    finally:
        holder.release()

    assert scoped.returncode == 0, f"stdout:\n{scoped.stdout}\nstderr:\n{scoped.stderr}"
    assert "selected 1 of 10 test files" in scoped.stderr
    assert "1 passed" in scoped.stdout
    # Every live grant still belongs to this process: the scoped run took none.
    assert set(_active_grants(pool_dir, {os.getpid()})) == {os.getpid()}
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}
    assert governed.returncode != 0
    assert "worker token" in (governed.stdout + governed.stderr).lower()

    manifest = _scoped_manifest(root)
    assert manifest["escalated"] is False
    assert manifest["selected"] == ["tests/test_thing.py"]
    assert manifest["outcome"] == "passed"
    assert manifest["duration"] > 0
    # Nothing escalated, so the gear was never offered anything and the
    # manifest says nothing about it.
    assert "gear" not in manifest


def test_scoped_run_ignores_parent_shard_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested scoped subprocesses must not inherit the gate's fast-lane shard."""
    monkeypatch.setenv("SASE_TEST_SHARD", "2/6")
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    scoped = _run_miniature_runner(root, pool_dir, "scoped")

    assert scoped.returncode == 0, f"stdout:\n{scoped.stdout}\nstderr:\n{scoped.stderr}"
    assert "selected 1 of 10 test files" in scoped.stderr
    assert "1 passed" in scoped.stdout


def test_ungoverned_bypass_is_bounded_by_the_host_budget(tmp_path: Path) -> None:
    """The incident, end to end, and the route that replaces it.

    `SASE_TEST_GATE_DISABLED=1` still means "take no tokens and never queue".
    It no longer means "take the whole machine": the pool cannot see this run,
    so its width is the one thing that must stay inside the budget.
    """
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)
    bypass = {
        "SASE_PYTEST_WORKERS": "4",
        "SASE_TEST_GATE_DISABLED": "1",
        # The miniature repo carries the runner's imports, not the full lane's
        # in-pytest failure recorder.
        "SASE_TEST_SELECTION_HEALTH_DISABLED": "1",
    }

    over_budget = _run_miniature_runner(root, pool_dir, "fast", slots=1, extra=bypass)

    assert over_budget.returncode != 0
    refusal = over_budget.stdout + over_budget.stderr
    assert "Requested 4 pytest worker tokens" in refusal
    assert "SASE_TEST_GATE_SLOTS" in refusal

    # The supported route for a genuinely wide run: enlarge the pool where
    # concurrent runs can see it. The pool is held to its capacity throughout,
    # which is what proves the bypass still never queues.
    holder = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(4, 4, exact=True)
    try:
        widened = _run_miniature_runner(root, pool_dir, "fast", slots=4, extra=bypass)
    finally:
        holder.release()

    assert widened.returncode == 0, (
        f"stdout:\n{widened.stdout}\nstderr:\n{widened.stderr}"
    )
    assert "suite gate bypassed: running 4 ungoverned workers" in widened.stderr
    assert "SASE_TEST_GATE_SLOTS" in widened.stderr
    assert "bringing up nodes" in widened.stdout
    # Every token in the pool is still the one this process took.
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}


def test_over_budget_selection_runs_at_a_leased_width_and_releases_it(
    tmp_path: Path,
) -> None:
    """The middle gear, end to end: leased workers instead of the full suite."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    scoped = _run_miniature_runner(
        root, pool_dir, "scoped", slots=4, extra=_over_budget_environment(root)
    )

    assert scoped.returncode == 0, f"stdout:\n{scoped.stdout}\nstderr:\n{scoped.stderr}"
    assert "middle gear: running the over-budget selection at 4 worker(s)" in (
        scoped.stderr
    )
    assert "escalating to the governed full test lane" not in scoped.stderr
    # The selection ran, and it ran wide: 10 filler files would have run too if
    # this had escalated.
    assert "1 passed" in scoped.stdout
    # xdist only announces nodes when it has some: proof the run was parallel.
    assert "bringing up nodes" in scoped.stdout

    manifest = _scoped_manifest(root)
    assert "serial-budget-exceeded" in manifest["rules_fired"]
    # The rule that sent the run to the gear stays on the record: it is why
    # the third gear engaged, not something the gear undid.
    assert manifest["escalated"] is False
    assert manifest["selected"] == ["tests/test_thing.py"]
    assert manifest["outcome"] == "passed"
    assert manifest["gear"] == {
        "granted": True,
        "worker_count": 4,
        "ceiling": 4,
        "floor": SCOPED_WORKER_FLOOR,
        "reason": None,
    }

    # The lease outlived the run and no longer: the whole pool is free again.
    reclaimed = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    assert reclaimed.try_acquire(4, 4) == 4
    reclaimed.release()


def test_over_budget_selection_escalates_rather_than_queueing_for_a_lease(
    tmp_path: Path,
) -> None:
    """A refused gear is an escalation, never a wait."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    holder = WorkerTokenLease(
        directory=pool_dir, budget=1, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    started = time.monotonic()
    try:
        scoped = _run_miniature_runner(
            root, pool_dir, "scoped", slots=1, extra=_over_budget_environment(root)
        )
    finally:
        holder.release()
    elapsed = time.monotonic() - started

    assert "middle gear: no bounded lease (tokens-unavailable)" in scoped.stderr
    assert "escalating to the governed full test lane" in scoped.stderr
    # It escalated into an exhausted pool, whose zero-second timeout fails the
    # run loudly. That is the pre-existing escalation contract; what this test
    # pins is that the gear did not wait to get there.
    assert scoped.returncode != 0
    assert elapsed < _ADMISSION_DEADLINE_FLOOR_SECONDS
    # The holder's token was never taken from it.
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}

    manifest = _scoped_manifest(root)
    assert manifest["escalated"] is True
    assert manifest["selected"] == []
    assert manifest["outcome"] == "escalated"
    assert manifest["gear"] == {
        "granted": False,
        "worker_count": None,
        "ceiling": 4,
        "floor": SCOPED_WORKER_FLOOR,
        "reason": REFUSED_TOKENS_UNAVAILABLE,
    }


def _active_grants(pool_dir: Path, controller_pids: set[int]) -> dict[int, int]:
    grants: dict[int, int] = {}
    for token_path in pool_dir.glob("token-*.lock"):
        metadata = json.loads(token_path.read_text(encoding="utf-8"))
        pid = int(metadata["pid"])
        if pid in controller_pids:
            grants[pid] = int(metadata["granted"])
    return grants
