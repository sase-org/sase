"""Linked plan document loading contracts used by Active plans."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.plans_data_documents import (
    LinkedPlanPayload,
    load_linked_plan_document,
)


def test_linked_document_reads_are_deduplicated_by_resolved_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "202608" / "plan.md"
    path.parent.mkdir()
    path.write_text("---\ntitle: Shared plan\n---\nBody.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data_documents._resolve_linked_plan_path",
        lambda *_args, **_kwargs: path,
    )
    reads: list[Path] = []

    def read_text(value: Path) -> str:
        reads.append(value)
        return value.read_text(encoding="utf-8")

    cache: dict[Path, LinkedPlanPayload] = {}
    first = load_linked_plan_document(
        "plans:202608/plan.md",
        workspace_dir=str(tmp_path),
        plans_root=tmp_path,
        read_cache=cache,
        read_text=read_text,
    )
    second = load_linked_plan_document(
        "plans:202608/plan.md",
        workspace_dir=str(tmp_path),
        plans_root=tmp_path,
        read_cache=cache,
        read_text=read_text,
    )

    assert reads == [path]
    assert first.available and second.available
    assert first.body == "Body.\n"


def test_missing_linked_document_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "missing.md"
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data_documents._resolve_linked_plan_path",
        lambda *_args, **_kwargs: path,
    )

    document = load_linked_plan_document(
        "plans:missing.md",
        workspace_dir=str(tmp_path),
        plans_root=tmp_path,
        read_cache={},
        read_text=lambda value: value.read_text(encoding="utf-8"),
    )

    assert not document.available
    assert document.error == "Linked plan unavailable: file not found."
