from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
from pathlib import Path

import pytest

from sase.artifact_cli import link_suggest as link_suggest_module
from sase.artifact_cli.link_suggest import _ArtifactLinkSuggestion
from sase.artifact_cli.link_suggest import _suggest_artifact_links
from sase.artifact_cli.link_suggest import handle_link_suggest
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from sase.artifact_read_log import append_artifact_read_event
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.artifact_link_store import artifact_link_aggregate_path
from tests._conftest_environment import redirect_sase_home


_PROJECT = "gh_sase-org__sase"


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    research = tmp_path / "research"
    research.mkdir()
    return ArtifactLinkStore(
        project_key=_PROJECT,
        sidecar_roots={"research": research},
    )


def _event(
    *,
    ref: str,
    agent_name: str,
    reason: str,
    timestamp: str,
) -> ArtifactReadEvent:
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=f"{agent_name}-{ref}-{timestamp}",
        timestamp=timestamp,
        project=_PROJECT,
        cwd="/tmp/proj",
        ref=ref,
        reason=reason,
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        recorded_link=False,
    )


def _keys(
    suggestions: Iterable[_ArtifactLinkSuggestion],
) -> set[tuple[str, str, str]]:
    return {
        (suggestion.source_ref, suggestion.relation, suggestion.target_ref)
        for suggestion in suggestions
    }


def test_suggest_reports_read_log_and_overlapping_read_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    append_artifact_read_event(
        _event(
            ref="plan:202608/a.md",
            agent_name="alice.athena.worker",
            reason="need plan a",
            timestamp="2026-08-01T00:00:00Z",
        )
    )
    append_artifact_read_event(
        _event(
            ref="plan:202608/b.md",
            agent_name="alice.athena.worker",
            reason="compare adjacent plan",
            timestamp="2026-08-01T01:00:00Z",
        )
    )

    suggestions = _suggest_artifact_links(store, limit=0)

    keys = _keys(suggestions)
    assert ("agent:alice.athena.worker", "read", "plan:202608/a.md") in keys
    assert ("agent:alice.athena.worker", "read", "plan:202608/b.md") in keys
    assert ("plan:202608/a.md", "related", "plan:202608/b.md") in keys
    overlap = next(
        suggestion
        for suggestion in suggestions
        if suggestion.signal == "overlapping-reads"
    )
    assert "alice.athena.worker read both" in overlap.evidence[0]


def test_suggest_excludes_existing_related_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    append_artifact_read_event(
        _event(
            ref="plan:202608/a.md",
            agent_name="alice.athena.worker",
            reason="need plan a",
            timestamp="2026-08-01T00:00:00Z",
        )
    )
    append_artifact_read_event(
        _event(
            ref="plan:202608/b.md",
            agent_name="alice.athena.worker",
            reason="need plan b",
            timestamp="2026-08-01T01:00:00Z",
        )
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "plan:202608/b.md",
            "relation": "related",
            "target_ref": "plan:202608/a.md",
            "description": "already connected",
            "origin": "manual",
            "created_by": "tester",
            "created_at": "2026-08-01T02:00:00Z",
            "uses": 1,
        }
    )

    suggestions = _suggest_artifact_links(store, limit=0)

    assert ("plan:202608/a.md", "related", "plan:202608/b.md") not in _keys(suggestions)


def test_suggest_reports_filename_lineage_without_writing_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    month = tmp_path / "research" / "202608" / "widget"
    month.mkdir(parents=True)
    (month / "widget.md").write_text("# lead\n", encoding="utf-8")
    (month / "widget__a.md").write_text("# source\n", encoding="utf-8")
    aggregate = artifact_link_aggregate_path(_PROJECT)
    assert not aggregate.exists()

    suggestions = _suggest_artifact_links(store, limit=0)

    assert (
        "research:202608/widget/widget.md",
        "derives-from",
        "research:202608/widget/widget__a.md",
    ) in _keys(suggestions)
    assert not aggregate.exists()


def test_handle_link_suggest_json_prints_stable_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        link_suggest_module, "resolve_artifact_link_store", lambda: store
    )
    append_artifact_read_event(
        _event(
            ref="plan:202608/a.md",
            agent_name="alice.athena.worker",
            reason="need plan a",
            timestamp="2026-08-01T00:00:00Z",
        )
    )

    exit_code = handle_link_suggest(
        argparse.Namespace(reference=None, json=True, limit=50)
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["source_ref"] == "agent:alice.athena.worker"
    assert payload[0]["relation"] == "read"
