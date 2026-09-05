"""Tests for the Rust-backed prompt archive inventory facade."""

from __future__ import annotations

from pathlib import Path

from sase.core.prompt_archive_facade import prompt_archive_inventory
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderSectionKind,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_prompt_archive_inventory_facade_returns_parsed_documents(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "prompts/202609/example.md",
        "---\nsha256: abc\n---\n"
        "- **PLAN:** [202609/plan.md](https://example.test/plan)\n"
        "- **AGENTS:**\n"
        "  - [alice.athena.worker](https://example.test/agent)\n"
        "- **ARTIFACTS:**\n"
        "  - [trace.txt](../../artifacts/202609/trace.txt)\n\n"
        "# Prompt body\n",
    )

    [document] = prompt_archive_inventory(tmp_path)

    assert document.relpath == "prompts/202609/example.md"
    assert document.path == tmp_path / "prompts/202609/example.md"
    assert document.month == "202609"
    assert document.name == "example"
    assert document.content.startswith("---\nsha256: abc")
    assert document.body == "# Prompt body\n"
    assert document.disposition is PlanHeaderDisposition.CANONICAL
    assert [section.kind for section in document.sections] == [
        PlanHeaderSectionKind.PLAN,
        PlanHeaderSectionKind.AGENTS,
        PlanHeaderSectionKind.ARTIFACTS,
    ]
    assert document.parse_error is None


def test_prompt_archive_inventory_facade_honors_month_selector(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "prompts/202608/old.md", "old\n")
    _write(tmp_path / "prompts/202609/new.md", "new\n")

    documents = prompt_archive_inventory(tmp_path, month="202609")

    assert [document.relpath for document in documents] == ["prompts/202609/new.md"]


def test_prompt_archive_inventory_facade_reports_invalid_headers(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "prompts/202609/broken.md",
        "- **PARENT:** [202609/parent.md](202609/parent.md) (closed)\n\nBody\n",
    )

    [document] = prompt_archive_inventory(tmp_path)

    assert document.disposition is PlanHeaderDisposition.INVALID
    assert document.parse_error
