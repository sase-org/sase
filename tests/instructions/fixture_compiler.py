"""Tmp project/home fixtures for instruction compiler tests."""

from __future__ import annotations

from pathlib import Path

from sase.instructions.facts import InstructionFacts, parse_facts


def write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def core_note(body: str) -> str:
    """Wrap *body* as a core memory note."""
    return "---\ntype: core\nparent: AGENTS.md\n---\n" + body


def reference_note(body: str, *, description: str = "A reference note.") -> str:
    """Wrap *body* as a reference memory note."""
    return (
        "---\ntype: reference\nparent: AGENTS.md\n"
        f"description: {description}\n---\n" + body
    )


def web_descriptor(title: str, description: str) -> str:
    """Return a minimal memory web descriptor body."""
    return (
        "---\nweb: true\n"
        f"description: {description}\n"
        "roster: list\n"
        "---\n"
        f"# {title}\n\nDescriptor body.\n"
    )


def web_strand(keyword: str, summary: str) -> str:
    """Return a minimal memory web strand body."""
    return (
        "---\n"
        f"keyword: {keyword}\n"
        f"summary: {summary}\n"
        "metadata:\n"
        "  status: accepted\n"
        "---\n\n**Claim.** A test claim.\n"
    )


def make_roots(base: Path, *, leaf: str = "proj") -> tuple[Path, Path]:
    """Build a fixture project and home under *base*; return both roots."""
    project_root = base / leaf
    home_root = base / "home"
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    write(
        project_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture\n\nProject contract note.\n"),
    )
    write(
        project_root / "sase" / "memory" / "gotchas.md",
        core_note("# Gotchas\n\nProject gotchas.\n"),
    )
    write(
        project_root / "sase" / "memory" / "cli_rules.md",
        reference_note("# CLI\n\nRules body.\n", description="CLI rules."),
    )
    write(
        project_root / "sase" / "memory" / "decisions.md",
        web_descriptor("Decisions", "Project decisions."),
    )
    write(
        project_root / "sase" / "memory" / "decisions" / "first.md",
        web_strand("First Decision", "The first decision."),
    )
    write(
        home_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture Home\n\nHome contract note.\n"),
    )
    write(
        home_root / "sase" / "memory" / "gotchas.md",
        core_note("# Gotchas\n\nHome gotchas.\n"),
    )
    write(
        home_root / "sase" / "memory" / "home_only.md",
        core_note("# Home Only\n\nHome-only core note.\n"),
    )
    return project_root, home_root


def make_facts(
    provider: str = "codex",
    *,
    actor: str = "sase_root",
    mode: str = "runtime",
    purpose: str = "ordinary",
    project: str | None = "fixture",
) -> InstructionFacts:
    """Return valid facts for compiler tests."""
    return parse_facts(
        {
            "actor": actor,
            "mode": mode,
            "purpose": purpose,
            "provider": provider,
            "project": project,
            "host": "testhost",
            "vcs": None,
        }
    )


__all__ = [
    "core_note",
    "make_facts",
    "make_roots",
    "reference_note",
    "web_descriptor",
    "web_strand",
    "write",
]
