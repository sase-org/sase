"""Package template splitting and repository config sources."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sase.instructions._sections_shared import git_blob_oid, overlay_exclusion
from sase.instructions.facts import InstructionFacts
from sase.instructions.sections_base import SectionBuilder, section_slug


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_for_file(
    *, scope: str, kind: str, root: Path | None, path: Path, fallback: bytes
) -> dict[str, Any]:
    """Return a manifest source for *path*, relativized against *root*."""
    try:
        data = path.read_bytes()
    except OSError:
        data = fallback
        source: dict[str, Any] = {
            "scope": scope,
            "kind": "generated" if kind != "generated" else kind,
            "path": path.as_posix() if root is None else _rel_posix(root, path),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return source
    if root is not None:
        rel = _rel_posix(root, path)
    else:
        rel = path.as_posix()
    return {
        "scope": scope,
        "kind": kind,
        "path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob_oid": git_blob_oid(data),
    }


def _package_subsection_id(heading: str) -> tuple[str, str, bool]:
    """Map a template H4 heading to ``(section id, lifecycle, required)``."""
    normalized = heading.strip()
    if normalized == "SASE Memory":
        return "pkg.sase.memory", "neutral", False
    lowered = normalized.lower()
    if "ephemeral" in lowered and "workspace director" in lowered:
        return "pkg.sase.workspaces", "neutral", False
    if normalized == "Repositories":
        return "pkg.sase.repos", "neutral", False
    if normalized == "SASE Final Declaration":
        return "pkg.root.final_declaration", "root", True
    return f"pkg.sase.{section_slug(normalized)}", "neutral", False


_HEADING_RE = re.compile(r"^(#{4})\s+(.*\S)\s*$")


def split_package_sections(
    package_text: str,
    *,
    template_path: str,
    template_sha256: str,
    template_blob_oid: str | None,
    facts: InstructionFacts,
    repos_config_sources: list[dict[str, Any]],
) -> list[SectionBuilder]:
    """Split inlined contract text into package sections (decision 5)."""
    lines = package_text.splitlines()
    heading_end = len(lines)
    in_fence = False
    fence_marker = ""
    breaks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            marker = stripped.split()[0] if stripped.split() else "```"
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped.startswith(fence_marker):
                in_fence = False
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            if heading_end == len(lines):
                heading_end = index
            breaks.append((index, match.group(2)))
    head_text = "\n".join(lines[:heading_end]).strip("\n")
    sections = [
        SectionBuilder(
            id="pkg.sase.heading",
            layer="package",
            text=head_text,
            sources=[
                {
                    "scope": "package",
                    "kind": "package_template",
                    "path": template_path,
                    "sha256": template_sha256,
                    **({"blob_oid": template_blob_oid} if template_blob_oid else {}),
                }
            ],
        )
    ]
    for order, (start, heading) in enumerate(breaks):
        end = breaks[order + 1][0] if order + 1 < len(breaks) else len(lines)
        section_id, lifecycle, required = _package_subsection_id(heading)
        sources: list[dict[str, Any]] = [
            {
                "scope": "package",
                "kind": "package_template",
                "path": template_path,
                "sha256": template_sha256,
                **({"blob_oid": template_blob_oid} if template_blob_oid else {}),
            }
        ]
        if section_id == "pkg.sase.repos":
            sources.extend(repos_config_sources)
        builder = SectionBuilder(
            id=section_id,
            layer="package",
            lifecycle=lifecycle,
            required=required,
            text="\n".join(lines[start:end]).strip("\n"),
            sources=sources,
        )
        reason = overlay_exclusion(facts, lifecycle=lifecycle, section_id=section_id)
        if reason is not None:
            builder.text = None
            builder.reason = reason
        sections.append(builder)
    return sections


def repos_config_sources(
    *,
    project_root: Path,
    project_config: Path,
    global_config: Path,
    project_entries: tuple[Any, ...],
    home_entries: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """Return config sources for the merged Repositories section."""
    try:
        project_config_rel = project_config.relative_to(project_root).as_posix()
    except ValueError:
        project_config_rel = project_config.as_posix()
    repos_sources: list[dict[str, Any]] = []
    if project_entries:
        repos_sources.append(
            _source_for_file(
                scope="project",
                kind="config",
                root=project_root,
                path=project_config,
                fallback=b"",
            )
        )
        repos_sources[-1]["path"] = project_config_rel
    if home_entries:
        repos_sources.append(
            {
                "scope": "home",
                "kind": "config",
                "path": f"global/{global_config.name}",
            }
        )
    return repos_sources


__all__ = [
    "repos_config_sources",
    "split_package_sections",
]
