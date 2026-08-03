"""Action planning for persisted identity migration data."""

from __future__ import annotations

import json
from pathlib import Path

from sase.agent.names._identity_migration import (
    AgentIdentityMigrationBlocker,
    AgentIdentityMigrationFileAction,
    AgentIdentityMigrationSkip,
)
from sase.agent.names._identity_migration_common import (
    json_bytes,
    merge_counts,
    read_json_payload,
    write_action,
)
from sase.agent.names._identity_migration_rewrites import (
    contains_any_old_token,
    rewrite_json_payload,
    rewrite_prompt_references,
    rewrite_text_tokens,
)
from sase.agent.names._identity_migration_types import (
    AffectedArtifact,
    AffectedBundle,
    RewriteContext,
)


def artifact_actions(
    artifacts: tuple[AffectedArtifact, ...],
    context: RewriteContext,
    *,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    actions: list[AgentIdentityMigrationFileAction] = []
    for artifact in artifacts:
        for payload in artifact.payloads:
            updated, counts = rewrite_json_payload(payload.data, context)
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
        updated, counts = rewrite_json_payload(bundle.payload.data, context)
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
                new_text, text_counts = rewrite_prompt_references(text, context)
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
            if contains_any_old_token(line, context):
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
        updated, line_counts = rewrite_json_payload(data, context)
        if updated != data:
            changed = True
            merge_counts(counts, line_counts)
            lines.append(json.dumps(updated, sort_keys=True))
        else:
            lines.append(line)
    if not changed:
        return []
    return [write_action(path, preimage, ("\n".join(lines) + "\n").encode(), counts)]


def registry_actions(
    state_root: Path,
    context: RewriteContext,
    blockers: list[AgentIdentityMigrationBlocker],
) -> list[AgentIdentityMigrationFileAction]:
    path = state_root / "agent_name_registry.json"
    payload = read_json_payload(path, required=False, blockers=blockers)
    if payload is None:
        return []
    updated, counts = rewrite_json_payload(payload.data, context, rewrite_keys=True)
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
        updated, counts = rewrite_prompt_references(text, context)
    else:
        updated, counts = rewrite_text_tokens(text, context.all_text_replacements)
    postimage = updated.encode("utf-8")
    if postimage == preimage:
        return []
    return [write_action(path, preimage, postimage, counts)]


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
