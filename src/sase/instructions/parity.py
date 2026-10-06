"""Legacy parity checker for instruction bundles (E2 render-cli).

Compares a compiled bundle against the legacy native files (the project
root ``AGENTS.md`` and the home ``AGENTS.md``): every legacy core path,
reference path, and web path must map to an included or shadowed bundle
section, every repository name in either legacy Repositories list must
appear in ``pkg.sase.repos``, and exactly one included section must contain
the contract marker for root renders. Extra bundle sections (for example
``pkg.provider.*``) are reported as additions, not failures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.amd._agents_doc import parse_amd_agents_document
from sase.instructions.sections import section_slug

#: Marker whose included-section count must be exactly one for parity.
CONTRACT_MARKER = "SASE Final Declaration"

#: Legacy generated-contract note mapped onto the package sections.
_GENERATED_CONTRACT_STEM = "sase"

_REPO_SECTION_RE = re.compile(r"^##\s+Repositories\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+.*$", re.MULTILINE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class ParityIssue:
    """One parity failure: a missing unit, repo, or contract problem."""

    kind: str
    detail: str
    section_id: str | None = None


@dataclass(frozen=True)
class ParityReport:
    """Result of :func:`legacy_parity`."""

    ok: bool
    issues: tuple[ParityIssue, ...] = ()
    additions: tuple[str, ...] = ()
    contract_count: int = 0
    missing_sections: tuple[str, ...] = ()
    missing_repos: tuple[str, ...] = ()

    def summary(self) -> str:
        """Return a one-line human summary of this report."""
        if self.ok:
            return f"parity ok: contract_count=1, additions={len(self.additions)}"
        parts = [
            f"{len(self.missing_sections)} missing sections",
            f"{len(self.missing_repos)} missing repos",
        ]
        if self.contract_count != 1:
            parts.append(f"contract_count={self.contract_count}")
        return "parity failed: " + ", ".join(parts)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _legacy_repo_names(text: str | None) -> tuple[str, ...]:
    """Return the repository names in the legacy Repositories section."""
    if not text:
        return ()
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _REPO_SECTION_RE.match(line.strip()):
            start = index + 1
            break
    if start is None:
        return ()
    end = len(lines)
    for index in range(start, len(lines)):
        if _H2_RE.match(lines[index]):
            end = index
            break
    names: list[str] = []
    for line in lines[start:end]:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        for token in _BACKTICK_RE.findall(stripped):
            name = token.strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _expected_section_id(prefix: str, kind_group: str, path: str) -> str | None:
    """Return the bundle section id for legacy *path*, or None for sase.md."""
    stem = Path(path).stem
    if stem == _GENERATED_CONTRACT_STEM and Path(path).parent.as_posix().endswith(
        "memory"
    ):
        return None
    return f"{prefix}.{kind_group}.{section_slug(stem)}"


def legacy_parity(
    compiled: Any,
    project_root: Path | str,
    home_root: Path | str,
) -> ParityReport:
    """Compare *compiled* against the legacy native files.

    *compiled* is a :class:`CompiledBundle` (or any object with ``text`` and
    ``sections`` wire dicts). Every legacy core, reference, and web path must
    map to an included or shadowed bundle section; the legacy ``sase.md``
    maps to the ``pkg.sase.*`` sections. Every legacy repository name must
    appear in ``pkg.sase.repos``. Exactly one included section must contain
    ``SASE Final Declaration``.
    """
    project_path = Path(project_root)
    home_path = Path(home_root)
    sections: tuple[dict[str, Any], ...] = tuple(compiled.sections)
    by_id = {str(section["id"]): section for section in sections}
    included = {
        section_id
        for section_id, section in by_id.items()
        if section.get("status") == "included"
    }
    shadowed = {
        section_id
        for section_id, section in by_id.items()
        if section.get("status") == "excluded" and section.get("reason") == "shadowed"
    }
    covered = included | shadowed

    bundle_text = str(compiled.text)
    section_texts: dict[str, str] = {}
    for section in sections:
        if section.get("status") != "included":
            continue
        offset = section.get("offset")
        length = section.get("length")
        if isinstance(offset, int) and isinstance(length, int):
            raw = bundle_text.encode("utf-8")[offset : offset + length]
            section_texts[str(section["id"])] = raw.decode("utf-8", "replace")
    contract_count = sum(
        1 for text in section_texts.values() if CONTRACT_MARKER in text
    )

    issues: list[ParityIssue] = []
    missing_sections: list[str] = []
    mapped_ids: set[str] = set()

    project_text = _read_text(project_path / "AGENTS.md")
    home_text = _read_text(home_path / "AGENTS.md") if home_path.is_dir() else None
    for prefix, legacy_text in (("proj", project_text), ("home", home_text)):
        if not legacy_text:
            continue
        parsed = parse_amd_agents_document(legacy_text)
        expected: list[tuple[str, str]] = []
        for path in parsed.short_memory_paths:
            expected.append((path, "core"))
        for entry in parsed.long_memory_entries:
            expected.append((entry.path, "ref"))
        for path in parsed.web_memory_paths:
            expected.append((path, "web"))
        for path, kind_group in expected:
            section_id = _expected_section_id(prefix, kind_group, path)
            if section_id is None:
                for candidate in by_id:
                    if candidate.startswith("pkg.sase.") or candidate == (
                        "pkg.root.final_declaration"
                    ):
                        mapped_ids.add(candidate)
                continue
            mapped_ids.add(section_id)
            if section_id not in covered:
                missing_sections.append(section_id)
                issues.append(
                    ParityIssue(
                        kind="missing_section",
                        detail=f"legacy {prefix} {kind_group} {path!r} "
                        f"has no bundle section {section_id!r}",
                        section_id=section_id,
                    )
                )

    repos_text = section_texts.get("pkg.sase.repos", "")
    bundle_repos = set(_BACKTICK_RE.findall(repos_text))
    legacy_repos = (*_legacy_repo_names(project_text),)
    if home_text:
        legacy_repos = (*legacy_repos, *_legacy_repo_names(home_text))
    missing_repos: list[str] = []
    for name in legacy_repos:
        if name not in bundle_repos and name not in repos_text:
            missing_repos.append(name)
            issues.append(
                ParityIssue(
                    kind="missing_repo",
                    detail=f"legacy repository {name!r} is missing from pkg.sase.repos",
                )
            )
    if "pkg.sase.repos" in by_id:
        mapped_ids.add("pkg.sase.repos")

    if contract_count != 1:
        issues.append(
            ParityIssue(
                kind="contract",
                detail=f"expected exactly one included section containing "
                f"{CONTRACT_MARKER!r}, found {contract_count}",
            )
        )

    additions = tuple(
        sorted(section_id for section_id in included if section_id not in mapped_ids)
    )
    ok = not issues
    return ParityReport(
        ok=ok,
        issues=tuple(issues),
        additions=additions,
        contract_count=contract_count,
        missing_sections=tuple(missing_sections),
        missing_repos=tuple(missing_repos),
    )


def render_parity_table(report: ParityReport, *, console: Any | None = None) -> None:
    """Render *report* as a Rich table (missing units fail, extras inform)."""
    from rich.console import Console
    from rich.table import Table

    table = Table("status", "item", "detail", title="Legacy parity")
    for issue in report.issues:
        table.add_row(
            "✗",
            issue.section_id or issue.kind,
            issue.detail,
        )
    for section_id in report.additions:
        table.add_row("＋", section_id, "extra bundle section (not a failure)")
    if report.ok:
        table.add_row(
            "✓",
            "parity",
            f"contract_count=1, additions={len(report.additions)}",
        )
    target = console if console is not None else Console()
    target.print(table)


__all__ = [
    "CONTRACT_MARKER",
    "ParityIssue",
    "ParityReport",
    "legacy_parity",
    "render_parity_table",
]
