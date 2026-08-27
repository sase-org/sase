"""Provider discovery must degrade visibly instead of dropping tabs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.ace.tui._artifact_tab_descriptors import provider_descriptors
from sase.ace.tui._artifact_tab_model import (
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
)
from sase.ace.tui.artifact_tabs import (
    ARTIFACTS_ACCENTS,
    artifacts_provider_diagnostics,
    reset_artifacts_subtabs_cache,
    resolve_artifacts_subtabs,
)
from sase.sidecar_ref_config import SidecarRefPolicy


def test_missing_ref_provider_creates_degraded_tab() -> None:
    descriptors = provider_descriptors(
        [],
        (
            ProviderDiscoveryIssue(
                message=(
                    "artifact ref provider 'research-docs' is not installed; "
                    "a cloned sidecar repo does not install a provider plugin"
                ),
                code="missing_ref_provider",
                kind="research",
                role="research",
                source="/tmp/proj/.sase.yml",
            ),
        ),
    )

    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor.id == "ref:research"
    assert descriptor.is_degraded
    assert descriptor.error_code == "missing_ref_provider"
    assert descriptor.error_source == "/tmp/proj/.sase.yml"
    assert "research-docs" in (descriptor.error or "")


def test_missing_ref_provider_is_listed_in_ace_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptors = provider_descriptors(
        [],
        (
            ProviderDiscoveryIssue(
                message="artifact ref provider 'research-docs' is not installed",
                code="missing_ref_provider",
                kind="research",
                role="research",
                source="/tmp/proj/.sase.yml",
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs",
        lambda: descriptors,
    )
    assert artifacts_provider_diagnostics() == (
        ("ref:research", "missing_ref_provider", descriptors[0].error or ""),
    )


def test_healthy_kind_is_not_removed_by_a_sibling_failure() -> None:
    healthy = ProjectProviderRecord(
        project="proj",
        display_name="Proj",
        workspace_dir="/tmp/proj",
        role="plans",
        root=Path("/tmp/proj"),
        policy=SidecarRefPolicy(
            role="plans",
            ref_kind="plan",
            is_document=True,
            spec={"ref": {"kind": "plan", "label": "Plan"}},
        ),
    )
    descriptors = provider_descriptors(
        [healthy],
        (
            ProviderDiscoveryIssue(
                message="artifact ref provider 'missing-provider' is not installed",
                code="missing_ref_provider",
                kind="research",
                role="research",
            ),
        ),
    )
    by_id = {descriptor.id: descriptor for descriptor in descriptors}
    assert by_id["ref:plan"].is_degraded is False
    assert by_id["ref:research"].is_degraded is True
    assert by_id["ref:plan"].error is None


def test_discovery_failure_keeps_a_degraded_plan_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import _artifact_tab_discovery

    def _boom(*_args: object, **_kwargs: object) -> list[object]:
        raise ImportError("sase_core_rs is not importable in this environment")

    monkeypatch.setattr(_artifact_tab_discovery, "list_project_records", _boom)
    reset_artifacts_subtabs_cache()
    first = resolve_artifacts_subtabs()
    reset_artifacts_subtabs_cache()
    second = resolve_artifacts_subtabs()

    assert [descriptor.id for descriptor in first] == [
        "agents",
        "stitches",
        "patches",
        "beads",
        "ref:plan",
        "files",
    ]
    plan = next(descriptor for descriptor in first if descriptor.id == "ref:plan")
    assert plan.is_degraded
    assert plan.error_code == "provider_discovery_failed"
    assert "sase_core_rs" in (plan.error or "")
    assert [descriptor.id for descriptor in second] == [d.id for d in first]
    assert ARTIFACTS_ACCENTS.get("ref:plan") == "#AF87FF"


def _fake_project_record(project_file: Path) -> object:
    from sase.core.project_lifecycle_wire import ProjectRecordWire

    return ProjectRecordWire(
        schema_version=1,
        project_name="proj",
        project_dir=str(project_file.parent),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def test_provider_source_token_cache_invalidates_on_project_file_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.ace.tui import _artifact_tab_discovery as discovery

    project_file = tmp_path / "proj.sase"
    project_file.write_text("PROJECT_NAME: proj\n")

    monkeypatch.setattr(
        discovery,
        "list_project_records",
        lambda *args, **kwargs: (_fake_project_record(project_file),),
    )
    monkeypatch.setattr(discovery, "current_config_token", lambda: ("config", 1))

    discovery.reset_provider_source_token_cache()
    first = discovery.provider_source_token()
    assert first is not None

    # Still within the refresh window: the cache wins even though the file
    # underneath it just changed.
    stat = project_file.stat()
    os.utime(project_file, ns=(stat.st_mtime_ns + 10**9, stat.st_mtime_ns + 10**9))
    assert discovery.provider_source_token() == first

    reset_artifacts_subtabs_cache()
    second = discovery.provider_source_token()
    assert second is not None
    assert second != first


def test_provider_source_token_does_not_cache_a_none_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import _artifact_tab_discovery as discovery

    def _boom(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise ImportError("sase_core_rs is not importable in this environment")

    discovery.reset_provider_source_token_cache()
    monkeypatch.setattr(discovery, "list_project_records", _boom)
    assert discovery.provider_source_token() is None

    monkeypatch.setattr(discovery, "list_project_records", lambda *args, **kwargs: ())
    monkeypatch.setattr(discovery, "current_config_token", lambda: ("config", 1))
    assert discovery.provider_source_token() is not None
