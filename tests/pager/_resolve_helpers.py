"""Shared helpers for pager link-resolution tests."""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import ArtifactRefTargetResolution
from sase.pager.document import PagerTargetSpan
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.link_scan import LinkSpanKind


def _context(
    *directories: Path, workspace_num: int | None = None
) -> LinkResolutionContext:
    return LinkResolutionContext(
        anchors=tuple(
            LinkAnchor(directory=directory, workspace_num=workspace_num)
            for directory in directories
        )
    )


def _write(path: Path, body: str = "ok\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _span(kind: LinkSpanKind, text: str) -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=kind.value,
        target=text,
        start=0,
        end=len(text),
        text=text,
        source="scanned",
    )


def _owned_resolution(**overrides: object) -> ArtifactRefTargetResolution:
    values: dict[str, object] = {
        "schema_version": 1,
        "status": "exact",
        "resolved_path": None,
        "repository": "capture",
        "revision": None,
        "candidates": (),
        "failure_category": None,
        "retryable": False,
    }
    values.update(overrides)
    return ArtifactRefTargetResolution(**values)  # type: ignore[arg-type]
