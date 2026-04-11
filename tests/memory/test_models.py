"""Tests for sase.memory.models."""

import pytest

from sase.memory.models import MemoryFile, MemoryType


class TestMemoryType:
    def test_all_values(self) -> None:
        expected = {
            "architecture",
            "convention",
            "decision",
            "feedback",
            "reference",
            "pitfall",
        }
        assert {t.value for t in MemoryType} == expected

    def test_from_string(self) -> None:
        assert MemoryType("feedback") is MemoryType.FEEDBACK


class TestMemoryFileToMarkdown:
    def test_round_trip(self) -> None:
        mem = MemoryFile(
            name="Test Memory",
            description="A test memory",
            memory_type=MemoryType.FEEDBACK,
            created="2026-04-11",
            body="Use real databases in tests.\n\n**Why:** Mocks diverged from prod.",
        )
        md = mem.to_markdown()
        parsed = MemoryFile.from_markdown(md)
        assert parsed.name == mem.name
        assert parsed.description == mem.description
        assert parsed.memory_type == mem.memory_type
        assert parsed.created == mem.created
        assert parsed.body == mem.body.strip()

    def test_trailing_newline(self) -> None:
        mem = MemoryFile(
            name="X",
            description="d",
            memory_type=MemoryType.DECISION,
            created="2026-01-01",
            body="content",
        )
        assert mem.to_markdown().endswith("\n")


class TestMemoryFileFromMarkdown:
    def test_valid(self) -> None:
        text = (
            "---\n"
            "name: Arch\n"
            "description: Architecture notes\n"
            "type: architecture\n"
            "created: 2026-04-11\n"
            "---\n"
            "\n"
            "The system uses src layout.\n"
        )
        mem = MemoryFile.from_markdown(text, project="sase")
        assert mem.name == "Arch"
        assert mem.memory_type is MemoryType.ARCHITECTURE
        assert mem.project == "sase"
        assert "src layout" in mem.body

    def test_missing_frontmatter_start(self) -> None:
        with pytest.raises(ValueError, match="must start with YAML frontmatter"):
            MemoryFile.from_markdown("no frontmatter here")

    def test_missing_closing_fence(self) -> None:
        with pytest.raises(ValueError, match="closing frontmatter"):
            MemoryFile.from_markdown("---\nname: X\n")

    def test_missing_required_field(self) -> None:
        text = "---\nname: X\ndescription: d\n---\nbody"
        with pytest.raises(ValueError, match="Missing frontmatter fields"):
            MemoryFile.from_markdown(text)
