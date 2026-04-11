"""Data models for the memory system."""

from dataclasses import dataclass
from enum import Enum


class MemoryType(Enum):
    """Supported memory categories."""

    ARCHITECTURE = "architecture"
    CONVENTION = "convention"
    DECISION = "decision"
    FEEDBACK = "feedback"
    REFERENCE = "reference"
    PITFALL = "pitfall"


@dataclass
class MemoryFile:
    """A single memory entry with YAML frontmatter and markdown body."""

    name: str
    description: str
    memory_type: MemoryType
    created: str
    body: str
    project: str | None = None
    system: bool = False

    def to_markdown(self) -> str:
        """Serialize to markdown with YAML frontmatter."""
        lines = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
            f"type: {self.memory_type.value}",
            f"created: {self.created}",
            "---",
            "",
            self.body,
        ]
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"
        return text

    @staticmethod
    def from_markdown(text: str, project: str | None = None) -> "MemoryFile":
        """Parse a markdown file with YAML frontmatter into a MemoryFile."""
        if not text.startswith("---"):
            raise ValueError("Memory file must start with YAML frontmatter (---)")

        # Split on the second '---'
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError("Memory file must have closing frontmatter (---)")

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        # Parse frontmatter as simple key: value pairs
        meta: dict[str, str] = {}
        for line in frontmatter_text.splitlines():
            line = line.strip()
            if not line:
                continue
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

        required = {"name", "description", "type", "created"}
        missing = required - meta.keys()
        if missing:
            raise ValueError(
                f"Missing frontmatter fields: {', '.join(sorted(missing))}"
            )

        return MemoryFile(
            name=meta["name"],
            description=meta["description"],
            memory_type=MemoryType(meta["type"]),
            created=meta["created"],
            body=body,
            project=project,
        )
