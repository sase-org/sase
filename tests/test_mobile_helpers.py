from __future__ import annotations

import argparse
import io
import json
from collections.abc import Callable

import pytest

from sase.ace.changespec import ChangeSpec
from sase.integrations.mobile_helpers import handle_mobile_helper_bridge
from sase.xprompt.catalog import (
    StructuredCatalogAttachment,
    StructuredCatalogEntry,
    StructuredCatalogProjection,
    StructuredCatalogSkipped,
    StructuredCatalogStats,
)


def _cs(
    name: str,
    status: str,
    project: str,
    *,
    archive: bool = False,
) -> ChangeSpec:
    suffix = "-archive" if archive else ""
    return ChangeSpec(
        name=name,
        description="",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=f"/home/user/.sase/projects/{project}/{project}{suffix}.gp",
        line_number=1,
    )


@pytest.fixture
def set_changespecs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[ChangeSpec]], None]:
    def _set(changespecs: list[ChangeSpec]) -> None:
        monkeypatch.setattr(
            "sase.integrations.changespec_tags.find_all_changespecs",
            lambda: changespecs,
        )

    return _set


def _run_bridge(
    payload: object, operation: str = "changespec-tags"
) -> tuple[int, dict[str, object], str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_mobile_helper_bridge(
        argparse.Namespace(mobile_helper_bridge_subcommand=operation),
        stdin=io.StringIO(json.dumps(payload)),
        stdout=stdout,
        stderr=stderr,
    )
    data = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
    return code, data, stderr.getvalue()


def test_changespec_tags_bridge_projects_wire_shape_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs(
        [
            _cs("zeta", "Ready", "sase"),
            _cs("alpha", "WIP (sase_1)", "sase"),
            _cs("other", "Ready", "other"),
        ]
    )
    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type",
        lambda project_file: "gh",
    )

    code, data, stderr = _run_bridge(
        {"schema_version": 1, "project": "sase", "limit": 1}
    )

    assert code == 0
    assert stderr == ""
    assert data["schema_version"] == 1
    assert data["context"] == {"project": "sase", "scope": "explicit"}
    assert data["result"]["status"] == "success"  # type: ignore[index]
    assert data["total_count"] == 2
    assert data["tags"] == [
        {
            "tag": "#gh:alpha",
            "project": "sase",
            "changespec": "alpha",
            "title": None,
            "status": "WIP",
            "workflow": "gh",
            "source_path_display": None,
        }
    ]


def test_changespec_tags_bridge_returns_skipped_structurally(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs([_cs("bad", "Ready", "sase"), _cs("good", "Ready", "sase")])

    def detect(project_file: str) -> str:
        if "/sase/" in project_file:
            raise ValueError("workflow missing")
        return "gh"

    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type", detect
    )

    code, data, stderr = _run_bridge({"schema_version": 1})

    assert code == 0
    assert stderr == ""
    assert data["result"]["status"] == "partial_success"  # type: ignore[index]
    assert data["result"]["partial_failure_count"] == 2  # type: ignore[index]
    assert data["result"]["skipped"] == [  # type: ignore[index]
        {
            "target": "sase/bad",
            "reason": "could not detect workflow type: workflow missing",
        },
        {
            "target": "sase/good",
            "reason": "could not detect workflow type: workflow missing",
        },
    ]


def test_changespec_tags_bridge_rejects_invalid_json() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_mobile_helper_bridge(
        argparse.Namespace(mobile_helper_bridge_subcommand="changespec-tags"),
        stdin=io.StringIO("{invalid"),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert "invalid JSON request" in stderr.getvalue()


def test_changespec_tags_bridge_rejects_invalid_limit() -> None:
    code, data, stderr = _run_bridge({"schema_version": 1, "limit": "10"})

    assert code == 2
    assert data == {}
    assert "limit must be an integer" in stderr


def test_xprompt_catalog_bridge_returns_structured_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_catalog(**kwargs: object) -> StructuredCatalogProjection:
        assert kwargs == {
            "project": "sase",
            "source": "project",
            "tag": "fix_hook",
            "query": "repair",
            "include_pdf": True,
            "limit": 2,
        }
        return StructuredCatalogProjection(
            entries=[
                StructuredCatalogEntry(
                    name="fix_hook",
                    display_label="fix hook",
                    description="Repair a hook failure",
                    source_bucket="project",
                    project="sase",
                    tags=["fix_hook"],
                    input_signature="(log: text)",
                    is_skill=False,
                    content_preview="Repair this failure",
                    source_path_display=".sase/xprompts/fix_hook.md",
                )
            ],
            stats=StructuredCatalogStats(
                total_count=5,
                project_count=1,
                skill_count=0,
                pdf_requested=True,
            ),
            warnings=["PDF catalog was not generated"],
            skipped=[
                StructuredCatalogSkipped(
                    target="xprompt-catalog.pdf",
                    reason="No PDF engine available.",
                )
            ],
            catalog_attachment=None,
        )

    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.build_structured_xprompts_catalog",
        fake_catalog,
    )

    code, data, stderr = _run_bridge(
        {
            "schema_version": 1,
            "project": "sase",
            "source": "project",
            "tag": "fix_hook",
            "query": "repair",
            "include_pdf": True,
            "limit": 2,
        },
        operation="xprompt-catalog",
    )

    assert code == 0
    assert stderr == ""
    assert data["context"] == {"project": "sase", "scope": "explicit"}
    assert data["result"]["status"] == "partial_success"  # type: ignore[index]
    assert data["stats"] == {
        "total_count": 5,
        "project_count": 1,
        "skill_count": 0,
        "pdf_requested": True,
    }
    assert data["catalog_attachment"] is None
    assert data["entries"] == [
        {
            "name": "fix_hook",
            "display_label": "fix hook",
            "description": "Repair a hook failure",
            "source_bucket": "project",
            "project": "sase",
            "tags": ["fix_hook"],
            "input_signature": "(log: text)",
            "is_skill": False,
            "content_preview": "Repair this failure",
            "source_path_display": ".sase/xprompts/fix_hook.md",
        }
    ]


def test_xprompt_catalog_bridge_returns_attachment_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.build_structured_xprompts_catalog",
        lambda **_kwargs: StructuredCatalogProjection(
            entries=[],
            stats=StructuredCatalogStats(
                total_count=0,
                project_count=0,
                skill_count=0,
                pdf_requested=True,
            ),
            warnings=[],
            skipped=[],
            catalog_attachment=StructuredCatalogAttachment(
                display_name="xprompts_catalog.pdf",
                content_type="application/pdf",
                byte_size=123,
                path_display="~/tmp/xprompts_catalog.pdf",
                generated=True,
            ),
        ),
    )

    code, data, stderr = _run_bridge(
        {"schema_version": 1, "include_pdf": True},
        operation="xprompt-catalog",
    )

    assert code == 0
    assert stderr == ""
    assert data["result"]["status"] == "success"  # type: ignore[index]
    assert data["catalog_attachment"] == {
        "display_name": "xprompts_catalog.pdf",
        "content_type": "application/pdf",
        "byte_size": 123,
        "path_display": "~/tmp/xprompts_catalog.pdf",
        "generated": True,
    }


def test_xprompt_catalog_bridge_rejects_invalid_include_pdf() -> None:
    code, data, stderr = _run_bridge(
        {"schema_version": 1, "include_pdf": "yes"},
        operation="xprompt-catalog",
    )

    assert code == 2
    assert data == {}
    assert "include_pdf must be a boolean" in stderr
