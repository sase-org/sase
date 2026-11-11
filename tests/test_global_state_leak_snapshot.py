"""Real-snapshot regressions for the global-state leak detector's fast paths.

Every test here drives ``_snapshot`` against live modules in ``sys.modules``
rather than fabricated fingerprint pairs, so the per-binding shortcuts in
``tests._global_state_leaks.fingerprints`` are exercised exactly as the cost
lane runs them.
"""

from __future__ import annotations

from collections import namedtuple
from collections.abc import Callable, Iterator
import functools
import json
import os
from pathlib import Path
import re
import sys
from types import FunctionType, ModuleType
from typing import Any
from uuid import uuid4

import pytest

from tests._global_state_leaks import fingerprints
from tests._global_state_leaks.diffing import (
    _classify_cache_change,
    _diff_snapshots,
)
from tests._global_state_leaks.fingerprints import _snapshot as capture
from tests._global_state_leaks.models import _Change, _Snapshot


_ROOT = Path(__file__).resolve().parents[1]
_CacheInfo = namedtuple("_CacheInfo", "hits misses maxsize currsize")

_POISON_MODULE = """
import sase

sase._LEAK_FOR_TEST = {"value": "before"}

def test_poison_global_state():
    sase._LEAK_FOR_TEST["value"] = "after"

def test_clean():
    assert sase._LEAK_FOR_TEST
"""

_CLEAN_MODULE = """
import sase

sase._CLEAN_FOR_TEST = {"value": "before"}

def test_reads_only():
    assert sase._CLEAN_FOR_TEST["value"] == "before"

def test_restores_its_own_change():
    sase._CLEAN_FOR_TEST["value"] = "during"
    sase._CLEAN_FOR_TEST["value"] = "before"
"""


def _new_probe_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    name = f"sase._leak_probe_{uuid4().hex}"
    module = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    return _new_probe_module(monkeypatch)


def _name(module: Any, attr: str) -> str:
    return f"{module.__name__}.{attr}"


def _poisoning(before: _Snapshot, after: _Snapshot, module: Any) -> dict[str, str]:
    prefix = f"{module.__name__}."
    changes: list[_Change] = list(_diff_snapshots(before, after).poisoning)
    return {
        change.name: change.reason
        for change in changes
        if change.name.startswith(prefix)
    }


@pytest.fixture
def fingerprint_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[object], int]]:
    """Count real ``_global_fingerprint`` work per value identity."""
    calls: list[object] = []
    real = fingerprints._global_fingerprint

    def _counting(value: object):  # type: ignore[no-untyped-def]
        calls.append(value)
        return real(value)

    monkeypatch.setattr(fingerprints, "_global_fingerprint", _counting)
    yield lambda value: sum(1 for seen in calls if seen is value)


def test_same_size_in_place_edits_are_poisoning(probe: Any) -> None:
    probe._STATE = {"key": "before", "other": 1}
    probe._ITEMS = ["x", "y"]
    before = capture()

    probe._STATE["key"] = "after"
    probe._ITEMS[1] = "z"
    after = capture()

    assert len(probe._STATE) == 2 and len(probe._ITEMS) == 2
    assert _poisoning(before, after, probe) == {
        _name(probe, "_STATE"): "changed-value",
        _name(probe, "_ITEMS"): "changed-value",
    }


def test_nested_mutation_without_identity_or_length_change_is_poisoning(
    probe: Any,
) -> None:
    nested_list = ["a"]
    nested_dict = {"inner": "a"}
    probe._STATE = {"list": nested_list, "dict": nested_dict}
    probe._ITEMS = [nested_dict]
    state, items = probe._STATE, probe._ITEMS
    before = capture()

    nested_list[0] = "b"
    nested_dict["inner"] = "b"
    after = capture()

    assert probe._STATE is state and probe._ITEMS is items
    assert _poisoning(before, after, probe) == {
        _name(probe, "_STATE"): "changed-value",
        _name(probe, "_ITEMS"): "changed-value",
    }


def test_rebinding_deleting_and_kind_changes_remain_observable(
    probe: Any,
) -> None:
    probe._REBOUND = {"a": 1}
    probe._DELETED = {"a": 1}
    probe._UNTRACKED = {"a": 1}
    probe._KIND = {"a": 1}
    before = capture()

    probe._REBOUND = {"a": 2}
    del probe._DELETED
    probe._UNTRACKED = "now a string"
    probe._KIND = ["a"]
    after = capture()

    assert _poisoning(before, after, probe) == {
        _name(probe, "_REBOUND"): "changed-value",
        _name(probe, "_DELETED"): "changed-to-untracked-or-deleted",
        _name(probe, "_UNTRACKED"): "changed-to-untracked-or-deleted",
        _name(probe, "_KIND"): "changed-kind",
    }


