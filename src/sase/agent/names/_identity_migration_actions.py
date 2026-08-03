"""Action planning and text rewrites for identity migration."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any

from sase.agent.names._identity_migration import (
    AgentIdentityMigrationBlocker,
    AgentIdentityMigrationFileAction,
    AgentIdentityMigrationRequest,
    AgentIdentityMigrationSkip,
)
from sase.agent.names._identity_migration_common import (
    counts_tuple,
    json_bytes,
    merge_counts,
    read_json_payload,
    sha256,
    write_action,
)
from sase.agent.names._identity_migration_types import (
    AffectedArtifact,
    AffectedBundle,
    RewriteContext,
)
from sase.core.bead_prefix_migration import rewrite_id_tokens
from sase.core.paths import make_safe_filename


_BEAD_KEYS = frozenset({"bead_id", "epic_bead_id", "phase_bead_id"})
_NAME_KEYS = frozenset(
    {
        "agent_clan",
        "agent_family",
        "agent_name",
        "canonical_global_name",
        "cl_name",
        "global_name",
        "local_name",
        "name",
        "parent_agent_name",
        "source_agent_name",
        "target_agent_name",
        "workflow_name",
    }
)
_REF_KEYS = frozenset(
    {
        "agent_names",
        "family_name",
        "lane_name",
        "member_name",
        "source_global_name",
        "target_global_name",
        "wait_for",
        "waiting_for",
    }
)
_PATH_KEYS = frozenset({"chat_path", "response_path"})
_PROMPT_DIRECTIVE_RE = r"(?:%id|%name|%n|%w|%wait|#fork|#resume)"
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


def artifact_actions(
    artifacts: tuple[AffectedArtifact, ...],
    context: RewriteContext,
    *,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    actions: list[AgentIdentityMigrationFileAction] = []
    for artifact in artifacts:
        for payload in artifact.payloads:
            updated, counts = _rewrite_json_payload(payload.data, context)
            if updated == payload.data:
                continue
            actions.append(
                write_action(
                    payload.path,
                    payload.preimage,
                    json_bytes(updated),
                    counts,
                )
            )
        prompt = artifact.path / "raw_xprompt.md"
        if prompt.is_file():
            actions.extend(
                _text_file_action(
                    prompt,
                    context,
                    prompt_directives=True,
                    blockers=blockers,
                )
            )
    return actions


def bundle_actions(
    bundles: tuple[AffectedBundle, ...],
    context: RewriteContext,
    *,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    del blockers
    actions: list[AgentIdentityMigrationFileAction] = []
    for bundle in bundles:
        updated, counts = _rewrite_json_payload(bundle.payload.data, context)
        if updated != bundle.payload.data:
            actions.append(
                write_action(
                    bundle.payload.path,
                    bundle.payload.preimage,
                    json_bytes(updated),
                    counts,
                )
            )
    return actions


def prompt_history_actions(
    state_root: Path,
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    actions: list[AgentIdentityMigrationFileAction] = []
    for path in _prompt_history_paths(state_root):
        payload = read_json_payload(path, required=False, blockers=blockers)
        if payload is None:
            continue
        prompts = payload.data.get("prompts")
        if not isinstance(prompts, list):
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "malformed_prompt_history",
                    "prompt history must contain a prompts list",
                    str(path),
                )
            )
            continue
        updated = dict(payload.data)
        changed = False
        counts: dict[str, int] = {}
        new_prompts: list[object] = []
        for entry in prompts:
            if not isinstance(entry, dict):
                new_prompts.append(entry)
                continue
            row = dict(entry)
            text = row.get("text")
            if isinstance(text, str):
                new_text, text_counts = _rewrite_prompt_references(text, context)
                if new_text != text:
                    row["text"] = new_text
                    merge_counts(counts, text_counts)
                    changed = True
            new_prompts.append(row)
        if changed:
            updated["prompts"] = new_prompts
            actions.append(
                write_action(path, payload.preimage, json_bytes(updated), counts)
            )
    return actions


def _prompt_history_paths(state_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    legacy = state_root / "prompt_history.json"
    if legacy.is_file():
        paths.append(legacy)
    shards = state_root / "prompt_history"
    if shards.is_dir():
        paths.extend(sorted(shards.glob("*.json"), key=lambda item: str(item)))
    return tuple(dict.fromkeys(paths))


def notification_actions(
    state_root: Path,
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    path = state_root / "notifications" / "notifications.jsonl"
    if not path.is_file():
        return []
    try:
        preimage = path.read_bytes()
    except OSError as exc:
        blockers.append(
            AgentIdentityMigrationBlocker(
                "unreadable_notifications",
                f"could not read notifications: {exc}",
                str(path),
            )
        )
        return []
    changed = False
    counts: dict[str, int] = {}
    lines: list[str] = []
    for line in preimage.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            lines.append(line)
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            if _contains_any_old_token(line, context):
                blockers.append(
                    AgentIdentityMigrationBlocker(
                        "malformed_notification",
                        f"affected notification line is malformed: {exc}",
                        str(path),
                    )
                )
            lines.append(line)
            continue
        if not isinstance(data, dict):
            lines.append(line)
            continue
        updated, line_counts = _rewrite_json_payload(data, context)
        if updated != data:
            changed = True
            merge_counts(counts, line_counts)
            lines.append(json.dumps(updated, sort_keys=True))
        else:
            lines.append(line)
    if not changed:
        return []
    return [write_action(path, preimage, ("\n".join(lines) + "\n").encode(), counts)]


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
    updated, counts = _rewrite_text_tokens(text, context.all_text_replacements)
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
        if _contains_any_old_token(text, context):
            skips.append(
                AgentIdentityMigrationSkip(
                    "uncataloged_chat",
                    "chat mentions an old identity but is not cataloged to an "
                    "affected run",
                    str(path),
                )
            )


def registry_actions(
    state_root: Path,
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    path = state_root / "agent_name_registry.json"
    payload = read_json_payload(path, required=False, blockers=blockers)
    if payload is None:
        return []
    updated, counts = _rewrite_json_payload(payload.data, context, rewrite_keys=True)
    if updated == payload.data:
        return []
    return [write_action(path, payload.preimage, json_bytes(updated), counts)]


def add_derived_index_skips(
    state_root: Path, skips: list[AgentIdentityMigrationSkip]
) -> None:
    for path in (
        state_root / "agent_artifact_index.sqlite",
        state_root / "dismissed_bundles" / "index.sqlite",
    ):
        if path.is_file():
            skips.append(
                AgentIdentityMigrationSkip(
                    "derived_index_regeneration_required",
                    "derived index is not patched by preview; apply regenerates "
                    "production projections when operating on the active SASE home",
                    str(path),
                )
            )


def _text_file_action(
    path: Path,
    context: RewriteContext,
    *,
    prompt_directives: bool,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    try:
        preimage = path.read_bytes()
        text = preimage.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        blockers.append(
            AgentIdentityMigrationBlocker(
                "unreadable_text",
                f"could not read text file {path}: {exc}",
                str(path),
            )
        )
        return []
    if prompt_directives:
        updated, counts = _rewrite_prompt_references(text, context)
    else:
        updated, counts = _rewrite_text_tokens(text, context.all_text_replacements)
    postimage = updated.encode("utf-8")
    if postimage == preimage:
        return []
    return [write_action(path, preimage, postimage, counts)]


def _rewrite_json_payload(
    data: dict[str, Any],
    context: RewriteContext,
    *,
    rewrite_keys: bool = False,
) -> tuple[dict[str, Any], dict[str, int]]:
    counts: dict[str, int] = {}
    rewritten = _rewrite_json_value(
        data, context, counts, key=None, rewrite_keys=rewrite_keys
    )
    assert isinstance(rewritten, dict)
    return rewritten, counts


def _rewrite_json_value(
    value: Any,
    context: RewriteContext,
    counts: dict[str, int],
    *,
    key: str | None,
    rewrite_keys: bool,
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for item_key, item in value.items():
            new_key = str(item_key)
            if rewrite_keys:
                new_key, key_counts = _rewrite_text_tokens(
                    new_key, context.all_text_replacements
                )
                merge_counts(counts, key_counts)
            result[new_key] = _rewrite_json_value(
                item,
                context,
                counts,
                key=str(item_key),
                rewrite_keys=rewrite_keys,
            )
        return result
    if isinstance(value, list):
        return [
            _rewrite_json_value(
                item, context, counts, key=key, rewrite_keys=rewrite_keys
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value
    if key in _PATH_KEYS and value:
        replacement = context.chat_path_map.get(value)
        replacement = replacement or context.chat_path_map.get(
            str(Path(value).expanduser())
        )
        if replacement is not None:
            merge_counts(counts, {value: 1})
            return replacement
        return value
    replacements: Mapping[str, str] | None = None
    if key in _BEAD_KEYS:
        replacements = context.bead_map
    elif key in (_NAME_KEYS | _REF_KEYS):
        replacements = context.all_text_replacements
    if replacements is None:
        return value
    updated, text_counts = _rewrite_structured_string(value, replacements)
    merge_counts(counts, text_counts)
    return updated


def _rewrite_structured_string(
    value: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    exact = replacements.get(value)
    if exact is not None:
        return exact, {value: 1}
    return _rewrite_text_tokens(value, replacements)


def _path_value_with_replaced_basename(original: str, replacement_path: str) -> str:
    return str(Path(original).with_name(Path(replacement_path).name))


def _rewrite_prompt_references(
    text: str,
    context: RewriteContext,
) -> tuple[str, dict[str, int]]:
    replacements = context.all_text_replacements
    if not replacements or not any(
        token in text
        for token in ("%id", "%name", "%n", "%w", "%wait", "#fork", "#resume")
    ):
        return text, {}
    counts: dict[str, int] = {}

    def replace_quoted_colon(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}`{arg}`"

    def replace_colon(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}{arg}"

    def replace_paren(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}{arg})"

    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}:)`(?P<arg>[^`]+)`",
        replace_quoted_colon,
        text,
    )
    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}:)(?P<arg>[^`\s)]+)",
        replace_colon,
        updated,
    )
    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}\()(?P<arg>[^)]*)\)",
        replace_paren,
        updated,
    )
    return updated, counts


def _rewrite_ref_arg(
    arg: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    parts = arg.split(",")
    out: list[str] = []
    for part in parts:
        leading_len = len(part) - len(part.lstrip())
        trailing_len = len(part) - len(part.rstrip())
        leading = part[:leading_len]
        trailing = part[len(part) - trailing_len :] if trailing_len else ""
        core = part.strip()
        updated, item_counts = _rewrite_structured_string(core, replacements)
        merge_counts(counts, item_counts)
        out.append(f"{leading}{updated}{trailing}")
    return ",".join(out), counts


def _rewrite_text_tokens(
    text: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    if not replacements:
        return text, {}
    outcome = rewrite_id_tokens(text, dict(replacements))
    return outcome.text, outcome.replacement_counts


def _contains_any_old_token(text: str, context: RewriteContext) -> bool:
    return any(token in text for token in context.all_text_replacements)


def dedupe_actions(
    actions: list[AgentIdentityMigrationFileAction],
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    by_key: dict[tuple[str, str, str | None], AgentIdentityMigrationFileAction] = {}
    for action in actions:
        key = (action.kind, action.source_path, action.destination_path)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = action
            continue
        if previous.postimage_bytes != action.postimage_bytes:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "conflicting_file_action",
                    f"conflicting planned actions for {action.source_path}",
                    action.source_path,
                )
            )
    return list(by_key.values())


def action_sort_key(
    action: AgentIdentityMigrationFileAction,
) -> tuple[str, str, str]:
    return (action.path, action.kind, action.source_path)


def block_sort_key(blocker: AgentIdentityMigrationBlocker) -> tuple[str, str, str]:
    return (blocker.path or "", blocker.code, blocker.message)


def skip_sort_key(skip: AgentIdentityMigrationSkip) -> tuple[str, str, str]:
    return (skip.path or "", skip.code, skip.message)
