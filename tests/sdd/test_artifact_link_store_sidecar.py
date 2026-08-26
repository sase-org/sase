"""Sidecar index edge cases for the artifact link store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests.sdd._artifact_link_store_helpers import _plan_index, _store


def test_schema_v1_sidecar_file_is_unsupported_after_graduation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    index_path = _plan_index(tmp_path, "monitor_followup_wait_release.md")
    index_path.parent.mkdir(parents=True)
    live = (
        Path(__file__).parent
        / "fixtures"
        / "referenced_by_v1"
        / ("live_monitor_followup_wait_release.json")
    )
    index_path.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="schema-v1 Referenced By"):
        store.load_artifact_rows("plan:202608/monitor_followup_wait_release.md")
    assert json.loads(index_path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_missing_sidecar_root_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": tmp_path / "missing-plans"},
    )
    assert store.load_artifact_rows("plan:202608/a.md") == ()


def test_malformed_sidecar_index_is_fail_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    index_path = _plan_index(tmp_path, "a.md")
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises((json.JSONDecodeError, RuntimeError)):
        store.load_artifact_rows("plan:202608/a.md")