def test_late_modules_attributes_and_replaced_modules_are_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture()  # Warm every cross-snapshot table before the module exists.
    late = _new_probe_module(monkeypatch)
    late._LATE = {"a": 1}

    appeared = capture()
    assert appeared.globals[_name(late, "_LATE")].length == 1

    late._ADDED = ["x"]
    added = capture()
    assert _name(late, "_ADDED") in added.globals

    replacement: Any = ModuleType(late.__name__)
    replacement._LATE = {"a": 2}
    monkeypatch.setitem(sys.modules, late.__name__, replacement)
    replaced = capture()

    assert _name(late, "_ADDED") not in replaced.globals
    assert _poisoning(added, replaced, late) == {
        _name(late, "_LATE"): "changed-value",
        _name(late, "_ADDED"): "changed-to-untracked-or-deleted",
    }


def test_aliased_state_keeps_every_name_and_is_fingerprinted_once(
    monkeypatch: pytest.MonkeyPatch,
    fingerprint_calls: Callable[[object], int],
) -> None:
    first = _new_probe_module(monkeypatch)
    second = _new_probe_module(monkeypatch)
    shared = {"a": 1}
    first._SHARED = shared
    first._ALIAS = shared
    second._SHARED = shared
    names = [
        _name(first, "_SHARED"),
        _name(first, "_ALIAS"),
        _name(second, "_SHARED"),
    ]

    before = capture()
    assert fingerprint_calls(shared) == 1
    assert {before.globals[name].length for name in names} == {1}

    shared["a"] = 2
    after = capture()
    # Mutable state is re-fingerprinted on every snapshot, once per object.
    assert fingerprint_calls(shared) == 2
    assert len({after.globals[name] for name in names}) == 1
    assert {after.globals[name].digest for name in names}.isdisjoint(
        {before.globals[name].digest for name in names}
    )
    assert set(_poisoning(before, after, first)) == set(names[:2])
    assert set(_poisoning(before, after, second)) == {names[2]}


def test_only_provably_immutable_fingerprints_are_reused(
    monkeypatch: pytest.MonkeyPatch,
    probe: Any,
    fingerprint_calls: Callable[[object], int],
) -> None:
    monkeypatch.setattr(fingerprints, "_IMMUTABLE_FINGERPRINTS", {})
    probe._NAMES = frozenset({"a", "b", 1, None})
    # ``re`` memoizes compiled patterns, so make this one unique to the test.
    probe._PATTERN = re.compile(f"x+{uuid4().hex}", re.IGNORECASE)
    probe._NESTED = frozenset({("a",), "b"})
    probe._SET = {"a"}
    probe._DICT = {"a": "b"}
    probe._LIST = ["a"]
    probe._NONE = None

    first = capture()
    second = capture()

    assert fingerprint_calls(probe._NAMES) == 1
    assert fingerprint_calls(probe._PATTERN) == 1
    for mutable_or_nested in (probe._NESTED, probe._SET, probe._DICT, probe._LIST):
        assert fingerprint_calls(mutable_or_nested) == 2
    for attr in ("_NAMES", "_PATTERN", "_NESTED", "_SET", "_DICT", "_LIST", "_NONE"):
        assert first.globals[_name(probe, attr)] == second.globals[_name(probe, attr)]
    assert _poisoning(first, second, probe) == {}


def test_lru_caches_are_observed_through_warm_clear_and_replace(
    probe: Any,
) -> None:
    @functools.cache
    def cached(value: int) -> int:
        return value

    probe.cached = cached
    probe._private_cached = cached
    names = (_name(probe, "cached"), _name(probe, "_private_cached"))

    cold = capture()
    assert {cold.caches[name].currsize for name in names} == {0}

    cached(1)
    cached(1)
    warm = capture()
    assert warm.caches[names[0]].hits == 1 and warm.caches[names[0]].currsize == 1
    assert _classify_cache_change(cold.caches[names[0]], warm.caches[names[0]]) == (
        "warming"
    )

    cached.cache_clear()
    cleared = capture()
    assert _classify_cache_change(warm.caches[names[0]], cleared.caches[names[0]]) == (
        "cooling"
    )

    @functools.lru_cache(maxsize=4)
    def replacement(value: int) -> int:
        return value

    probe.cached = replacement
    replaced = capture()
    assert replaced.caches[names[0]].maxsize == 4
    assert replaced.caches[names[1]].maxsize is None
    assert _classify_cache_change(
        cleared.caches[names[0]], replaced.caches[names[0]]
    ) == ("invalidation")


