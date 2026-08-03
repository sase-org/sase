"""Chat discovery and action planning for identity migration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re

from sase.agent.names._identity_migration import (
    AgentIdentityMigrationBlocker,
    AgentIdentityMigrationFileAction,
    AgentIdentityMigrationRequest,
    AgentIdentityMigrationSkip,
)
from sase.agent.names._identity_migration_common import (
    counts_tuple,
    sha256,
    write_action,
)
from sase.agent.names._identity_migration_rewrites import (
    contains_any_old_token,
    rewrite_text_tokens,
)
from sase.agent.names._identity_migration_types import (
    AffectedArtifact,
    AffectedBundle,
    RewriteContext,
)
from sase.core.paths import make_safe_filename


_PATH_KEYS = frozenset({"chat_path", "response_path"})
_CHAT_HEADER_RE = re.compile(
    r"^#\s+Chat History\s*-\s*(?P<workflow>\S+?)(?:\s+\((?P<agent>[^)]+)\))?\s*$",
    re.MULTILINE,
)


def planned_chat_path_map(
    request: AgentIdentityMigrationRequest,
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
    name_map: Mapping[str, str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_path in _selected_raw_chat_paths(artifacts, bundles):
        path = _expand_state_path(raw_path, request.state_path)
        new_path = _renamed_chat_path(path, name_map)
        if new_path != path:
            result[raw_path] = _path_value_with_replaced_basename(
                raw_path,
                str(new_path),
            )
            result[str(path)] = str(new_path)
    for path in _iter_chat_files(request.state_path):
        if not _chat_metadata_matches(path, name_map):
            continue
        new_path = _renamed_chat_path(path, name_map)
        if new_path != path:
            result[str(path)] = str(new_path)
    return dict(sorted(result.items()))


def chat_actions(
    request: AgentIdentityMigrationRequest,
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
    skips: list[AgentIdentityMigrationSkip],
) -> list[AgentIdentityMigrationFileAction]:
    actions: list[AgentIdentityMigrationFileAction] = []
    selected = _selected_chat_paths(request, artifacts, bundles, context.local_name_map)
    for path in selected:
        if not path.is_file():
            skips.append(
                AgentIdentityMigrationSkip(
                    "missing_cataloged_chat",
                    f"cataloged chat path does not exist: {path}",
                    str(path),
                )
            )
            continue
        actions.extend(_chat_action(path, context, blockers))
    _add_uncataloged_chat_skips(request.state_path, selected, context, skips)
    return actions


def _selected_chat_paths(
    request: AgentIdentityMigrationRequest,
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
    name_map: Mapping[str, str],
) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for raw_path in _selected_raw_chat_paths(artifacts, bundles):
        paths.add(_expand_state_path(raw_path, request.state_path))
    for path in _iter_chat_files(request.state_path):
        if _chat_metadata_matches(path, name_map):
            paths.add(path)
    return tuple(sorted(paths, key=lambda item: str(item)))


def _selected_raw_chat_paths(
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
) -> tuple[str, ...]:
    paths: set[str] = set()
    for payload in (
        *(item for artifact in artifacts for item in artifact.payloads),
        *(bundle.payload for bundle in bundles),
    ):
        paths.update(_collect_chat_paths(payload.data))
    return tuple(sorted(paths))


def _collect_chat_paths(value: object, *, key: str | None = None) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for item_key, item in value.items():
            paths.update(_collect_chat_paths(item, key=str(item_key)))
        return paths
    if isinstance(value, list):
        for item in value:
            paths.update(_collect_chat_paths(item, key=key))
        return paths
    if key in _PATH_KEYS and isinstance(value, str) and value:
        paths.add(value)
    return paths


def _expand_state_path(value: str, state_root: Path) -> Path:
    if value.startswith("~/.sase/"):
        return state_root / value.removeprefix("~/.sase/")
    return Path(value).expanduser()


def _iter_chat_files(state_root: Path) -> tuple[Path, ...]:
    chats = state_root / "chats"
    if not chats.is_dir():
        return ()
    return tuple(sorted((p for p in chats.rglob("*.md") if p.is_file()), key=str))


def _chat_metadata_matches(path: Path, name_map: Mapping[str, str]) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:8192]
    except OSError:
        return False
    header = _CHAT_HEADER_RE.search(head)
    if header is not None and header.group("agent") in name_map:
        return True
    safe_old_names = {make_safe_filename(name) for name in name_map}
    return any(token and token in path.stem for token in safe_old_names)


def _chat_action(
    path: Path,
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    try:
        preimage = path.read_bytes()
        text = preimage.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        blockers.append(
            AgentIdentityMigrationBlocker(
                "unreadable_chat",
                f"could not read chat transcript {path}: {exc}",
                str(path),
            )
        )
        return []
    updated, counts = rewrite_text_tokens(text, context.all_text_replacements)
    postimage = updated.encode("utf-8")
    destination = _renamed_chat_path(path, context.local_name_map)
    if destination != path and destination.exists():
        try:
            existing = destination.read_bytes()
        except OSError as exc:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "chat_destination_unreadable",
                    f"could not read existing chat destination {destination}: {exc}",
                    str(destination),
                )
            )
            return []
        if existing != postimage:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "chat_destination_collision",
                    f"chat destination already exists with different bytes: {destination}",
                    str(destination),
                )
            )
            return []
        return []
    if destination != path:
        return [
            AgentIdentityMigrationFileAction(
                "rename",
                str(path),
                str(destination),
                sha256(preimage),
                sha256(postimage),
                counts_tuple(counts),
                postimage,
            )
        ]
    if postimage != preimage:
        return [write_action(path, preimage, postimage, counts)]
    return []


def _renamed_chat_path(path: Path, name_map: Mapping[str, str]) -> Path:
    name = path.name
    updated = name
    for old, new in sorted(
        name_map.items(), key=lambda item: len(item[0]), reverse=True
    ):
        updated = updated.replace(make_safe_filename(old), make_safe_filename(new))
        updated = updated.replace(old, new)
    return path.with_name(updated)


def _add_uncataloged_chat_skips(
    state_root: Path,
    selected: tuple[Path, ...],
    context: RewriteContext,
    skips: list[AgentIdentityMigrationSkip],
) -> None:
    selected_set = {path.resolve(strict=False) for path in selected}
    for path in _iter_chat_files(state_root):
        if path.resolve(strict=False) in selected_set:
            continue
        try:
            text = path.read_text(encoding="utf-8")[:8192]
        except OSError:
            continue
        if contains_any_old_token(text, context):
            skips.append(
                AgentIdentityMigrationSkip(
                    "uncataloged_chat",
                    "chat mentions an old identity but is not cataloged to an "
                    "affected run",
                    str(path),
                )
            )


def _path_value_with_replaced_basename(original: str, replacement_path: str) -> str:
    return str(Path(original).with_name(Path(replacement_path).name))
