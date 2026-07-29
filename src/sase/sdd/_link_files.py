"""Root resolution and file discovery for linked SDD artifacts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.sdd._link_models import SddFile
from sase.sdd._link_support import LIST_KINDS, PROMPT_KINDS, relpath
from sase.sdd._paths import has_month_dirs, is_month_dir_name
from sase.sdd.artifact_links import parse_sdd_artifact_link
from sase.sdd.plan_tiers import classify_plan_file


def resolve_sdd_root(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve an SDD root from either an SDD dir or a project dir."""
    base = Path.cwd() if cwd is None else cwd
    if path is None:
        return _resolve_project_sdd_root(base).resolve()

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.is_dir() and _looks_like_project_root(candidate):
        candidate = _resolve_project_sdd_root(candidate)
    return candidate.resolve()


def list_sdd_files(root: Path, *, kind: str = "all") -> list[SddFile]:
    """Return known SDD markdown files under ``root``."""
    files: list[SddFile] = []
    plans_root = root / "plans"
    if not has_month_dirs(plans_root):
        plans_root = root
    if kind in {"all", "prompts"}:
        if plans_root.is_dir():
            for path in sorted(plans_root.glob("*/prompts/*.md")):
                sdd_file = _read_sdd_file(root, path, "prompts")
                if sdd_file is not None:
                    files.append(sdd_file)
        for physical_kind in PROMPT_KINDS:
            kind_root = root / physical_kind
            if not kind_root.is_dir():
                continue
            for path in sorted(kind_root.glob("*/*.md")):
                sdd_file = _read_sdd_file(root, path, "prompts")
                if sdd_file is not None:
                    files.append(sdd_file)
    if kind in {"all", "plans", "tales", "epics"}:
        kind_root = plans_root
        if kind_root.is_dir():
            for path in sorted(kind_root.glob("*/*.md")):
                sdd_file = _read_sdd_file(root, path, "tales")
                if sdd_file is None:
                    continue
                item_kind = f"{classify_plan_file(path, sdd_file.frontmatter)}s"
                sdd_file = replace(sdd_file, kind=item_kind)
                if kind in {"all", "plans", item_kind}:
                    files.append(sdd_file)
    return sorted(files, key=lambda file: file.relpath)


def _read_sdd_file(root: Path, path: Path, kind: str) -> SddFile | None:
    parts = path.relative_to(root).parts
    nested_prompt = (
        kind == "prompts"
        and len(parts) == 4
        and parts[0] == "plans"
        and parts[2] == "prompts"
    )
    flat_prompt = kind == "prompts" and len(parts) == 3 and parts[1] == "prompts"
    flat_plan = kind != "prompts" and len(parts) == 2
    if len(parts) != 3 and not nested_prompt and not flat_prompt and not flat_plan:
        return None
    yyyymm = parts[0] if flat_prompt or flat_plan else parts[1]
    if not is_month_dir_name(yyyymm):
        return None
    content = path.read_text(encoding="utf-8")
    artifact_link = parse_sdd_artifact_link(content)
    frontmatter, _, had_frontmatter, parse_error = _parse_frontmatter_strict(content)
    return SddFile(
        path=path,
        relpath=relpath(root, path),
        kind=kind,
        yyyymm=yyyymm,
        name=path.stem,
        frontmatter=frontmatter,
        artifact_link=artifact_link,
        body=artifact_link.body,
        had_frontmatter=had_frontmatter,
        parse_error=parse_error,
    )


def _parse_frontmatter_strict(
    content: str,
) -> tuple[dict[str, Any], str, bool, str | None]:
    if not content.startswith("---\n"):
        return {}, content, False, None
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content, True, "frontmatter closing marker not found"
    raw = content[4:end]
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as exc:
        return {}, content[end + 5 :], True, f"invalid YAML frontmatter: {exc}"
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, content[end + 5 :], True, "frontmatter must be a YAML mapping"
    return dict(parsed), content[end + 5 :], True, None


def _looks_like_project_root(path: Path) -> bool:
    if path.name == "sdd" and path.parent.name == ".sase":
        return False
    if path.parent.name == "repos" and path.parent.parent.name == "sase":
        return False
    if (path / "beads").is_dir():
        return False
    if has_month_dirs(path):
        return False
    has_project_marker = (
        (path / "sase" / "sase.yml").is_file()
        or (path / "sase.yml").is_file()
        or (path / ".git").exists()
        or (path / "sdd").is_dir()
        or (path / ".sase" / "sdd").is_dir()
    )
    return has_project_marker and not any((path / kind).is_dir() for kind in LIST_KINDS)


def _resolve_project_sdd_root(project_root: Path) -> Path:
    try:
        from sase.sdd.store import resolve_sdd_dir

        return resolve_sdd_dir(project_root, 1)
    except Exception:
        return project_root / ".sase" / "sdd"
