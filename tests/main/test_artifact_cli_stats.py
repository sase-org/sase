from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.stats import _TrashOccupancy, handle_stats
from sase.core.artifact_file_economics import (
    ArtifactFileEconomics,
    ArtifactFileEconomicsGroup,
    _ArtifactFileGenerationProjection,
)
from sase.core.artifact_file_protection import ProtectedArtifactIds
from sase.core.artifact_file_retention import (
    _RetentionCounts,
    RetentionPlan,
)
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)


def _economics() -> ArtifactFileEconomics:
    return ArtifactFileEconomics(
        schema_version=1,
        total_rows=4,
        explicit_rows=1,
        automatic_rows=3,
        vcs_backed_rows=1,
        rows_missing_size=0,
        total_bytes=450,
        explicit_bytes=100,
        automatic_bytes=350,
        vcs_backed_bytes=50,
        by_kind=(ArtifactFileEconomicsGroup("image", 2, 300),),
        by_project=(ArtifactFileEconomicsGroup("gh_sase-org__sase", 4, 450),),
        by_agent=(ArtifactFileEconomicsGroup("agent.one", 3, 350),),
        by_agent_truncated_groups=2,
        by_agent_truncated_bytes=100,
        first_created_at="2026-07-01T00:00:00Z",
        last_created_at="2026-07-04T00:00:00Z",
        window_days=4,
        bytes_per_day=112.5,
        rows_per_day=1.0,
        duplicate_digest_groups=1,
        redundant_digest_rows=1,
        redundant_digest_bytes=100,
        distinct_labels=2,
        label_generation_projections=(_ArtifactFileGenerationProjection(3, 1, 100),),
        source_inside_workspace_rows=2,
        source_inside_workspace_bytes=300,
    )


def _retention() -> RetentionPlan:
    return RetentionPlan(
        schema_version=1,
        selected=(),
        protected=(),
        counts=_RetentionCounts(
            candidates=3,
            selected=1,
            protected=1,
            byte_backed_selected=1,
            byte_free_selected=0,
        ),
        reclaimable_bytes=100,
        truncated=0,
        summary_lines=("1 selected",),
    )


def _projects() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"}),
        aliases={"ss": "gh_sase-org__sase"},
    )


def test_stats_json_has_stable_envelope_and_builds_default_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: dict[str, object] = {}
    referenced_only = "default:111111111111111111111111"
    overlap = "default:222222222222222222222222"
    consumed_only = "explicit:333333333333333333333333"
    protections = ProtectedArtifactIds(
        referenced_ids=frozenset({referenced_only, overlap}),
        consumed_ids=frozenset({overlap, consumed_only}),
        sources_scanned=("/plans", "/beads"),
        sources_unavailable=("/missing",),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.load_project_ref_display_snapshot",
        _projects,
    )

    def economics(**kwargs: object) -> ArtifactFileEconomics:
        calls["economics"] = kwargs
        return _economics()

    def retention(policy):  # type: ignore[no-untyped-def]
        calls["policy"] = policy
        return _retention()

    monkeypatch.setattr(
        "sase.artifact_cli.stats.artifact_file_store_economics",
        economics,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.collect_protected_artifact_ids",
        lambda: protections,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.plan_artifact_file_retention",
        retention,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats._trash_occupancy",
        lambda: _TrashOccupancy(2, 25, 1),
    )

    assert handle_stats(argparse.Namespace(json=True, project="ss", top=7)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == [
        "schema_version",
        "economics",
        "protections",
        "trash",
        "default_policy",
    ]
    assert payload["schema_version"] == 1
    assert payload["economics"]["total_rows"] == 4
    assert payload["protections"] == {
        "explicit_rows": 1,
        "referenced_ids": 2,
        "consumed_ids": 2,
        "overlap_ids": 1,
        "total_ids": 3,
        "ids": [referenced_only, overlap, consumed_only],
        "sources_scanned": ["/plans", "/beads"],
        "sources_unavailable": ["/missing"],
    }
    assert payload["trash"] == {
        "entries": 2,
        "bytes": 25,
        "unreadable_entries": 1,
    }
    assert payload["default_policy"]["keep_per_label"] == 3
    assert payload["default_policy"]["max_age_days"] == 90
    assert payload["default_policy"]["plan"]["counts"]["selected"] == 1
    assert calls["economics"] == {
        "project": "gh_sase-org__sase",
        "top_n": 7,
    }
    policy = calls["policy"]
    assert policy.project == "gh_sase-org__sase"  # type: ignore[union-attr]
    assert policy.before == "90d"  # type: ignore[union-attr]
    assert policy.protected_ids == protections.ids  # type: ignore[union-attr]


def test_stats_pretty_report_has_every_section_and_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.stats.load_project_ref_display_snapshot",
        _projects,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.artifact_file_store_economics",
        lambda **_kwargs: _economics(),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=("sase:beads",),
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.plan_artifact_file_retention",
        lambda _policy: _retention(),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats._trash_occupancy",
        lambda: _TrashOccupancy(0, 0, 0),
    )

    assert handle_stats(argparse.Namespace(json=False, project=None, top=10)) == 0

    output = capsys.readouterr().out
    for title in (
        "Artifact Store Totals",
        "Window and Observed Growth",
        "By Kind",
        "By Project",
        "Top Agents",
        "Redundancy and Projections",
        "Protections",
        "Trash Occupancy",
        "What the Default Policy Would Select",
    ):
        assert title in output
    assert "Referenced ids" in output
    assert "Consumed ids" in output
    assert "Overlap ids" in output
    assert "Total protected ids" in output
    assert "sase:beads" in output
    assert "sase" in output


def test_stats_unknown_project_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.stats.load_project_ref_display_snapshot",
        _projects,
    )

    assert handle_stats(argparse.Namespace(json=False, project="unknown", top=10)) == 2
    assert "unknown project reference" in capsys.readouterr().err


def test_stats_with_empty_store_never_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(
        "sase.artifact_cli.stats.load_project_ref_display_snapshot",
        _projects,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.stats.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )

    assert handle_stats(argparse.Namespace(json=True, project=None, top=10)) == 0

    assert not home.exists()
    assert json.loads(capsys.readouterr().out)["economics"]["total_rows"] == 0
