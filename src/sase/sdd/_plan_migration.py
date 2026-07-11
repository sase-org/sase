"""Migration from legacy ``tales/`` and ``epics/`` into ``plans/``."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
from sase.sdd.plan_tiers import normalize_plan_tier, read_plan_frontmatter


@dataclass(frozen=True)
class _PlanMigrationAction:
    source: Path
    destination: Path
    new_content: str | None
    warning: str | None = None
    remove_source_only: bool = False


@dataclass(frozen=True)
class _PlanMigrationResult:
    moved: tuple[Path, ...]
    removed: tuple[Path, ...]
    changed: tuple[Path, ...]
    warnings: tuple[str, ...]


def plan_legacy_plan_migration(sdd_root: Path) -> tuple[_PlanMigrationAction, ...]:
    """Return deterministic, collision-safe legacy plan migration actions."""
    reserved = {
        path.resolve()
        for path in (sdd_root / "plans").glob("**/*.md")
        if path.is_file()
    }
    actions: list[_PlanMigrationAction] = []
    for legacy_dir, fallback_tier in (("tales", "tale"), ("epics", "epic")):
        root = sdd_root / legacy_dir
        if not root.is_dir():
            continue
        paths = sorted(
            path for path in root.glob("**/*.md") if path.name != "README.md"
        )
        for source in paths:
            try:
                stat = source.stat()
                content = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                actions.append(
                    _PlanMigrationAction(
                        source=source,
                        destination=source,
                        new_content=None,
                        warning=f"skipping unreadable plan {source}: {exc}",
                    )
                )
                continue
            relative = source.relative_to(root)
            if len(relative.parts) == 1:
                shard = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m")
                relative = Path(shard) / relative
            frontmatter, parse_error = read_plan_frontmatter(source)
            if parse_error is not None:
                new_content = content
                warning = f"moved {source} without frontmatter changes: {parse_error}"
            else:
                tier = normalize_plan_tier(frontmatter.get("tier")) or fallback_tier
                fields: dict[str, str] = {"tier": tier}
                if not frontmatter.get("create_time"):
                    fields["create_time"] = datetime.fromtimestamp(
                        stat.st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S")
                new_content = set_frontmatter_fields(content, fields)
                warning = None

            canonical_destination = sdd_root / "plans" / relative
            matching_destination = _matching_destination(
                canonical_destination,
                new_content,
                ignore_create_time=not bool(frontmatter.get("create_time")),
            )
            if matching_destination is not None:
                destination = matching_destination
            else:
                destination = _deduplicated_destination(canonical_destination, reserved)
                reserved.add(destination.resolve())
            actions.append(
                _PlanMigrationAction(
                    source=source,
                    destination=destination,
                    new_content=new_content,
                    warning=warning,
                    remove_source_only=matching_destination is not None,
                )
            )
    return tuple(actions)


def migrate_legacy_plan_directories(sdd_root: Path) -> _PlanMigrationResult:
    """Apply the legacy plan migration and repair persisted path references."""
    actions = plan_legacy_plan_migration(sdd_root)
    path_map: dict[str, str] = {}
    moved: list[Path] = []
    removed: list[Path] = []
    changed: list[Path] = []
    warnings = [action.warning for action in actions if action.warning]
    for action in actions:
        if action.source == action.destination or action.new_content is None:
            continue
        old_rel = action.source.relative_to(sdd_root).as_posix()
        new_rel = action.destination.relative_to(sdd_root).as_posix()
        try:
            if action.remove_source_only:
                action.source.unlink()
            else:
                action.destination.parent.mkdir(parents=True, exist_ok=True)
                if action.source.read_text(encoding="utf-8") != action.new_content:
                    action.source.write_text(action.new_content, encoding="utf-8")
                _move(action.source, action.destination, sdd_root)
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not migrate {action.source}: {exc}")
            continue
        path_map[old_rel] = new_rel
        if not action.remove_source_only:
            moved.append(action.destination)
        removed.append(action.source)

    if path_map:
        changed.extend(_rewrite_prompt_links(sdd_root, path_map, warnings))
        changed.extend(_rewrite_bead_designs(sdd_root, path_map, warnings))
    changed.extend(_cleanup_legacy_directories(sdd_root))
    return _PlanMigrationResult(
        moved=tuple(moved),
        removed=tuple(removed),
        changed=tuple(dict.fromkeys(changed)),
        warnings=tuple(warning for warning in warnings if warning),
    )


def legacy_readme_paths(sdd_root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (sdd_root / "tales" / "README.md", sdd_root / "epics" / "README.md")
        if path.exists()
    )


def _deduplicated_destination(destination: Path, reserved: set[Path]) -> Path:
    candidate = destination
    suffix = 1
    while candidate.resolve() in reserved or candidate.exists():
        candidate = destination.with_name(
            f"{destination.stem}_{suffix}{destination.suffix}"
        )
        suffix += 1
    return candidate


def _matching_destination(
    destination: Path,
    expected: str,
    *,
    ignore_create_time: bool,
) -> Path | None:
    candidates = [
        destination,
        *sorted(destination.parent.glob(f"{destination.stem}_*{destination.suffix}")),
    ]
    return next(
        (
            candidate
            for candidate in candidates
            if _content_matches(
                candidate,
                expected,
                ignore_create_time=ignore_create_time,
            )
        ),
        None,
    )


def _content_matches(
    path: Path,
    expected: str,
    *,
    ignore_create_time: bool,
) -> bool:
    try:
        if not path.is_file():
            return False
        actual = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if actual == expected:
        return True
    if not ignore_create_time:
        return False
    actual_frontmatter, actual_body, actual_valid = parse_frontmatter(actual)
    expected_frontmatter, expected_body, expected_valid = parse_frontmatter(expected)
    if not actual_valid or not expected_valid:
        return False
    actual_frontmatter.pop("create_time", None)
    expected_frontmatter.pop("create_time", None)
    return actual_frontmatter == expected_frontmatter and actual_body == expected_body


def _move(source: Path, destination: Path, sdd_root: Path) -> None:
    repo = _git_root(sdd_root)
    if repo is not None:
        result = subprocess.run(
            ["git", "mv", str(source), str(destination)],
            cwd=repo,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return
    source.rename(destination)


def _git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def _rewrite_prompt_links(
    sdd_root: Path, path_map: dict[str, str], warnings: list[str]
) -> list[Path]:
    changed: list[Path] = []
    for directory in ("prompts", "specs"):
        for path in sorted((sdd_root / directory).glob("**/*.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            frontmatter, error = read_plan_frontmatter(path)
            if error is not None or not isinstance(frontmatter.get("plan"), str):
                continue
            old = str(frontmatter["plan"])
            new = _rewrite_reference(old, path_map)
            if new == old:
                continue
            try:
                path.write_text(
                    set_frontmatter_fields(content, {"plan": new}), encoding="utf-8"
                )
            except OSError as exc:
                warnings.append(f"could not rewrite plan link in {path}: {exc}")
                continue
            changed.append(path)
    return changed


def _rewrite_bead_designs(
    sdd_root: Path, path_map: dict[str, str], warnings: list[str]
) -> list[Path]:
    beads_dir = sdd_root / "beads"
    if not beads_dir.is_dir():
        return []
    try:
        from sase.bead.project import BeadProject
        from sase.core import bead_mutation_facade as rust_beads

        project_root = sdd_root if (sdd_root / ".git").is_dir() else sdd_root.parent
        beads_dirname = (
            "beads" if project_root == sdd_root else f"{sdd_root.name}/beads"
        )
        with BeadProject(project_root, beads_dirname=beads_dirname) as project:
            updated = False
            for issue in project.list_issues():
                if not issue.design:
                    continue
                rewritten = _rewrite_reference(issue.design, path_map)
                if rewritten != issue.design:
                    rust_beads.update(project.beads_dir, issue.id, design=rewritten)
                    updated = True
            if updated:
                project._refresh_db_from_jsonl()
        return [beads_dir]
    except Exception as exc:
        warnings.append(f"could not rewrite bead design paths: {exc}")
        return []


def _rewrite_reference(value: str, path_map: dict[str, str]) -> str:
    normalized = value.replace(os.sep, "/")
    for old, new in path_map.items():
        for prefix in ("", "sdd/", ".sase/sdd/"):
            old_value = f"{prefix}{old}"
            if normalized == old_value:
                return f"{prefix}{new}"
        if normalized.endswith(f"/{old}"):
            return normalized[: -len(old)] + new
    return value


def _cleanup_legacy_directories(sdd_root: Path) -> list[Path]:
    changed: list[Path] = []
    for dirname in ("tales", "epics"):
        root = sdd_root / dirname
        readme = root / "README.md"
        if readme.exists():
            try:
                readme.unlink()
                changed.append(readme)
            except OSError:
                pass
        if not root.is_dir():
            continue
        for directory in sorted(
            (path for path in root.glob("**/*") if path.is_dir()), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass
    return changed
