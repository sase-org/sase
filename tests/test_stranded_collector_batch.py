"""Parity coverage for the batched stranded-work session query.

``_session_record_cache`` issues one index query per chunk of candidate
sessions instead of one per session. These tests pin that the batched path
returns exactly what the legacy per-assignee ``_query_session_records``
reference returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead import stranded_facts as facts
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _rich_records(tmp_path: Path) -> list[Any]:
    """Records covering roots, shared sessions, cross-key matches, dupes."""
    root_dir = _dir(tmp_path, "root-run")
    shared_a = _dir(tmp_path, "shared-a")
    shared_b = _dir(tmp_path, "shared-b")
    cross_dir = _dir(tmp_path, "cross-run")
    dupe_dir = _dir(tmp_path, "dupe-run")
    foreign_dir = _dir(tmp_path, "foreign-run")
    return [
        # Session root: agent_session null, matched by name only.
        record(root_dir, name="root-key", session=None),
        # Two successors sharing one session.
        record(shared_a, name="name-a", session="shared"),
        record(shared_b, name="name-b", session="shared"),
        # One record whose session is one key and whose name is another.
        record(cross_dir, name="key-b", session="key-a"),
        # Duplicate artifact_dirs: only the first is kept per key.
        record(dupe_dir, name="dupe-first", session="dupe-key"),
        record(dupe_dir, name="dupe-second", session="dupe-key"),
        # Matches no requested key; both paths must drop it.
        record(foreign_dir, name="foreign", session="foreign-session"),
    ]


def _legacy_single_key_query(project: str, key: str) -> AgentArtifactIndexQueryWire:
    """The pre-batch per-assignee query, one key at a time."""
    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        candidate_filter={
            "kind": "any",
            "filters": [
                {"kind": "equals", "field": "agent_session", "value": key},
                {"kind": "equals", "field": "agent_name", "value": key},
            ],
        },
    )


def _legacy_options(project: str) -> AgentArtifactScanOptionsWire:
    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project,),
    )


def _legacy_answers(project: str, keys: set[str]) -> dict[str, tuple[list[str], bool]]:
    """The pre-batch answer: one query per key with the exact recheck."""
    answers: dict[str, tuple[list[str], bool]] = {}
    for key in sorted(keys):
        scan = facts.query_agent_artifact_index(
            facts.default_agent_artifact_index_path(),
            facts.sase_projects_dir(),
            _legacy_single_key_query(project, key),
            _legacy_options(project),
        )
        dirs: list[str] = []
        seen: set[str] = set()
        for item in scan.records:
            if item.artifact_dir in seen:
                continue
            meta = item.agent_meta
            if meta is None:
                continue
            session = (meta.agent_session or "").strip()
            name = (meta.name or "").strip()
            if session == key or name == key:
                seen.add(item.artifact_dir)
                dirs.append(item.artifact_dir)
        answers[key] = (dirs, True)
    return answers


def _batched_answers(project: str, keys: set[str]) -> dict[str, tuple[list[str], bool]]:
    return {
        key: (
            [item.artifact_dir for item in records],
            available,
        )
        for key, (records, available) in facts._session_record_cache(
            project, keys
        ).items()
    }


def test_batched_cache_matches_legacy_per_assignee(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="key-a")],
        _rich_records(tmp_path),
    )
    keys = {"root-key", "shared", "name-a", "name-b", "key-a", "key-b", "dupe-key"}
    assert _batched_answers(PROJECT, keys) == _legacy_answers(PROJECT, keys)


def test_cross_key_record_reaches_every_matching_key(
    monkeypatch, tmp_path: Path
) -> None:
    cross_dir = tmp_path / "artifacts" / "cross-run"
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="key-a")],
        _rich_records(tmp_path),
    )
    cache = facts._session_record_cache(PROJECT, {"key-a", "key-b"})
    assert str(cross_dir) in [item.artifact_dir for item in cache["key-a"][0]]
    assert str(cross_dir) in [item.artifact_dir for item in cache["key-b"][0]]
    assert cache["key-a"][1] is True
    assert cache["key-b"][1] is True


def test_duplicate_artifact_dirs_keep_first_per_key(
    monkeypatch, tmp_path: Path
) -> None:
    dupe_dir = tmp_path / "artifacts" / "dupe-run"
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="dupe-key")],
        _rich_records(tmp_path),
    )
    cache = facts._session_record_cache(PROJECT, {"dupe-key"})
    dirs = [item.artifact_dir for item in cache["dupe-key"][0]]
    assert dirs.count(str(dupe_dir)) == 1
    assert cache["dupe-key"][0][0].agent_meta.name == "dupe-first"


def test_single_batched_query_carries_every_key(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="key-a")],
        _rich_records(tmp_path),
    )
    captured: list[Any] = []
    original = facts.query_agent_artifact_index

    def query(
        index_path: Path,
        projects_root: Path,
        index_query: Any,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        captured.append((index_query, options))
        return original(index_path, projects_root, index_query, options)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    keys = {"key-a", "key-b", "shared"}
    facts._session_record_cache(PROJECT, keys)
    assert len(captured) == 1
    index_query, options = captured[0]
    values = sorted(item["value"] for item in index_query.candidate_filter["filters"])
    assert values == sorted(
        [key for key in keys for _ in ("agent_session", "agent_name")]
    )
    fields = {
        (item["field"], item["value"])
        for item in index_query.candidate_filter["filters"]
    }
    for key in keys:
        assert ("agent_session", key) in fields
        assert ("agent_name", key) in fields
    assert options.only_projects == (PROJECT,)
    assert index_query.include_full_history is True
    assert index_query.include_hidden is True


def test_more_than_100_keys_uses_multiple_chunks(monkeypatch, tmp_path: Path) -> None:
    keys = [f"key-{index:03d}" for index in range(250)]
    records = [
        record(_dir(tmp_path, f"run-{key}"), name=key, session=key) for key in keys
    ]
    wire_collector(monkeypatch, tmp_path, [], records)
    calls = 0
    original = facts.query_agent_artifact_index

    def query(
        index_path: Path,
        projects_root: Path,
        index_query: Any,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        return original(index_path, projects_root, index_query, options)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    cache = facts._session_record_cache(PROJECT, set(keys))
    assert calls == 3
    assert set(cache) == set(keys)
    assert all(available for _, available in cache.values())
    for key in keys:
        dirs = [item.artifact_dir for item in cache[key][0]]
        assert dirs == [str(tmp_path / "artifacts" / f"run-{key}")]


def test_failing_chunk_marks_only_its_keys_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(facts, "_BATCH_CHUNK_SIZE", 2)
    good_c_dir = _dir(tmp_path, "good-c")
    good_d_dir = _dir(tmp_path, "good-d")
    records = [
        record(good_c_dir, name="good-c", session="good-c"),
        record(good_d_dir, name="good-d", session="good-d"),
    ]
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="good-c")],
        records,
    )
    original = facts.query_agent_artifact_index

    def query(
        index_path: Path,
        projects_root: Path,
        index_query: Any,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        values = {item["value"] for item in index_query.candidate_filter["filters"]}
        if values & {"bad-a", "bad-b"}:
            raise OSError("index busy")
        return original(index_path, projects_root, index_query, options)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    # Sorted: bad-a, bad-b, good-c, good-d -> chunks [bad-a, bad-b], [good-c, good-d].
    cache = facts._session_record_cache(PROJECT, {"good-d", "good-c", "bad-b", "bad-a"})
    assert cache["bad-a"] == ([], False)
    assert cache["bad-b"] == ([], False)
    assert cache["good-c"][1] is True
    assert cache["good-d"][1] is True
    assert [item.artifact_dir for item in cache["good-c"][0]] == [str(good_c_dir)]


def test_missing_index_file_marks_every_key_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="key-a")],
        _rich_records(tmp_path),
    )
    monkeypatch.setattr(
        facts,
        "default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    calls = 0
    original = facts.query_agent_artifact_index

    def query(*args: Any, **kwargs: Any) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    cache = facts._session_record_cache(PROJECT, {"key-a", "key-b"})
    assert cache == {"key-a": ([], False), "key-b": ([], False)}
    assert calls == 0


def test_collector_end_to_end_uses_batched_query(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2")],
    )
    calls = 0
    original = facts.query_agent_artifact_index

    def query(
        index_path: Path,
        projects_root: Path,
        index_query: Any,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        return original(index_path, projects_root, index_query, options)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    assert calls == 1
    bead = bead_facts(payload, "sase-1.2")
    assert [member["name"] for member in bead["members"]] == ["sase-1.2"]
