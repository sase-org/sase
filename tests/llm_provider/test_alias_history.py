"""Tests for the frontend-neutral alias-history adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_alias_history_wire import (
    AgentAliasHistoryGroupWire,
    AgentAliasHistoryLimitWire,
    AgentAliasHistoryQueryWire,
    AgentAliasHistoryWire,
    AgentAliasRunWire,
)
from sase.core.agent_scan_wire_markers import UsedXPromptWire
from sase.llm_provider.alias_history import (
    _alias_history_duration_seconds,
    _classify_alias_history_provenance,
    _classify_alias_history_status,
    load_alias_history,
)
from sase.llm_provider.launch_selection import (
    ALIAS_ORIGIN_DEFAULT_MODEL,
    ALIAS_ORIGIN_DIRECTIVE,
    ALIAS_ORIGIN_NONE,
)
from sase.project_display_names import ProjectDisplaySnapshot


def _run(**overrides: Any) -> AgentAliasRunWire:
    payload: dict[str, Any] = {
        "artifact_dir": "/tmp/a",
        "project_name": "gh_sase-org__sase",
        "workflow_dir_name": "ace-run",
        "timestamp": "20260816120000",
        "alias_position": 0,
        "status": "done",
        "has_done_marker": True,
        "hidden": False,
    }
    payload.update(overrides)
    return AgentAliasRunWire(**payload)


def _group(
    alias: str,
    runs: list[AgentAliasRunWire],
    *,
    limit: int = 10,
    total_count: int | None = None,
    truncated: bool | None = None,
) -> AgentAliasHistoryGroupWire:
    returned = len(runs)
    recorded = returned if total_count is None else total_count
    return AgentAliasHistoryGroupWire(
        alias=alias,
        runs_limit=AgentAliasHistoryLimitWire(
            limit=limit,
            total_count=recorded,
            returned_count=returned,
            truncated=recorded > returned if truncated is None else truncated,
        ),
        runs=runs,
    )


def _wire(
    groups: list[AgentAliasHistoryGroupWire],
    *,
    query: AgentAliasHistoryQueryWire | None = None,
    index_path: str = "/tmp/agent_artifact_index.sqlite",
) -> AgentAliasHistoryWire:
    return AgentAliasHistoryWire(
        schema_version=1,
        index_path=index_path,
        query=query
        or AgentAliasHistoryQueryWire(aliases=[group.alias for group in groups]),
        groups=groups,
    )


def _snapshot() -> ProjectDisplaySnapshot:
    return ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"})


def test_classify_direct_directive_at_entry() -> None:
    provenance = _classify_alias_history_provenance(
        0,
        ALIAS_ORIGIN_DIRECTIVE,
        ("large",),
    )
    assert provenance.kind == "direct"
    assert provenance.label == "direct"
    assert provenance.origin == ALIAS_ORIGIN_DIRECTIVE
    assert provenance.via_alias is None


def test_classify_default_origin_at_entry() -> None:
    provenance = _classify_alias_history_provenance(
        0,
        ALIAS_ORIGIN_DEFAULT_MODEL,
        ("large",),
    )
    assert provenance.kind == "default"
    assert provenance.label == "default"
    assert provenance.origin == ALIAS_ORIGIN_DEFAULT_MODEL


def test_classify_indirect_uses_previous_trail_hop() -> None:
    provenance = _classify_alias_history_provenance(
        1,
        ALIAS_ORIGIN_DIRECTIVE,
        ("coder", "large"),
    )
    assert provenance.kind == "indirect"
    assert provenance.label == "via @coder"
    assert provenance.via_alias == "coder"
    assert provenance.origin == ALIAS_ORIGIN_DIRECTIVE


def test_classify_indirect_regardless_of_origin() -> None:
    provenance = _classify_alias_history_provenance(2, None, ("a", "b", "c"))
    assert provenance.kind == "indirect"
    assert provenance.label == "via @b"
    assert provenance.via_alias == "b"
    assert provenance.origin is None


def test_classify_unrecorded_when_origin_missing() -> None:
    provenance = _classify_alias_history_provenance(0, None, ("large",))
    assert provenance.kind == "unrecorded"
    assert provenance.label == "unrecorded"
    assert provenance.origin is None


@pytest.mark.parametrize("origin", [ALIAS_ORIGIN_NONE, "wizard", "  ", ""])
def test_classify_unknown_or_none_origin_is_unrecorded(origin: str) -> None:
    provenance = _classify_alias_history_provenance(0, origin, ("large",))
    assert provenance.kind == "unrecorded"
    assert provenance.label == "unrecorded"
    if origin.strip() and origin.strip() != ALIAS_ORIGIN_NONE:
        assert provenance.origin == origin.strip()


def test_classify_unknown_future_origin_does_not_raise() -> None:
    provenance = _classify_alias_history_provenance(0, "future_origin_v2")
    assert provenance.kind == "unrecorded"
    assert provenance.origin == "future_origin_v2"


def test_classify_status_buckets() -> None:
    assert _classify_alias_history_status("done", has_done_marker=True) == "done"
    assert _classify_alias_history_status("completed") == "done"
    assert _classify_alias_history_status("failed") == "failed"
    assert _classify_alias_history_status("running") == "running"
    assert _classify_alias_history_status("starting") == "running"
    assert _classify_alias_history_status("waiting") == "running"
    assert (
        _classify_alias_history_status(
            "running",
            workflow_status="failed",
        )
        == "failed"
    )


def test_duration_from_started_and_finished() -> None:
    finished_at = 1_786_892_400.0  # 2026-08-16T15:00:00Z
    assert (
        _alias_history_duration_seconds("2026-08-16T14:22:00+00:00", finished_at)
        == 2280.0
    )
    assert _alias_history_duration_seconds(None, finished_at) is None
    assert _alias_history_duration_seconds("2026-08-16T14:22:00+00:00", None) is None
    assert _alias_history_duration_seconds("not-a-time", finished_at) is None
    assert (
        _alias_history_duration_seconds("2026-08-16T15:00:00+00:00", 1_786_890_120.0)
        is None
    )


def test_load_maps_display_names_and_unknown_project_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_query(
        index_path: Path | str,
        query: AgentAliasHistoryQueryWire,
    ) -> AgentAliasHistoryWire:
        captured["index_path"] = str(index_path)
        captured["query"] = query
        return _wire(
            [
                _group(
                    "large",
                    [
                        _run(),
                        _run(
                            artifact_dir="/tmp/b",
                            project_name="unknown_proj",
                            timestamp="20260816110000",
                        ),
                    ],
                )
            ],
            query=query,
        )

    monkeypatch.setattr(
        "sase.llm_provider.alias_history.query_agent_alias_history",
        fake_query,
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_history.get_model_alias_history_limit",
        lambda: 10,
    )

    index = tmp_path / "agent_artifact_index.sqlite"
    view = load_alias_history(
        ["large"],
        index_path=index,
        snapshot=_snapshot(),
    )

    assert view.groups[0].runs[0].project_key == "gh_sase-org__sase"
    assert view.groups[0].runs[0].project_name == "sase"
    assert view.groups[0].runs[1].project_key == "unknown_proj"
    assert view.groups[0].runs[1].project_name == "unknown_proj"
    assert captured["index_path"] == str(index)


def test_load_preserves_truncation_and_empty_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_query(
        _index_path: Path | str,
        query: AgentAliasHistoryQueryWire,
    ) -> AgentAliasHistoryWire:
        return _wire(
            [
                _group(
                    "large",
                    [_run(status="done"), _run(status="failed", artifact_dir="/tmp/f")],
                    limit=query.limit_per_alias,
                    total_count=43,
                    truncated=True,
                ),
                _group(
                    "coder",
                    [],
                    limit=query.limit_per_alias,
                    total_count=0,
                    truncated=False,
                ),
            ],
            query=query,
        )

    monkeypatch.setattr(
        "sase.llm_provider.alias_history.query_agent_alias_history",
        fake_query,
    )

    view = load_alias_history(
        ["large", "coder"],
        limit_per_alias=2,
        index_path=tmp_path / "idx.sqlite",
        snapshot=_snapshot(),
    )

    large, coder = view.groups
    assert large.limit == 2
    assert large.total_count == 43
    assert large.returned_count == 2
    assert large.truncated is True
    assert large.status_rollup.done == 1
    assert large.status_rollup.failed == 1
    assert large.status_rollup.running == 0
    assert coder.runs == ()
    assert coder.total_count == 0
    assert coder.truncated is False
    assert coder.status_rollup.total == 0
    assert view.status_rollup.done == 1
    assert view.status_rollup.failed == 1


def test_load_resolves_limit_from_config_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_query(
        _index_path: Path | str,
        query: AgentAliasHistoryQueryWire,
    ) -> AgentAliasHistoryWire:
        captured["query"] = query
        return _wire([_group("large", [], limit=query.limit_per_alias)], query=query)

    monkeypatch.setattr(
        "sase.llm_provider.alias_history.query_agent_alias_history",
        fake_query,
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_history.get_model_alias_history_limit",
        lambda: 7,
    )

    view = load_alias_history(
        "large",
        include_hidden=True,
        projects=["gh_sase-org__sase"],
        freshness="revalidate",
        index_path=tmp_path / "idx.sqlite",
        snapshot=_snapshot(),
    )

    query = captured["query"]
    assert query.aliases == ["large"]
    assert query.limit_per_alias == 7
    assert query.include_hidden is True
    assert query.projects == ["gh_sase-org__sase"]
    assert query.freshness == "revalidate"
    assert view.limit_per_alias == 7
    assert view.include_hidden is True
    assert view.projects == ("gh_sase-org__sase",)
    assert view.freshness == "revalidate"


def test_load_classifies_each_provenance_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_query(
        _index_path: Path | str,
        query: AgentAliasHistoryQueryWire,
    ) -> AgentAliasHistoryWire:
        return _wire(
            [
                _group(
                    "large",
                    [
                        _run(
                            artifact_dir="/tmp/direct",
                            model_alias_origin=ALIAS_ORIGIN_DIRECTIVE,
                            model_alias_trail=["large"],
                            started_at="2026-08-16T14:22:00+00:00",
                            finished_at=1_786_892_400.0,
                            used_xprompts=[
                                UsedXPromptWire(name="gh:sase", kind="reference")
                            ],
                        ),
                        _run(
                            artifact_dir="/tmp/default",
                            alias_position=0,
                            model_alias_origin=ALIAS_ORIGIN_DEFAULT_MODEL,
                            model_alias_trail=["large"],
                        ),
                        _run(
                            artifact_dir="/tmp/via",
                            alias_position=1,
                            model_alias="coder",
                            model_alias_origin=ALIAS_ORIGIN_DIRECTIVE,
                            model_alias_trail=["coder", "large"],
                        ),
                        _run(
                            artifact_dir="/tmp/legacy",
                            model_alias_origin=None,
                            model_alias_trail=["large"],
                        ),
                    ],
                )
            ],
            query=query,
        )

    monkeypatch.setattr(
        "sase.llm_provider.alias_history.query_agent_alias_history",
        fake_query,
    )

    view = load_alias_history(
        ["large"],
        limit_per_alias=10,
        index_path=tmp_path / "idx.sqlite",
        snapshot=_snapshot(),
    )
    labels = [run.provenance.label for run in view.groups[0].runs]
    assert labels == ["direct", "default", "via @coder", "unrecorded"]
    assert view.groups[0].runs[0].duration_seconds == 2280.0
    assert view.groups[0].runs[0].used_xprompts[0].name == "gh:sase"
    assert view.groups[0].runs[2].provenance.via_alias == "coder"


def test_load_rejects_empty_aliases(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="aliases must be a non-empty list"):
        load_alias_history([], index_path=tmp_path / "idx.sqlite")