def test_attached_cache_apis_are_seen_after_a_negative_probe(
    probe: Any,
) -> None:
    """A stale negative probe result must never hide a later cache API."""
    counter = {"hits": 0}

    def plain() -> None:
        return None

    class Registry:
        pass

    class Instance:
        pass

    instance = Instance()
    probe.plain = plain
    probe.Registry = Registry
    probe.instance = instance

    def _info() -> _CacheInfo:
        return _CacheInfo(counter["hits"], 0, None, counter["hits"])

    def _clear() -> None:
        counter["hits"] = 0

    before = capture()
    for attr in ("plain", "Registry", "instance"):
        assert _name(probe, attr) not in before.caches

    plain.cache_info = _info  # type: ignore[attr-defined]
    plain.cache_clear = _clear  # type: ignore[attr-defined]
    Registry.cache_info = staticmethod(_info)  # type: ignore[attr-defined]
    Registry.cache_clear = staticmethod(_clear)  # type: ignore[attr-defined]
    instance.cache_info = _info  # type: ignore[attr-defined]
    instance.cache_clear = _clear  # type: ignore[attr-defined]
    attached = capture()
    for attr in ("plain", "Registry", "instance"):
        assert attached.caches[_name(probe, attr)].currsize == 0

    counter["hits"] = 3
    warmed = capture()
    assert warmed.caches[_name(probe, "plain")].hits == 3

    del plain.cache_clear  # type: ignore[attr-defined]
    detached = capture()
    assert _name(probe, "plain") not in detached.caches


def test_incomplete_or_broken_cache_apis_are_ignored(probe: Any) -> None:
    class InfoOnly:
        def cache_info(self) -> _CacheInfo:
            return _CacheInfo(0, 0, None, 0)

    class Raises:
        def cache_info(self) -> _CacheInfo:
            raise RuntimeError("boom")

        def cache_clear(self) -> None:
            return None

    class WrongShape:
        def cache_info(self) -> tuple[int, int]:
            return (0, 0)

        def cache_clear(self) -> None:
            return None

    probe.info_only = InfoOnly()
    probe.raises = Raises()
    probe.wrong_shape = WrongShape()
    snapshot = capture()

    for attr in ("info_only", "raises", "wrong_shape"):
        assert _name(probe, attr) not in snapshot.caches


def test_failed_probe_never_asks_for_cache_clear(probe: Any) -> None:
    class Recorder:
        def __init__(self) -> None:
            self.lookups: list[str] = []

        def __getattr__(self, name: str) -> object:
            self.lookups.append(name)
            raise AttributeError(name)

    recorder = Recorder()
    probe.recorder = recorder
    capture()

    assert recorder.lookups == ["cache_info"]


def test_cache_protocol_free_types_reject_anything_that_could_expose_it() -> None:
    class Plain:
        pass

    @functools.cache
    def cached() -> None:
        return None

    assert fingerprints._cache_protocol_free_types((str, dict)) == frozenset(
        {str, dict}
    )
    for candidate in (Plain, FunctionType, ModuleType, type(cached)):
        with pytest.raises(TypeError):
            fingerprints._cache_protocol_free_types((candidate,))


def test_private_name_classification_is_cached_and_bounded(
    monkeypatch: pytest.MonkeyPatch, probe: Any
) -> None:
    monkeypatch.setattr(fingerprints, "_PRIVATE_NAME_CACHE", {})
    expected = {
        "_x": True,
        "_": True,
        "__x": True,
        "x__": False,
        "__x__": False,
        "x": False,
        "": False,
    }
    for name, is_private in expected.items():
        assert fingerprints._is_private_global_name(name) is is_private
    assert fingerprints._PRIVATE_NAME_CACHE == expected

    monkeypatch.setattr(fingerprints, "_PRIVATE_NAME_CACHE", {})
    monkeypatch.setattr(fingerprints, "_PRIVATE_NAME_CACHE_LIMIT", 0)
    probe._BEYOND_LIMIT = {"a": 1}
    snapshot = capture()

    assert fingerprints._PRIVATE_NAME_CACHE == {}
    assert _name(probe, "_BEYOND_LIMIT") in snapshot.globals


