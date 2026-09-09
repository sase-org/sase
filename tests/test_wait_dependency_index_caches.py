"""Cache behavior for the wait-dependency index query hot paths."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import WaitDependencyIndex
from sase.core.wait_dependency_resolution import _artifact_state


def _completed_done() -> dict[str, str]:
    return {"outcome": "completed"}


def _meta(
    name: str,
    *,
    family: str | None = None,
    tribe: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {"name": name}
    if family is not None:
        data["workflow_name"] = family
        data["agent_family"] = family
    if tribe is not None:
        data["tribe"] = tribe
    return data


def _write_agent(
    root: Path,
    timestamp: str,
    name: str,
    *,
    family: str | None = None,
    tribe: str | None = None,
    done: bool = True,
) -> Path:
    artifact_dir = root / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(_meta(name, family=family, tribe=tribe)),
        encoding="utf-8",
    )
    if done:
        (artifact_dir / "done.json").write_text(
            json.dumps(_completed_done()),
            encoding="utf-8",
        )
    return artifact_dir


def _add_scan_record(index: WaitDependencyIndex, artifact_dir: Path, name: str) -> None:
    index.add_scan_record(
        artifact_dir,
        _meta(name, tribe="epic"),
        project_name="proj",
        done_data=_completed_done(),
    )


def _add_live_record(index: WaitDependencyIndex, artifact_dir: Path, name: str) -> None:
    _write_agent(artifact_dir.parent, artifact_dir.name, name, tribe="epic")
    index.add(artifact_dir, _meta(name, tribe="epic"), project_name="proj")


def _add_many_record(index: WaitDependencyIndex, artifact_dir: Path, name: str) -> None:
    _write_agent(artifact_dir.parent, artifact_dir.name, name, tribe="epic")
    index.add_many(((artifact_dir, _meta(name, tribe="epic"), "proj"),))


@pytest.mark.parametrize(
    "mutate",
    [_add_scan_record, _add_live_record, _add_many_record],
)
def test_query_caches_invalidate_after_index_mutation(
    tmp_path: Path,
    mutate: Callable[[WaitDependencyIndex, Path, str], None],
) -> None:
    index = WaitDependencyIndex.empty()
    first_dir = tmp_path / "20260909010101"
    second_dir = tmp_path / "20260909020202"
    _add_scan_record(index, first_dir, "first")

    assert index._excluded_member_name(first_dir) == "first"
    assert index.tribe_candidate("epic", newer_than="20260909000000").name == "first"

    mutate(index, second_dir, "second")

    assert index._excluded_member_name(second_dir) == "second"
    candidate = index.tribe_candidate("epic", newer_than="20260909010101")
    assert candidate is not None
    assert candidate.name == "second"


def test_resolved_dir_key_reverse_map_preserves_first_match_semantics(
    tmp_path: Path,
) -> None:
    real_dir = tmp_path / "20260909010101"
    alias_dir = tmp_path / "20260909020202"
    real_dir.mkdir()
    alias_dir.symlink_to(real_dir, target_is_directory=True)

    index = WaitDependencyIndex.empty()
    _add_scan_record(index, real_dir, "real")
    _add_scan_record(index, alias_dir, "alias")

    assert index._excluded_member_name(alias_dir) == "real"
    candidate = index.tribe_candidate(
        "epic",
        newer_than="20260909000000",
        exclude_artifact_dir=alias_dir,
    )
    assert candidate is not None
    assert candidate.name == "alias"


def test_dir_key_resolution_does_not_scale_with_waiters_times_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_count = 300
    waiter_count = 40
    index = WaitDependencyIndex.empty()
    dependency_dirs: list[Path] = []
    waiter_dirs: list[Path] = []

    for number in range(artifact_count):
        artifact_dir = tmp_path / f"20260908{number:06d}"
        dependency_dirs.append(artifact_dir)
        index.add_scan_record(
            artifact_dir,
            _meta(f"target-{number}", family="target"),
            project_name="proj",
            done_data=_completed_done(),
        )

    for number in range(waiter_count):
        waiter_dir = tmp_path / f"20260909{number:06d}"
        waiter_dirs.append(waiter_dir)
        index.add_scan_record(
            waiter_dir,
            _meta(f"waiter-{number}"),
            project_name="proj",
            done_data=None,
        )

    original_uncached = _artifact_state._artifact_dir_key_uncached
    uncached_calls: list[str] = []

    def counting_uncached(value: str) -> str:
        uncached_calls.append(value)
        return original_uncached(value)

    _artifact_state.artifact_dir_key.cache_clear()
    monkeypatch.setattr(
        _artifact_state,
        "_artifact_dir_key_uncached",
        counting_uncached,
    )

    try:
        for waiter_dir in waiter_dirs:
            assert index.is_resolved("target", exclude_artifact_dir=waiter_dir)
            assert (
                index.terminal_blocking_artifacts_for_name(
                    "target",
                    exclude_artifact_dir=waiter_dir,
                )
                == ()
            )
    finally:
        _artifact_state.artifact_dir_key.cache_clear()

    distinct_dirs = {str(path) for path in [*dependency_dirs, *waiter_dirs]}
    assert len(uncached_calls) <= len(distinct_dirs)
    assert len(uncached_calls) < artifact_count * waiter_count
