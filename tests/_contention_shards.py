"""Sharded collection for a whole-suite contention soak.

Every xdist worker normally collects the entire selection, and a collected
worker holds all of it: on the default lane that measured about 1 GB per
worker, so the soak's 26 workers needed about 26 GB before a single test ran.
Twenty-six-way collection on two pinned CPUs is also more than 20 minutes of
CPU-starved importing. Both the hosted runner (15.6 GB RAM, 3 GB swap) and a
local repro capped at that size were OOM-killed mid-collection, and the unit
manager then stopped the whole job (``sase-1rq.2.1.4.1.1``).

A sharded soak keeps all 26 workers on the same two CPUs, and keeps the full
selection, but each worker collects, imports, and runs only its own disjoint
shard of the test files. `tools/run_pytest contention` computes the shards with
the master gate's balancer (:func:`tests._test_shards.assign_shards`, LPT over
the committed timing table) and hands the controller a map through
`SHARDS_ENV`. The controller gives each worker its shard index through
``workerinput``, never the environment, so the pytest subprocesses tests spawn
cannot inherit it.

The default schedulers assume every worker collected the same items, so the
controller also installs `ShardScheduling`: each worker runs its own
collection, and a worker that replaces a crashed one takes over the crashed
worker's shard and only its unfinished tests.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections import deque
from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from xdist.report import report_collection_diff
from xdist.scheduler import EachScheduling

from tests._contention import SHARDS_ENV, read_shard_map


#: The ``workerinput`` keys a worker's shard reaches it under.
SHARD_INDEX_KEY = "sase_contention_shard"
SHARD_MAP_KEY = "sase_contention_shard_map"
CONTROLLER_PLUGIN_NAME = "sase-contention-shards"
WORKER_PLUGIN_NAME = "sase-contention-shard-filter"


def shard_owners(shards: Sequence[Sequence[str]]) -> dict[str, int]:
    """Each mapped file's owning shard index."""
    return {name: index for index, files in enumerate(shards) for name in files}


def shard_owner(relative_path: str, owners: Mapping[str, int], count: int) -> int:
    """The one shard that collects ``relative_path``.

    A test file the map does not name -- created after the harness wrote the
    map, or outside the discovery walk -- still belongs to exactly one shard,
    chosen by a stable digest so every worker agrees without coordinating.
    """
    owner = owners.get(relative_path)
    if owner is not None:
        return owner
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return int(digest, 16) % count


def node_shard(node: Any) -> int | None:
    """The shard index the controller assigned ``node``, if any."""
    value = getattr(node, "workerinput", {}).get(SHARD_INDEX_KEY)
    return None if value is None else int(value)


class ShardScheduling(EachScheduling):
    """Run each worker's own collection: its disjoint shard of the suite.

    ``EachScheduling`` already accepts a different collection per worker and
    runs each one whole. What it gets wrong for shards is replacement: it
    matches a replacement to a crashed worker by gateway spec, which every
    ``-n`` worker shares, and a replacement it cannot match reruns its whole
    collection. Here a replacement inherits only its own shard's unfinished
    tests, and one with nothing to inherit is shut down idle.
    """

    def __init__(self, config: pytest.Config, log: Any = None) -> None:
        super().__init__(config, log)
        self._replacements: set[Any] = set()

    def add_node_collection(self, node: Any, collection: Sequence[str]) -> None:
        if not self.collection_is_completed:
            super().add_node_collection(node, collection)
            return
        self._replacements.add(node)
        shard = node_shard(node)
        for dead in self._removed2pending:
            if node_shard(dead) != shard:
                continue
            dead_collection = self.node2collection[dead]
            if list(collection) != dead_collection:
                # Left pending, so the run ends loudly instead of dropping
                # the crashed worker's unfinished tests.
                self.log(
                    report_collection_diff(
                        dead_collection,
                        list(collection),
                        dead.gateway.id,
                        node.gateway.id,
                    )
                )
                return
            self.node2collection[node] = list(collection)
            self.node2pending[node] = self._removed2pending.pop(dead)
            return

    def schedule(self) -> None:
        assert self.collection_is_completed
        for node, pending in self.node2pending.items():
            if node in self._started:
                continue
            if node not in self._replacements:
                pending[:] = range(len(self.node2collection[node]))
                node.send_runtest_all()
            elif pending:
                node.send_runtest_some(pending)
            node.shutdown()
            self._started.append(node)


