from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.changespec import ChangeSpec
from sase.integrations.chat_install import (
    ChatInstallLaunchResult,
    ChatInstallStatusResult,
)
from sase.xprompt.catalog import (
    StructuredCatalogEntry,
    StructuredCatalogProjection,
    StructuredCatalogStats,
)
from tests._mobile_helper_bridge_helpers import (
    run_bridge,
    seed_bead_project,
    seed_known_projects,
    stub_changespecs,
)


def test_mobile_helper_bridge_smoke_all_helpers_with_temp_project_and_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    project_file = tmp_path / ".sase/projects/alpha/alpha.gp"
    stub_changespecs(
        monkeypatch,
        [
            ChangeSpec(
                name="mobile_helper",
                description="",
                parent=None,
                cl=None,
                status="Ready",
                test_targets=None,
                kickstart=None,
                file_path=str(project_file),
                line_number=1,
            )
        ],
    )
    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type",
        lambda _project_file: "gh",
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.build_structured_xprompts_catalog",
        lambda **_kwargs: StructuredCatalogProjection(
            entries=[
                StructuredCatalogEntry(
                    name="mobile",
                    display_label="mobile",
                    description="Mobile helper smoke prompt",
                    source_bucket="project",
                    project="alpha",
                    tags=["mobile"],
                    input_signature=None,
                    is_skill=False,
                    content_preview="Smoke helper prompt",
                    source_path_display="xprompts/mobile.md",
                )
            ],
            stats=StructuredCatalogStats(
                total_count=1,
                project_count=1,
                skill_count=0,
                pdf_requested=False,
            ),
            warnings=[],
            skipped=[],
            catalog_attachment=None,
        ),
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.start_chat_install_worker",
        lambda: ChatInstallLaunchResult(
            status="launched",
            message="Update worker started.",
            job_id="job_smoke",
            log_path=tmp_path / "install.log",
            status_path=tmp_path / "job_smoke.json",
        ),
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.read_chat_install_status",
        lambda job_id: ChatInstallStatusResult(
            status="succeeded",
            message="Update completed successfully.",
            job_id=job_id,
            started_at="2026-05-06T15:00:00+00:00",
            finished_at="2026-05-06T15:01:00+00:00",
            log_path=tmp_path / "install.log",
            completion_path=tmp_path / "job_smoke.json",
        ),
    )

    calls = [
        (
            "changespec-tags",
            {"schema_version": 1, "project": "alpha"},
            ("tags",),
        ),
        (
            "xprompt-catalog",
            {"schema_version": 1, "project": "alpha"},
            ("entries",),
        ),
        (
            "beads-list",
            {"schema_version": 1, "project": "alpha"},
            ("beads",),
        ),
        (
            "beads-show",
            {"schema_version": 1, "project": "alpha", "bead_id": alpha_epic.id},
            ("bead",),
        ),
        ("update-start", {"schema_version": 1}, ("job",)),
        (
            "update-status",
            {"schema_version": 1, "job_id": "job_smoke"},
            ("job",),
        ),
    ]

    for operation, payload, required_keys in calls:
        code, data, stderr = run_bridge(payload, operation)

        assert code == 0, f"{operation}: {stderr}"
        assert stderr == ""
        assert data["schema_version"] == 1
        assert set(data["result"]) == {
            "status",
            "message",
            "warnings",
            "skipped",
            "partial_failure_count",
        }
        assert data["result"]["status"] == "success"  # type: ignore[index]
        for key in required_keys:
            assert key in data
