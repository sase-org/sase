"""Off-thread compute coverage for bead warmup confirmation displays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.models.agent_bead import (
    _BEAD_DISPLAY_CACHE,
    _bead_display_cache_key,
    agent_has_confirmed_bead,
    warm_confirmed_bead_displays,
)
from sase.bead.model import Issue
from tests.ace.tui._agents_bead_warmup_helpers import (
    clear_bead_display_cache,
    confirmed_lookup,
    make_agent,
)

pytestmark = pytest.mark.usefixtures("clear_bead_display_cache")

__all__ = [
    "test_warm_confirmed_bead_displays_clears_fingerprint_with_entries",
    "test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key",
    "test_warm_confirmed_bead_displays_missing_fingerprint_fails_open",
    "test_warm_confirmed_bead_displays_omits_missing_and_non_candidates",
    "test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation",
    "test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate",
    "test_warm_confirmed_bead_displays_reports_deleted_when_store_changes",
    "test_warm_confirmed_bead_displays_rereads_missing_when_store_changes",
    "test_warm_confirmed_bead_displays_rereads_when_store_changes",
    "test_warm_confirmed_bead_displays_reuses_store_for_batch",
    "test_warm_confirmed_bead_displays_reuses_unchanged_store_across_ttl",
    "test_warm_confirmed_bead_displays_reuses_unchanged_store_for_missing",
    "test_warm_confirmed_bead_displays_skips_unrelated_lineage_changes",
    "test_warm_confirmed_bead_displays_unknown_fingerprint_fails_open",
]


def test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        calls.append(candidate_id)
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)

    # a1 and a2 share a candidate + project + workspace, so one cache key; a3 is
    # a distinct candidate. Two unique keys → two bead-store lookups total.
    a1 = make_agent(agent_name="sase-x.3", cl_name="a1", raw_suffix="1")
    a2 = make_agent(agent_name="sase-x.3", cl_name="a2", raw_suffix="2")
    a3 = make_agent(agent_name="sase-y.4", cl_name="a3", raw_suffix="3")

    results = warm_confirmed_bead_displays([a1, a2, a3])

    assert calls == ["sase-x.3", "sase-y.4"]
    assert results == {a1.identity: True, a2.identity: True, a3.identity: True}


def test_warm_confirmed_bead_displays_omits_missing_and_non_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    missing = make_agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    ordinary = make_agent(agent_name="reviewer", cl_name="ordinary", raw_suffix="2")

    results = warm_confirmed_bead_displays([missing, ordinary])

    assert results == {}


def test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3", cl_name="deleted", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale description")
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    results = warm_confirmed_bead_displays([agent])

    assert results == {agent.identity: False}
    assert agent_has_confirmed_bead(agent) is False


def test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3", cl_name="same", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)

    results = warm_confirmed_bead_displays([agent])

    assert results == {}
    assert agent_has_confirmed_bead(agent) is True


def _issue_payload(issue_id: str, title: str) -> dict[str, object]:
    timestamp = "2026-07-12T00:00:00Z"
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": timestamp,
        "created_by": "",
        "updated_at": timestamp,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "patch_name": "",
        "patch_bug_id": "",
        "dependencies": [],
    }


def test_warm_confirmed_bead_displays_reuses_store_for_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    beads_dir = workspace / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    issues = [
        _issue_payload("batch-x.3", "First"),
        _issue_payload("batch-y.4", "Second"),
    ]
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(issue) + "\n" for issue in issues),
        encoding="utf-8",
    )

    from sase.bead import project as project_module

    real_bead_project = project_module.BeadProject
    constructions: list[Path] = []

    def counting_bead_project(
        root_dir: str | Path,
        beads_dirname: str = "sdd/beads",
    ) -> Any:
        constructions.append(Path(root_dir) / beads_dirname)
        return real_bead_project(root_dir, beads_dirname=beads_dirname)

    monkeypatch.setattr(project_module, "BeadProject", counting_bead_project)
    first = make_agent(
        agent_name="batch-x.3",
        cl_name="first",
        raw_suffix="1",
        project_file="",
        workspace_dir=str(workspace),
    )
    second = make_agent(
        agent_name="batch-y.4",
        cl_name="second",
        raw_suffix="2",
        project_file="",
        workspace_dir=str(workspace),
    )

    results = warm_confirmed_bead_displays([first, second])

    assert results == {first.identity: True, second.identity: True}
    assert constructions == [beads_dir]


def test_warm_confirmed_bead_displays_skips_unrelated_lineage_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _BEAD_DISPLAY_CACHE.clear()
    beads_dir = tmp_path / "beads"
    streams_dir = beads_dir / "events" / "streams"
    streams_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n", encoding="utf-8")
    (beads_dir / "events" / "manifest.json").write_text(
        '{"schema_version":1,"stream_count":2}\n', encoding="utf-8"
    )
    (streams_dir / "sase-x.jsonl").write_text("candidate event\n", encoding="utf-8")
    unrelated_stream = streams_dir / "other.jsonl"
    unrelated_stream.write_text("unrelated event\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    agent = make_agent(
        agent_name="sase-x.3",
        cl_name="fingerprint-gate",
        raw_suffix="1",
        project_file=str(tmp_path / "project" / "project.yml"),
    )
    lookups: list[str] = []

    def lookup_issue(_session: object, bead_id: str, _dirs: object) -> Issue:
        lookups.append(bead_id)
        return Issue(id=bead_id, title="Issue", description="")

    monkeypatch.setattr(
        "sase.agent.bead_display.BeadIssueLookupSession.lookup", lookup_issue
    )
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: True}
    cached = _BEAD_DISPLAY_CACHE.get(key)
    assert isinstance(cached, str)
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, cached)
    unrelated_stream.write_text(
        "unrelated stream changed without touching candidate lineage\n",
        encoding="utf-8",
    )

    assert warm_confirmed_bead_displays([agent]) == {}
    assert lookups == ["sase-x.3"]
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is False
    _BEAD_DISPLAY_CACHE.clear()


def test_warm_confirmed_bead_displays_reuses_unchanged_store_across_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        nonlocal calls
        calls += 1
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="reuse", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: True}
    assert calls == 1
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is False

    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is True

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 1
    assert agent_has_confirmed_bead(agent) is True
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is False


def test_warm_confirmed_bead_displays_rereads_when_store_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["tok-1"]
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_bead._bead_display_fingerprint",
        lambda _agent: tokens[0],
    )
    calls = 0

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        nonlocal calls
        calls += 1
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="changed", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: True}
    assert calls == 1

    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    tokens[0] = "tok-2"

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 2
    assert agent_has_confirmed_bead(agent) is True


def test_warm_confirmed_bead_displays_reuses_unchanged_store_for_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def missing_lookup(candidate_id: str, **_: object) -> None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", missing_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 1
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is False

    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, None)
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is True

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 1
    assert _BEAD_DISPLAY_CACHE.should_resolve(key) is False
    assert agent_has_confirmed_bead(agent) is False


def test_warm_confirmed_bead_displays_rereads_missing_when_store_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["tok-1"]
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_bead._bead_display_fingerprint",
        lambda _agent: tokens[0],
    )
    calls = 0

    def missing_lookup(candidate_id: str, **_: object) -> None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", missing_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 1

    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, None)
    tokens[0] = "tok-2"

    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 2


def test_warm_confirmed_bead_displays_missing_fingerprint_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_bead._bead_display_fingerprint",
        lambda _agent: None,
    )
    calls = 0

    def missing_lookup(candidate_id: str, **_: object) -> None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", missing_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {}
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, None)
    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 2


def test_warm_confirmed_bead_displays_reports_deleted_when_store_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["tok-1"]
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_bead._bead_display_fingerprint",
        lambda _agent: tokens[0],
    )
    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="deleted", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: True}

    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale")
    tokens[0] = "tok-2"
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: False}
    assert agent_has_confirmed_bead(agent) is False


def test_warm_confirmed_bead_displays_unknown_fingerprint_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_bead._bead_display_fingerprint",
        lambda _agent: None,
    )
    calls = 0

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        nonlocal calls
        calls += 1
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)
    agent = make_agent(agent_name="sase-x.3", cl_name="unknown", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None

    assert warm_confirmed_bead_displays([agent]) == {agent.identity: True}
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    assert warm_confirmed_bead_displays([agent]) == {}
    assert calls == 2


def test_warm_confirmed_bead_displays_clears_fingerprint_with_entries() -> None:
    agent = make_agent(agent_name="sase-x.3", cl_name="cleanup", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE.set(key, "sase-x.3")
    _BEAD_DISPLAY_CACHE.set_fingerprint(key, "tok-1")
    assert _BEAD_DISPLAY_CACHE.fingerprint_for(key) == "tok-1"
    _BEAD_DISPLAY_CACHE.clear()
    assert _BEAD_DISPLAY_CACHE.fingerprint_for(key) is None
