from __future__ import annotations

import pytest

from sase.xprompt.catalog import (
    StructuredCatalogAttachment,
    StructuredCatalogEntry,
    StructuredCatalogProjection,
    StructuredCatalogSkipped,
    StructuredCatalogStats,
)
from tests._mobile_helper_bridge_helpers import run_bridge


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

    code, data, stderr = run_bridge(
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

    code, data, stderr = run_bridge(
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
    code, data, stderr = run_bridge(
        {"schema_version": 1, "include_pdf": "yes"},
        operation="xprompt-catalog",
    )

    assert code == 2
    assert data == {}
    assert "include_pdf must be a boolean" in stderr
