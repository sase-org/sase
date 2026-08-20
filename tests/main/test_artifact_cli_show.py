"""Tests for ``sase artifact show``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.show import handle_show
from sase.core.artifact_consumption_query import ArtifactConsumptionSummary
from tests.main.artifact_cli_reference_helpers import (
    ARTIFACT_DIGEST,
    artifact_file,
    resolved_reference,
)


def test_show_json_uses_common_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "doc.md"
    result = resolved_reference(path, reference="plan:doc.md#L3")
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_show(argparse.Namespace(reference="plan:doc.md#L3", json=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == [
        "reference",
        "kind",
        "fragment",
        "file",
        "resolution",
        "consumption",
        "links",
        "entry",
    ]
    assert payload["links"] == []
    assert payload["reference"] == "plan:doc.md#L3"
    assert payload["kind"] == "plan"
    assert payload["consumption"] is None
    assert payload["fragment"]["start"] == 3
    assert payload["resolution"]["status"] == "exact"


def test_show_file_pretty_reports_every_field_and_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = tmp_path / "stored.txt"
    stored.write_text("live", encoding="utf-8")
    missing_source = tmp_path / "missing-source.txt"
    file = artifact_file(stored, source_path=str(missing_source))
    result = resolved_reference(
        stored,
        reference=f"file:explicit:{ARTIFACT_DIGEST}",
        file=file,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_show(argparse.Namespace(reference=result.input, json=False)) == 0

    output = capsys.readouterr().out
    for field in vars(file):
        assert field in output
    assert f"file:explicit:{ARTIFACT_DIGEST}" in output
    assert "stored_path_status" in output
    assert "source_path_status" in output
    assert "live" in output
    assert "missing" in output


def test_show_reports_consumption_in_pretty_and_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = resolved_reference(tmp_path / "report.md", reference="plan:report.md")
    summary = ArtifactConsumptionSummary(
        consumption_count=7,
        distinct_agent_count=6,
        agent_names=("alpha", "beta", "delta", "epsilon", "gamma", "zeta"),
        roles=("report",),
        first_consumed_at="2026-07-30T10:00:00Z",
        last_consumed_at="2026-07-30T12:00:00Z",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )
    calls: list[list[str]] = []

    def summarize(refs: list[str]) -> dict[str, ArtifactConsumptionSummary]:
        calls.append(refs)
        return {result.canonical_reference: summary}

    monkeypatch.setattr(
        "sase.artifact_cli.show.summarize_artifact_consumption",
        summarize,
    )

    assert handle_show(argparse.Namespace(reference=result.input, json=False)) == 0
    pretty = capsys.readouterr().out
    assert "consumption_count" in pretty
    assert "7" in pretty
    assert "consumed_by_agents" in pretty
    assert "6" in pretty
    assert "alpha, beta, delta, epsilon, gamma +1 more" in pretty
    assert "2026-07-30T12:00:00Z" in pretty

    assert handle_show(argparse.Namespace(reference=result.input, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["consumption"] == {
        "consumption_count": 7,
        "distinct_agent_count": 6,
        "agent_names": ["alpha", "beta", "delta", "epsilon", "gamma", "zeta"],
        "roles": ["report"],
        "first_consumed_at": "2026-07-30T10:00:00Z",
        "last_consumed_at": "2026-07-30T12:00:00Z",
    }
    assert calls == [
        ["plan:report.md"],
        ["plan:report.md"],
    ]


def test_show_joins_fragment_reference_to_fragment_free_consumption_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = resolved_reference(
        tmp_path / "report.md",
        reference="plan:report.md#L3",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )

    def summarize(refs: list[str]) -> dict[str, ArtifactConsumptionSummary]:
        calls.append(refs)
        return {}

    monkeypatch.setattr(
        "sase.artifact_cli.show.summarize_artifact_consumption",
        summarize,
    )

    assert handle_show(argparse.Namespace(reference=result.input, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["consumption"] is None
    assert calls == [["plan:report.md"]]


def test_show_json_includes_links_when_flag_is_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.feature_flags import override_flags

    result = resolved_reference(tmp_path / "report.md", reference="plan:report.md")
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.show.summarize_artifact_consumption",
        lambda _refs: {},
    )
    monkeypatch.setattr(
        "sase.artifact_cli.show._load_links",
        lambda _reference: [
            {
                "relation": "implements",
                "source_ref": "plan:report.md",
                "target_ref": "bead:sase-js",
            }
        ],
    )
    with override_flags(artifact_links=True):
        assert handle_show(argparse.Namespace(reference=result.input, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["links"][0]["target_ref"] == "bead:sase-js"
