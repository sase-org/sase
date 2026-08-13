"""Tests for the Rust-backed artifact-consumption summary facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.artifact_consumption_query import (
    ArtifactConsumptionSummary,
    summarize_artifact_consumption,
)


def test_summary_checks_schema_and_validates_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_require(name: str) -> Any:
        if name == "artifact_consumption_wire_schema_version":
            return lambda: 1
        if name == "artifact_consumption_summary":

            def summarize(path: str, refs: object) -> dict[str, object]:
                calls.append((path, refs))
                return {
                    "plan:report.md": {
                        "agent_names": ["alpha", "zeta"],
                        "consumption_count": 3,
                        "distinct_agent_count": 2,
                        "first_consumed_at": "2026-07-30T10:00:00Z",
                        "last_consumed_at": "2026-07-30T12:00:00Z",
                        "roles": ["report"],
                    }
                }

            return summarize
        raise AssertionError(name)

    monkeypatch.setattr(
        "sase.core.artifact_consumption_query.require_rust_binding",
        fake_require,
    )
    log_path = tmp_path / ".." / tmp_path.name / "consumption.jsonl"

    summaries = summarize_artifact_consumption(
        ["plan:report.md"],
        log_path=log_path,
    )

    assert summaries == {
        "plan:report.md": ArtifactConsumptionSummary(
            consumption_count=3,
            distinct_agent_count=2,
            agent_names=("alpha", "zeta"),
            roles=("report",),
            first_consumed_at="2026-07-30T10:00:00Z",
            last_consumed_at="2026-07-30T12:00:00Z",
        )
    }
    assert calls == [
        (
            str(log_path.expanduser().resolve(strict=False)),
            ["plan:report.md"],
        )
    ]


def test_summary_rejects_stale_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.artifact_consumption_query.require_rust_binding",
        lambda _name: lambda: 0,
    )

    with pytest.raises(RuntimeError, match="expected 1, got 0"):
        summarize_artifact_consumption()


@pytest.mark.parametrize(
    ("raw_summary", "match"),
    [
        ("not-an-object", "expected an object"),
        (
            {
                "agent_names": ["agent"],
                "consumption_count": True,
                "distinct_agent_count": 1,
                "first_consumed_at": None,
                "last_consumed_at": None,
                "roles": ["report"],
            },
            "consumption_count",
        ),
        (
            {
                "agent_names": [1],
                "consumption_count": 1,
                "distinct_agent_count": 1,
                "first_consumed_at": None,
                "last_consumed_at": None,
                "roles": ["report"],
            },
            "agent_names",
        ),
    ],
)
def test_summary_rejects_incompatible_rows(
    raw_summary: object,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(name: str) -> Any:
        if name == "artifact_consumption_wire_schema_version":
            return lambda: 1
        return lambda *_args: {"plan:report.md": raw_summary}

    monkeypatch.setattr(
        "sase.core.artifact_consumption_query.require_rust_binding",
        fake_require,
    )

    with pytest.raises(RuntimeError, match=match):
        summarize_artifact_consumption()
