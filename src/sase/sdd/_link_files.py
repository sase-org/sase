"""Root resolution and file discovery for linked SDD artifacts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.sdd._link_models import SddFile
from sase.sdd._link_support import LIST_KINDS, relpath
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
    flat_plan = len(parts) == 2
    if len(parts) != 3 and not flat_plan:
        return None
    yyyymm = parts[0] if flat_plan else parts[1]
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


def invalid_sdd_root_message(root: Path) -> str:
    """Return the invalid-root message, with a nested-clone remedy when needed."""

    message = f"SDD path does not exist or is not a directory: {root}"
    git_root = _git_checkout_root(root)
    if git_root is not None and _repo_open_clone_owner(git_root) is not None:
        return (
            f"{message}. Rerun `sase repo open` for this checkout to "
            "provision its plans sidecar"
        )
    return message


def _resolve_project_sdd_root(project_root: Path) -> Path:
    try:
        nested = _nested_repo_open_sdd_root(project_root)
    except Exception:
        nested = None
    if nested is not None:
        return nested
    try:
        from sase.sdd.store import resolve_sdd_dir

        return resolve_sdd_dir(project_root, 1)
    except Exception:
        return project_root / ".sase" / "sdd"


def _nested_repo_open_sdd_root(project_root: Path) -> Path | None:
    """Resolve a nested repo-open checkout from its own store record."""

    git_root = _git_checkout_root(project_root)
    if git_root is None or _repo_open_clone_owner(git_root) is None:
        return None

    from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
    from sase.sdd.store import resolve_sdd_store

    if not is_materialized_record(read_sdd_store_record(git_root)):
        return None

    checkout = str(git_root)

    def checkout_local(_workspace_dir: str, _workspace_num: int) -> str:
        return checkout

    return resolve_sdd_store(
        git_root,
        1,
        primary_workspace_resolver=checkout_local,
    ).sdd_dir


def _git_checkout_root(path: Path) -> Path | None:
    current = path.expanduser().resolve(strict=False)
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _repo_open_clone_owner(git_root: Path) -> Path | None:
    """Return the host checkout when *git_root* is a repo-open clone."""

    from sase._linked_repo_paths import (
        EXTERNAL_REPO_CLONES_SUBDIR,
        LINKED_REPO_CLONES_SUBDIR,
    )
    from sase.workspace_provider.marker import find_marker_from_cwd

    found = find_marker_from_cwd(str(git_root))
    if found is None:
        return None
    owner = Path(found[0]).expanduser().resolve(strict=False)
    resolved_root = git_root.expanduser().resolve(strict=False)
    for subdir in (EXTERNAL_REPO_CLONES_SUBDIR, LINKED_REPO_CLONES_SUBDIR):
        clone_root = owner.joinpath(*subdir)
        try:
            resolved_root.relative_to(clone_root)
        except ValueError:
            continue
        return owner
    return None
