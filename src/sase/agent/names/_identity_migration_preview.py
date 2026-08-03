"""Preview scanning for historical identity migration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_process_alive
from sase.agent.names._identity_migration import (
    AgentIdentityMigrationBlocker,
    AgentIdentityMigrationPreview,
    AgentIdentityMigrationRequest,
    AgentIdentityMigrationSkip,
)
from sase.agent.names._identity_migration_actions import (
    action_sort_key,
    add_derived_index_skips,
    artifact_actions,
    block_sort_key,
    bundle_actions,
    dedupe_actions,
    notification_actions,
    prompt_history_actions,
    registry_actions,
    skip_sort_key,
)
from sase.agent.names._identity_migration_chat_actions import (
    chat_actions,
    planned_chat_path_map,
)
from sase.agent.names._identity_migration_common import read_json_payload
from sase.agent.names._identity_migration_types import (
    AffectedArtifact,
    AffectedBundle,
    JsonPayload,
    RewriteContext,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity, globalize_agent_name
from sase.core.bead_prefix_migration import rewrite_id_tokens


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
_JSON_MARKER_NAMES = frozenset(
    {
        "agent_meta.json",
        "done.json",
        "ready.json",
        "running.json",
        "waiting.json",
        "workflow_state.json",
    }
)


def build_historical_agent_identity_migration_preview(
    req: AgentIdentityMigrationRequest,
) -> AgentIdentityMigrationPreview:
    bead_map = req.normalized_bead_map()
    blockers: list[AgentIdentityMigrationBlocker] = []
    skips: list[AgentIdentityMigrationSkip] = []
    _validate_mapping("bead_id_map", bead_map, blockers)

    affected_artifacts = _affected_artifacts(req.projects_path, bead_map, blockers)
    affected_bundles = _affected_bundles(req.state_path, bead_map, blockers)
    name_map = _derive_name_map(
        affected_artifacts,
        affected_bundles,
        bead_map,
        blockers,
    )
    _validate_mapping("agent_name_map", name_map, blockers, allow_empty=True)
    _validate_unaffected_name_collisions(
        req.projects_path,
        req.state_path,
        affected_artifacts,
        affected_bundles,
        name_map,
        blockers,
    )
    _validate_live_artifacts(affected_artifacts, blockers)

    owner = req.identity.owner if req.identity is not None else None
    global_name_map = _global_name_map(name_map, owner)
    chat_path_map = (
        planned_chat_path_map(req, affected_artifacts, affected_bundles, name_map)
        if req.include_chats and not blockers
        else {}
    )
    context = RewriteContext(bead_map, name_map, global_name_map, chat_path_map)

    actions = []
    if not blockers:
        actions.extend(artifact_actions(affected_artifacts, context, blockers=blockers))
        actions.extend(bundle_actions(affected_bundles, context, blockers=blockers))
        actions.extend(prompt_history_actions(req.state_path, context, blockers))
        actions.extend(notification_actions(req.state_path, context, blockers))
        if req.include_chats:
            actions.extend(
                chat_actions(
                    req,
                    affected_artifacts,
                    affected_bundles,
                    context,
                    blockers,
                    skips,
                )
            )
        actions.extend(registry_actions(req.state_path, context, blockers))
        add_derived_index_skips(req.state_path, skips)

    unique_actions = dedupe_actions(actions, blockers)
    return AgentIdentityMigrationPreview(
        request=req,
        bead_id_map=tuple(sorted(bead_map.items())),
        local_name_map=tuple(sorted(name_map.items())),
        global_name_map=tuple(sorted(global_name_map.items())),
        chat_path_map=tuple(sorted(chat_path_map.items())),
        actions=tuple(sorted(unique_actions, key=action_sort_key)),
        blockers=tuple(sorted(blockers, key=block_sort_key)),
        skips=tuple(sorted(skips, key=skip_sort_key)),
    )


def _validate_mapping(
    label: str,
    mapping: Mapping[str, str],
    blockers: list[AgentIdentityMigrationBlocker],
    *,
    allow_empty: bool = False,
) -> None:
    if not mapping:
        if allow_empty:
            return
        blockers.append(
            AgentIdentityMigrationBlocker("empty_mapping", f"{label} must not be empty")
        )
        return
    reverse: dict[str, str] = {}
    for source, destination in sorted(mapping.items()):
        if not source or not destination:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "invalid_mapping", f"{label} contains an empty identity"
                )
            )
            continue
        if source == destination:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "self_mapping",
                    f"{label} maps {source!r} to itself",
                )
            )
        previous = reverse.get(destination)
        if previous is not None and previous != source:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "noninjective_mapping",
                    f"{label} maps both {previous!r} and {source!r} to {destination!r}",
                )
            )
        reverse[destination] = source
    for source in sorted(mapping):
        seen: set[str] = set()
        current = source
        while current in mapping:
            if current in seen:
                blockers.append(
                    AgentIdentityMigrationBlocker(
                        "identity_cycle",
                        f"{label} contains a cycle through {current!r}",
                    )
                )
                break
            seen.add(current)
            current = mapping[current]


def _affected_artifacts(
    projects_root: Path,
    bead_map: Mapping[str, str],
    blockers: list[AgentIdentityMigrationBlocker],
) -> tuple[AffectedArtifact, ...]:
    result: list[AffectedArtifact] = []
    for artifact_dir in _iter_artifact_dirs(projects_root):
        primary = read_json_payload(artifact_dir / "agent_meta.json", required=False)
        done = read_json_payload(artifact_dir / "done.json", required=False)
        selected = (
            primary
            if primary is not None
            and _payload_has_affected_bead(primary.data, bead_map)
            else done
            if done is not None and _payload_has_affected_bead(done.data, bead_map)
            else None
        )
        if selected is None:
            continue
        payloads: list[JsonPayload] = []
        malformed = False
        for path in _artifact_structured_paths(artifact_dir):
            payload = read_json_payload(path, required=False, blockers=blockers)
            if payload is None:
                if path.is_file():
                    malformed = True
                continue
            payloads.append(payload)
        if malformed:
            continue
        result.append(
            AffectedArtifact(
                artifact_dir,
                selected,
                tuple(payloads),
                _payload_timestamps(
                    artifact_dir, *(payload.data for payload in payloads)
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: str(item.path)))


def _affected_bundles(
    state_root: Path,
    bead_map: Mapping[str, str],
    blockers: list[AgentIdentityMigrationBlocker],
) -> tuple[AffectedBundle, ...]:
    bundles_root = state_root / "dismissed_bundles"
    result: list[AffectedBundle] = []
    if not bundles_root.is_dir():
        return ()
    for path in sorted(bundles_root.rglob("*.json"), key=lambda item: str(item)):
        payload = read_json_payload(path, required=False, blockers=blockers)
        if payload is None:
            continue
        if not _payload_has_affected_bead(payload.data, bead_map):
            continue
        result.append(
            AffectedBundle(
                payload,
                _payload_timestamps(path, payload.data),
            )
        )
    return tuple(result)


def _iter_artifact_dirs(projects_root: Path) -> tuple[Path, ...]:
    if not projects_root.is_dir():
        return ()
    dirs: set[Path] = set()
    for marker in sorted(projects_root.glob("*/artifacts/*/**/*.json")):
        if marker.name in _JSON_MARKER_NAMES or marker.name.startswith("prompt_step_"):
            dirs.add(marker.parent)
    return tuple(sorted(dirs, key=lambda item: str(item)))


def _artifact_structured_paths(artifact_dir: Path) -> tuple[Path, ...]:
    paths = [artifact_dir / name for name in sorted(_JSON_MARKER_NAMES)]
    paths.extend(sorted(artifact_dir.glob("prompt_step_*.json"), key=lambda p: p.name))
    return tuple(paths)


def _payload_has_affected_bead(
    value: object,
    bead_map: Mapping[str, str],
    *,
    key: str | None = None,
) -> bool:
    if isinstance(value, dict):
        return any(
            _payload_has_affected_bead(item, bead_map, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(
            _payload_has_affected_bead(item, bead_map, key=key) for item in value
        )
    return key in _BEAD_KEYS and isinstance(value, str) and value in bead_map


def _derive_name_map(
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
    bead_map: Mapping[str, str],
    blockers: list[AgentIdentityMigrationBlocker],
) -> dict[str, str]:
    name_map: dict[str, str] = {}
    for payload in (
        *(item for artifact in artifacts for item in artifact.payloads),
        *(bundle.payload for bundle in bundles),
    ):
        for value in sorted(_collect_name_values(payload.data)):
            updated, _counts = _rewrite_text_tokens(value, bead_map)
            if updated == value:
                continue
            if _unsafe_identity(updated):
                blockers.append(
                    AgentIdentityMigrationBlocker(
                        "unsafe_agent_identity",
                        f"rewritten agent identity is unsafe: {updated!r}",
                        str(payload.path),
                    )
                )
                continue
            existing = name_map.get(value)
            if existing is not None and existing != updated:
                blockers.append(
                    AgentIdentityMigrationBlocker(
                        "conflicting_agent_mapping",
                        f"agent identity {value!r} maps to both {existing!r} "
                        f"and {updated!r}",
                        str(payload.path),
                    )
                )
                continue
            name_map[value] = updated
    return dict(sorted(name_map.items()))


def _collect_name_values(
    value: object,
    *,
    key: str | None = None,
) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        for item_key, item in value.items():
            names.update(_collect_name_values(item, key=str(item_key)))
        return names
    if isinstance(value, list):
        for item in value:
            names.update(_collect_name_values(item, key=key))
        return names
    if key in (_NAME_KEYS | _REF_KEYS) and isinstance(value, str) and value:
        names.add(value)
    return names


def _unsafe_identity(value: str) -> bool:
    return not value or "/" in value or "\\" in value or "\x00" in value


def _global_name_map(
    local_name_map: Mapping[str, str],
    owner: AgentOwnerIdentity | None,
) -> dict[str, str]:
    if owner is None:
        return {}
    result: dict[str, str] = {}
    prefix = f"{owner.username}.{owner.machine_name}."
    for old, new in local_name_map.items():
        if old.startswith(prefix) or new.startswith(prefix):
            result[old] = new
            continue
        try:
            result[globalize_agent_name(old, owner)] = globalize_agent_name(new, owner)
        except Exception:
            continue
    return dict(sorted(result.items()))


def _validate_unaffected_name_collisions(
    projects_root: Path,
    state_root: Path,
    artifacts: tuple[AffectedArtifact, ...],
    bundles: tuple[AffectedBundle, ...],
    name_map: Mapping[str, str],
    blockers: list[AgentIdentityMigrationBlocker],
) -> None:
    if not name_map:
        return
    affected_paths = {artifact.path for artifact in artifacts}
    affected_paths.update(bundle.payload.path for bundle in bundles)
    affected_old_names = set(name_map)
    existing: dict[str, str] = {}
    for artifact_dir in _iter_artifact_dirs(projects_root):
        if artifact_dir in affected_paths:
            continue
        for marker in (artifact_dir / "agent_meta.json", artifact_dir / "done.json"):
            payload = read_json_payload(marker, required=False)
            if payload is None:
                continue
            for name in _collect_name_values(payload.data):
                existing.setdefault(name, str(marker))
    bundles_root = state_root / "dismissed_bundles"
    if bundles_root.is_dir():
        for path in sorted(bundles_root.rglob("*.json"), key=lambda item: str(item)):
            if path in affected_paths:
                continue
            payload = read_json_payload(path, required=False)
            if payload is None:
                continue
            for name in _collect_name_values(payload.data):
                existing.setdefault(name, str(path))
    for destination in sorted(set(name_map.values())):
        if destination in affected_old_names:
            continue
        existing_path = existing.get(destination)
        if existing_path is None:
            continue
        blockers.append(
            AgentIdentityMigrationBlocker(
                "destination_identity_collision",
                f"destination agent identity {destination!r} already exists",
                existing_path,
            )
        )


def _validate_live_artifacts(
    artifacts: tuple[AffectedArtifact, ...],
    blockers: list[AgentIdentityMigrationBlocker],
) -> None:
    for artifact in artifacts:
        if (artifact.path / "done.json").is_file():
            continue
        meta_payload = next(
            (
                payload
                for payload in artifact.payloads
                if payload.path.name == "agent_meta.json"
            ),
            None,
        )
        if meta_payload is None:
            continue
        if (
            is_process_alive(meta_payload.data, artifact.path)
            or (artifact.path / "running.json").is_file()
        ):
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "affected_live_agent",
                    f"affected agent appears live: {artifact.path}",
                    str(artifact.path),
                )
            )


def _rewrite_text_tokens(
    text: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    if not replacements:
        return text, {}
    outcome = rewrite_id_tokens(text, dict(replacements))
    return outcome.text, outcome.replacement_counts


def _payload_timestamps(source: Path, *payloads: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = [source.name]
    for payload in payloads:
        for key in (
            "artifact_agent_id",
            "artifacts_timestamp",
            "raw_suffix",
            "start_time",
            "timestamp",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(dict.fromkeys(values))
