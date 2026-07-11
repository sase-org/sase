"""Migration from top-level prompt roots into plan month directories."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields


@dataclass(frozen=True)
class _PromptMigrationAction:
    source: Path
    destination: Path
    new_content: str | None
    warning: str | None = None


@dataclass(frozen=True)
class _PromptMigrationResult:
    moved: tuple[Path, ...]
    changed: tuple[Path, ...]
    warnings: tuple[str, ...]


def plan_legacy_prompt_migration(
    sdd_root: Path,
) -> tuple[_PromptMigrationAction, ...]:
    """Return deterministic, collision-safe legacy prompt migration actions."""
    reserved = {
        path.resolve()
        for path in (sdd_root / "plans").glob("*/prompts/*.md")
        if path.is_file()
    }
    actions: list[_PromptMigrationAction] = []
    for dirname in ("prompts", "specs"):
        root = sdd_root / dirname
        if not root.is_dir():
            continue
        for source in sorted(path for path in root.glob("**/*.md") if path.is_file()):
            try:
                stat = source.stat()
                content = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                actions.append(
                    _PromptMigrationAction(
                        source=source,
                        destination=source,
                        new_content=None,
                        warning=f"skipping unreadable prompt {source}: {exc}",
                    )
                )
                continue

            relative = source.relative_to(root)
            shard = (
                relative.parts[0]
                if len(relative.parts) > 1
                else datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m")
            )
            destination = _deduplicated_destination(
                sdd_root / "plans" / shard / "prompts" / source.name,
                reserved,
            )
            reserved.add(destination.resolve())
            actions.append(
                _PromptMigrationAction(
                    source=source,
                    destination=destination,
                    new_content=content,
                )
            )
    return tuple(actions)


def migrate_legacy_prompt_directories(sdd_root: Path) -> _PromptMigrationResult:
    """Move legacy prompt files and rewrite persisted prompt references."""
    actions = plan_legacy_prompt_migration(sdd_root)
    path_map: dict[str, str] = {}
    moved: list[Path] = []
    changed: list[Path] = []
    warnings = [action.warning for action in actions if action.warning]
    for action in actions:
        if action.source == action.destination or action.new_content is None:
            continue
        old_rel = action.source.relative_to(sdd_root).as_posix()
        new_rel = action.destination.relative_to(sdd_root).as_posix()
        try:
            action.destination.parent.mkdir(parents=True, exist_ok=True)
            _move(action.source, action.destination, sdd_root)
        except OSError as exc:
            warnings.append(f"could not migrate {action.source}: {exc}")
            continue
        path_map[old_rel] = new_rel
        moved.append(action.destination)
        # Targeted SDD commits need both sides of a rename. The source no
        # longer exists, but passing it as a pathspec lets the commit helper
        # discover and stage the deletion alongside the new destination.
        changed.append(action.source)

    if path_map:
        changed.extend(_rewrite_prompt_links(sdd_root, path_map, warnings))
    _cleanup_legacy_directories(sdd_root)
    return _PromptMigrationResult(
        moved=tuple(moved),
        changed=tuple(dict.fromkeys(changed)),
        warnings=tuple(warning for warning in warnings if warning),
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
            # ``git mv`` stages immediately, while targeted SDD commits discover
            # and stage only their explicit path scope. Put this move back into
            # the working tree so both source deletion and destination file are
            # included by that normal commit path.
            relative_source = source.resolve().relative_to(repo.resolve())
            relative_destination = destination.resolve().relative_to(repo.resolve())
            subprocess.run(
                [
                    "git",
                    "reset",
                    "--",
                    relative_source.as_posix(),
                    relative_destination.as_posix(),
                ],
                cwd=repo,
                check=False,
                capture_output=True,
            )
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
    for dirname in ("plans", "legends", "myths", "research"):
        for path in sorted((sdd_root / dirname).glob("**/*.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            frontmatter, _, had_frontmatter = parse_frontmatter(content)
            if not had_frontmatter or not isinstance(frontmatter.get("prompt"), str):
                continue
            old = str(frontmatter["prompt"])
            new = _rewrite_reference(old, path_map)
            if new == old:
                continue
            try:
                path.write_text(
                    set_frontmatter_fields(content, {"prompt": new}), encoding="utf-8"
                )
            except OSError as exc:
                warnings.append(f"could not rewrite prompt link in {path}: {exc}")
                continue
            changed.append(path)
    return changed


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


def _cleanup_legacy_directories(sdd_root: Path) -> None:
    for dirname in ("prompts", "specs"):
        root = sdd_root / dirname
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
