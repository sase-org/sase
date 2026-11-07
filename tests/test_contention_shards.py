"""Sharded collection for the whole-suite contention soak.

The property that cannot bend is coverage: every test file must be collected,
and run, by exactly one worker, including after a worker crashes. A dropped
file is lost coverage; a doubled one is a duplicated tally. The other
properties -- nothing reaches nested pytest runs, and an unusable shard map
fails instead of collecting everything -- keep that one true.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests._contention import (
    DIAGNOSTICS_ENV,
    FAILURES_ENV,
    SHARDS_ENV,
    read_shard_map,
    write_shard_map,
)
from tests._contention_shards import (
    CONTROLLER_PLUGIN_NAME,
    SHARD_INDEX_KEY,
    SHARD_MAP_KEY,
    WORKER_PLUGIN_NAME,
    ShardCollectionFilter,
    ShardDistributor,
    ShardScheduling,
    register_controller_shards,
    register_worker_shards,
    shard_owner,
    shard_owners,
)


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = ("test_*.py", "*_test.py")


class _Gateway:
    def __init__(self, gateway_id: str) -> None:
        self.id = gateway_id
        self.spec = "popen"


class _Node:
    """A worker controller as the scheduler and distributor see one."""

    def __init__(self, gateway_id: str, shard: int | None = None) -> None:
        self.gateway = _Gateway(gateway_id)
        self.workerinput: dict[str, Any] = {"workerid": gateway_id}
        if shard is not None:
            self.workerinput[SHARD_INDEX_KEY] = shard
        self.sent: list[tuple[str, tuple[int, ...]]] = []

    def send_runtest_all(self) -> None:
        self.sent.append(("all", ()))

    def send_runtest_some(self, indices: list[int]) -> None:
        self.sent.append(("some", tuple(indices)))

    def shutdown(self) -> None:
        self.sent.append(("shutdown", ()))


class _Log:
    def __init__(self) -> None:
        self.lines: list[tuple[object, ...]] = []

    def eachsched(self, *args: object) -> None:
        self.lines.append(args)


class _SchedulerConfig:
    def __init__(self, workers: int) -> None:
        self._workers = workers

    def getvalue(self, name: str) -> list[str]:
        assert name == "tx"
        return [f"{self._workers}*popen"]


class _Manager:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register(self, plugin: object, name: str) -> None:
        self.registered[name] = plugin


class _Config:
    def __init__(
        self, *, workerinput: dict[str, Any] | None = None, rootpath: Path = ROOT
    ) -> None:
        self.pluginmanager = _Manager()
        self.rootpath = rootpath
        if workerinput is not None:
            self.workerinput = workerinput

    def getini(self, name: str) -> list[str]:
        assert name == "python_files"
        return list(PATTERNS)


def _scheduler(workers: int) -> tuple[ShardScheduling, _Log]:
    log = _Log()
    return ShardScheduling(_SchedulerConfig(workers), log), log  # type: ignore[arg-type]


def test_shard_map_round_trips_and_rejects_anything_else(tmp_path: Path) -> None:
    path = tmp_path / "shards.json"
    write_shard_map(path, [("tests/b.py", "tests/a.py"), ("tests/c.py",)])

    assert read_shard_map(path) == (("tests/a.py", "tests/b.py"), ("tests/c.py",))

    path.write_text('{"schema": 99, "shards": [["tests/a.py"]]}', encoding="utf-8")
    with pytest.raises(ValueError, match="no usable"):
        read_shard_map(path)
    path.write_text('{"schema": 1, "shards": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        read_shard_map(path)
    with pytest.raises(ValueError, match="no usable"):
        read_shard_map(tmp_path / "missing.json")


def test_an_unmapped_file_still_gets_one_stable_owner() -> None:
    owners = shard_owners([("tests/test_a.py",), ("tests/test_b.py",)])

    assert shard_owner("tests/test_b.py", owners, 2) == 1
    unmapped = shard_owner("tests/test_new.py", owners, 2)
    assert unmapped in (0, 1)
    assert shard_owner("tests/test_new.py", owners, 2) == unmapped


def test_every_test_file_is_collected_by_exactly_one_worker(tmp_path: Path) -> None:
    shards = [
        ("tests/test_a.py", "tests/sub/test_c.py"),
        ("tests/test_b.py",),
        ("tests/sub/legacy_test.py",),
    ]
    filters = [
        ShardCollectionFilter(index, shards, rootpath=tmp_path, patterns=PATTERNS)
        for index in range(len(shards))
    ]
    test_files = [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/sub/test_c.py",
        "tests/sub/legacy_test.py",
        "tests/sub/test_added_after_the_map.py",
    ]

    for name in test_files:
        collectors = [
            index
            for index, shard_filter in enumerate(filters)
            if shard_filter.pytest_ignore_collect(tmp_path / name) is None
        ]
        assert len(collectors) == 1, (name, collectors)

    # Directories, conftests, helpers, and paths outside the root are never
    # this filter's to skip: every worker must still see them.
    for path in (
        tmp_path / "tests",
        tmp_path / "tests" / "conftest.py",
        tmp_path / "tests" / "__init__.py",
        tmp_path / "tests" / "_helpers.py",
        Path("/elsewhere/test_outside.py"),
    ):
        assert all(f.pytest_ignore_collect(path) is None for f in filters), path


def test_each_worker_runs_its_whole_shard_once_collection_completes() -> None:
    scheduler, _log = _scheduler(2)
    first, second = _Node("gw0", 0), _Node("gw1", 1)
    scheduler.add_node(first)
    scheduler.add_node(second)

    scheduler.add_node_collection(first, ["a::1", "a::2"])
    assert not scheduler.collection_is_completed
    scheduler.add_node_collection(second, ["b::1"])
    scheduler.schedule()

    assert first.sent == [("all", ()), ("shutdown", ())]
    assert second.sent == [("all", ()), ("shutdown", ())]
    assert scheduler.node2pending[first] == [0, 1]

    assert not scheduler.tests_finished
    # As in every xdist scheduler, a worker's last pending test is the one it
    # runs on shutdown, so one left per worker already counts as finished.
    scheduler.mark_test_complete(first, 0)
    assert scheduler.tests_finished


def test_a_replacement_inherits_only_its_own_shards_unfinished_tests() -> None:
    scheduler, _log = _scheduler(2)
    first, second = _Node("gw0", 0), _Node("gw1", 1)
    for node in (first, second):
        scheduler.add_node(node)
    scheduler.add_node_collection(first, ["a::1", "a::2", "a::3"])
    scheduler.add_node_collection(second, ["b::1", "b::2"])
    scheduler.schedule()
    scheduler.mark_test_complete(first, 0)

    # gw0 crashes inside a::2; a::3 is the only test nobody has run.
    assert scheduler.remove_node(first) == "a::2"
    replacement = _Node("gw2", 0)
    scheduler.add_node(replacement)
    scheduler.add_node_collection(replacement, ["a::1", "a::2", "a::3"])
    scheduler.schedule()

    assert replacement.sent == [("some", (2,)), ("shutdown", ())]
    assert second.sent == [("all", ()), ("shutdown", ())]
    scheduler.mark_test_complete(second, 0)
    scheduler.mark_test_complete(second, 1)
    scheduler.mark_test_complete(replacement, 2)
    assert scheduler.tests_finished


def test_a_replacement_with_nothing_left_is_shut_down_idle() -> None:
    scheduler, _log = _scheduler(1)
    only = _Node("gw0", 0)
    scheduler.add_node(only)
    scheduler.add_node_collection(only, ["a::1"])
    scheduler.schedule()

    # Crashing inside the shard's last test leaves nothing to rerun.
    assert scheduler.remove_node(only) == "a::1"
    replacement = _Node("gw1", 0)
    scheduler.add_node(replacement)
    scheduler.add_node_collection(replacement, ["a::1"])
    scheduler.schedule()

    assert replacement.sent == [("shutdown", ())]
    assert scheduler.tests_finished


def test_a_replacement_that_collected_differently_leaves_the_run_unfinished() -> None:
    scheduler, log = _scheduler(1)
    only = _Node("gw0", 0)
    scheduler.add_node(only)
    scheduler.add_node_collection(only, ["a::1", "a::2"])
    scheduler.schedule()
    scheduler.remove_node(only)

    replacement = _Node("gw1", 0)
    scheduler.add_node(replacement)
    scheduler.add_node_collection(replacement, ["a::1", "a::changed"])
    scheduler.schedule()

    assert replacement.sent == [("shutdown", ())]
    assert log.lines
    # Unfinished rather than silently short: xdist then fails the run.
    assert not scheduler.tests_finished


def test_distributor_hands_each_worker_a_shard_and_a_crashed_ones_to_its_clone(
    tmp_path: Path,
) -> None:
    lines: list[str] = []
    distributor = ShardDistributor(2, tmp_path / "shards.json", write_line=lines.append)
    first, second = _Node("gw0"), _Node("gw1")

    distributor.pytest_configure_node(first)
    distributor.pytest_configure_node(second)
    assert [
        first.workerinput[SHARD_INDEX_KEY],
        second.workerinput[SHARD_INDEX_KEY],
    ] == [0, 1]
    assert first.workerinput[SHARD_MAP_KEY] == str(tmp_path / "shards.json")

    # A clean finish orphans nothing; a crash orphans the crashed shard.
    distributor.pytest_testnodedown(first, None)
    distributor.pytest_testnodedown(second, "worker 'gw1' crashed")
    clone = _Node("gw2")
    distributor.pytest_configure_node(clone)
    assert clone.workerinput[SHARD_INDEX_KEY] == 1

    assert isinstance(
        distributor.pytest_xdist_make_scheduler(_SchedulerConfig(2), _Log()),  # type: ignore[arg-type]
        ShardScheduling,
    )
    distributor.pytest_xdist_node_collection_finished(first, ["a::1", "a::2"])
    assert lines == []
    distributor.pytest_xdist_node_collection_finished(second, ["b::1"])
    assert lines == [
        "contention shards: 2 workers collected 3 items in total (1-2 per worker)"
    ]
    assert distributor.collected_items == 3


def test_the_session_counts_every_shard_not_the_last_one_reported(
    tmp_path: Path,
) -> None:
    distributor = ShardDistributor(2, tmp_path / "shards.json")
    distributor.pytest_xdist_node_collection_finished(_Node("gw0", 0), ["a::1", "a::2"])
    distributor.pytest_xdist_node_collection_finished(_Node("gw1", 1), [])

    class _Session:
        testscollected = 0

    session = _Session()
    loop = distributor.pytest_runtestloop(session)  # type: ignore[arg-type]
    next(loop)
    with pytest.raises(StopIteration):
        loop.send(True)

    assert session.testscollected == 2


def test_controller_consumes_the_request_and_a_bad_map_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "shards.json"
    write_shard_map(path, [("tests/test_a.py",)])
    monkeypatch.setenv(SHARDS_ENV, str(path))
    config = _Config()

    distributor = register_controller_shards(config)  # type: ignore[arg-type]

    assert isinstance(distributor, ShardDistributor)
    assert config.pluginmanager.registered == {CONTROLLER_PLUGIN_NAME: distributor}
    # Popped, so the pytest subprocesses tests spawn cannot inherit it.
    assert SHARDS_ENV not in os.environ
    assert register_controller_shards(_Config()) is None  # type: ignore[arg-type]

    monkeypatch.setenv(SHARDS_ENV, str(tmp_path / "missing.json"))
    with pytest.raises(pytest.UsageError):
        register_controller_shards(_Config())  # type: ignore[arg-type]


def test_worker_filters_only_when_its_controller_assigned_a_shard(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shards.json"
    write_shard_map(path, [("tests/test_a.py",), ("tests/test_b.py",)])

    unsharded = _Config(workerinput={"workerid": "gw0"})
    register_worker_shards(unsharded)  # type: ignore[arg-type]
    assert unsharded.pluginmanager.registered == {}

    sharded = _Config(
        workerinput={"workerid": "gw1", SHARD_INDEX_KEY: 1, SHARD_MAP_KEY: str(path)},
        rootpath=tmp_path,
    )
    register_worker_shards(sharded)  # type: ignore[arg-type]
    shard_filter = sharded.pluginmanager.registered[WORKER_PLUGIN_NAME]
    assert isinstance(shard_filter, ShardCollectionFilter)
    assert shard_filter.pytest_ignore_collect(tmp_path / "tests" / "test_a.py")
    assert shard_filter.pytest_ignore_collect(tmp_path / "tests" / "test_b.py") is None

    # Collecting everything instead would run this worker's tests twice.
    broken = _Config(
        workerinput={
            "workerid": "gw0",
            SHARD_INDEX_KEY: 0,
            SHARD_MAP_KEY: str(tmp_path / "missing.json"),
        }
    )
    with pytest.raises(ValueError):
        register_worker_shards(broken)  # type: ignore[arg-type]


def test_a_real_sharded_xdist_run_imports_and_runs_every_file_exactly_once(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
        "PYTEST_ADDOPTS",
        FAILURES_ENV,
        DIAGNOSTICS_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    imports = pytester.path / "imports.log"
    module = f"""
        import os
        with open({str(imports)!r}, "a", encoding="utf-8") as log:
            log.write(os.environ["PYTEST_XDIST_WORKER"] + " " + __name__ + "\\n")

        def test_one():
            pass

        def test_two():
            pass
    """
    names = [f"test_mod{index}" for index in range(5)]
    pytester.makepyfile(**dict.fromkeys(names, module))
    # One file the map never names: it must still run, exactly once.
    shard_map = pytester.path / "shards.json"
    write_shard_map(
        shard_map,
        [("test_mod0.py", "test_mod1.py"), ("test_mod2.py",), ("test_mod3.py",)],
    )
    monkeypatch.setenv(SHARDS_ENV, str(shard_map))

    result = pytester.runpytest_subprocess(
        "-n",
        "3",
        "-p",
        "tests._contention_plugin",
        "-p",
        "no:cacheprovider",
        timeout=120,
    )

    result.assert_outcomes(passed=10)
    result.stdout.fnmatch_lines(
        ["contention shards: 3 workers collected 10 items in total (*)"]
    )
    imported = imports.read_text(encoding="utf-8").split("\n")[:-1]
    assert sorted(line.split()[1] for line in imported) == sorted(names)
    workers_for = {line.split()[1]: line.split()[0] for line in imported}
    assert workers_for["test_mod0"] == workers_for["test_mod1"]
    assert (
        len(
            {
                workers_for["test_mod0"],
                workers_for["test_mod2"],
                workers_for["test_mod3"],
            }
        )
        == 3
    )