def test_environment_values_stay_hashed_in_snapshots_and_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"SASE_LEAK_PROBE_{uuid4().hex.upper()}"
    secret = f"hunter2-{uuid4().hex}"
    rotated = f"hunter3-{uuid4().hex}"
    monkeypatch.setenv(key, secret)
    before = capture()
    monkeypatch.setenv(key, rotated)
    after = capture()

    rendered = repr((before.environ, after.environ))
    assert secret not in rendered and rotated not in rendered
    environment = [
        change
        for change in _diff_snapshots(before, after).poisoning
        if change.kind == "environment"
    ]
    assert len(environment) == 1
    assert environment[0].details is not None
    assert environment[0].details["changed_keys"] == [key]
    report = json.dumps(environment[0].public())
    assert secret not in report and rotated not in report


def test_real_cwd_and_sys_path_changes_keep_their_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = capture()
    monkeypatch.chdir(tmp_path)
    sys.path.append(str(tmp_path / "appended"))
    appended = capture()

    diff = _diff_snapshots(before, appended)
    [cwd_change] = _ambient_poisoning(diff.poisoning)
    assert cwd_change.kind == "cwd"
    assert cwd_change.after == {"kind": "cwd", "value": os.getcwd()}
    assert diff.warming_counts.get("sys_path") == 1

    sys.path.insert(0, str(tmp_path / "prepended"))
    prepended = capture()
    rewritten = _ambient_poisoning(_diff_snapshots(appended, prepended).poisoning)
    assert [change.kind for change in rewritten] == ["sys_path"]


def _ambient_poisoning(changes: tuple[_Change, ...]) -> list[_Change]:
    return [change for change in changes if change.kind in {"cwd", "sys_path"}]


def _run_leak_gate(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    *extra: str,
) -> tuple[pytest.RunResult, dict]:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    for key in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
        "SASE_GLOBAL_LEAK_WORKER_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    report_path = pytester.path / "leaks.json"
    pytester.makepyfile(source)
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        f"--sase-global-leak-report={report_path}",
        *extra,
        timeout=120,
    )
    return result, json.loads(report_path.read_text(encoding="utf-8"))


def test_clean_run_passes_the_blocking_gate(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, report = _run_leak_gate(
        pytester, monkeypatch, _CLEAN_MODULE, "--sase-fail-on-global-leaks"
    )

    result.assert_outcomes(passed=2)
    assert result.ret == 0
    assert report["summary"]["poisoning_changes"] == 0
    assert report["summary"]["observed_tests"] == 2


def test_xdist_poisoning_fails_the_gate_and_aggregates_workers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, report = _run_leak_gate(
        pytester,
        monkeypatch,
        _POISON_MODULE,
        "--sase-fail-on-global-leaks",
        "-n",
        "2",
    )

    result.assert_outcomes(passed=2)
    assert result.ret != 0
    assert report["summary"]["observed_tests"] == 2
    assert report["summary"]["poisoning_changes"] == 1
    [record] = report["poisoning"]
    assert record["worker_id"].startswith("gw")
    assert record["nodeid"].endswith("::test_poison_global_state")
    assert record["changes"][0]["name"] == "sase._LEAK_FOR_TEST"
    output = "\n".join(result.outlines)
    assert "test_poison_global_state" in output
    assert "global:sase._LEAK_FOR_TEST" in output


def test_xdist_report_only_mode_keeps_pytest_green(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, report = _run_leak_gate(pytester, monkeypatch, _POISON_MODULE, "-n", "2")

    result.assert_outcomes(passed=2)
    assert result.ret == 0
    assert report["summary"]["poisoning_changes"] == 1


def test_identity_memos_never_trust_a_recycled_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A memo entry left by a dead object must not answer for its id's reuse."""
    live = {"live": 1}
    stale = fingerprints._global_fingerprint({"stale": 2})
    assert stale is not None
    aliases: dict = {id(live): (object(), stale)}

    fingerprint = fingerprints._aliased_global_fingerprint(live, aliases)
    assert fingerprint == fingerprints._global_fingerprint(live)
    assert aliases[id(live)][0] is live

    frozen = frozenset({"live"})
    monkeypatch.setattr(
        fingerprints, "_IMMUTABLE_FINGERPRINTS", {id(frozen): (object(), stale)}
    )
    assert fingerprints._immutable_global_fingerprint(
        frozen, id(frozen)
    ) == fingerprints._global_fingerprint(frozen)