class ShardDistributor:
    """The controller side: hand out shards and schedule by them."""

    def __init__(
        self,
        shard_count: int,
        map_path: Path,
        *,
        write_line: Callable[[str], None] = lambda line: None,
    ) -> None:
        self._count = shard_count
        self._map_path = map_path
        self._write_line = write_line
        self._next = 0
        self._orphaned: deque[int] = deque()
        self._collected: dict[int, int] = {}
        self._announced = False

    @property
    def collected_items(self) -> int:
        return sum(self._collected.values())

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        # xdist configures a crashed worker's replacement right after
        # reporting the crash, so the replacement takes the orphaned shard.
        if self._orphaned:
            shard = self._orphaned.popleft()
        else:
            shard = self._next
            self._next += 1
        node.workerinput[SHARD_INDEX_KEY] = shard
        node.workerinput[SHARD_MAP_KEY] = str(self._map_path)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        shard = node_shard(node)
        if error is not None and shard is not None:
            self._orphaned.append(shard)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_make_scheduler(
        self, config: pytest.Config, log: Any
    ) -> ShardScheduling:
        return ShardScheduling(config, log)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: Any) -> None:
        shard = node_shard(node)
        if shard is None:
            return
        self._collected[shard] = len(ids)
        if self._announced or len(self._collected) < self._count:
            return
        self._announced = True
        self._write_line(self.summary())

    def summary(self) -> str:
        counts = self._collected.values()
        return (
            f"contention shards: {len(self._collected)} workers collected "
            f"{self.collected_items} items in total "
            f"({min(counts, default=0)}-{max(counts, default=0)} per worker)"
        )

    @pytest.hookimpl(wrapper=True)
    def pytest_runtestloop(
        self, session: pytest.Session
    ) -> Generator[None, object, object]:
        try:
            return (yield)
        finally:
            # xdist reports the last worker's collection as the session's;
            # with shards the session collected all of them.
            if self._collected:
                session.testscollected = self.collected_items


class ShardCollectionFilter:
    """The worker side: skip every test file another shard owns.

    Skipped before import, which is the point: a file this worker never runs
    costs it neither memory nor CPU.
    """

    def __init__(
        self,
        shard: int,
        shards: Sequence[Sequence[str]],
        *,
        rootpath: Path,
        patterns: Sequence[str],
    ) -> None:
        self._shard = shard
        self._count = len(shards)
        self._owners = shard_owners(shards)
        self._rootpath = rootpath
        self._patterns = tuple(patterns)

    def owns(self, relative_path: str) -> bool:
        return shard_owner(relative_path, self._owners, self._count) == self._shard

    def pytest_ignore_collect(self, collection_path: Path) -> bool | None:
        if collection_path.suffix != ".py" or not any(
            fnmatch.fnmatch(collection_path.name, pattern) for pattern in self._patterns
        ):
            return None
        try:
            relative = collection_path.relative_to(self._rootpath).as_posix()
        except ValueError:
            return None
        return None if self.owns(relative) else True


def register_controller_shards(config: pytest.Config) -> ShardDistributor | None:
    """Arm sharded collection on the controller, consuming the request."""
    # Popped like the failure record: nested pytest runs must not inherit it.
    requested = os.environ.pop(SHARDS_ENV, None)
    if not requested:
        return None
    map_path = Path(requested)
    try:
        shards = read_shard_map(map_path)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error

    def write_line(line: str) -> None:
        reporter = config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(line)

    distributor = ShardDistributor(len(shards), map_path, write_line=write_line)
    config.pluginmanager.register(distributor, CONTROLLER_PLUGIN_NAME)
    return distributor


def register_worker_shards(config: pytest.Config) -> None:
    """Restrict this worker's collection to its shard, if it was given one.

    A worker that cannot read the map refuses to start rather than collect
    everything: under `ShardScheduling` that would run its tests twice.
    """
    workerinput = getattr(config, "workerinput", None)
    if not isinstance(workerinput, dict) or SHARD_INDEX_KEY not in workerinput:
        return
    shards = read_shard_map(Path(workerinput[SHARD_MAP_KEY]))
    config.pluginmanager.register(
        ShardCollectionFilter(
            int(workerinput[SHARD_INDEX_KEY]),
            shards,
            rootpath=config.rootpath,
            patterns=config.getini("python_files"),
        ),
        WORKER_PLUGIN_NAME,
    )
