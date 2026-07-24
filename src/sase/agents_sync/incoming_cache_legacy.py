"""Legacy-v1 grouping and identity helpers for incoming agent hoods."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import re

from sase.agents_sync.io import AgentsSyncFormatError, canonical_json_bytes
from sase.agents_sync.models import AgentsManifest, ManifestEntry
from sase.agents_sync.v2_io import validate_component
from sase.core.agent_identity_facade import agent_local_hood

_DISMISSED_PREFIX_RE = re.compile(r"^\d{6}\.(.+)$")


def legacy_manifest_groups(manifest: AgentsManifest) -> tuple[AgentsManifest, ...]:
    grouped: dict[tuple[str, str], list[ManifestEntry]] = defaultdict(list)
    for entry in manifest.entries:
        grouped[(entry.machine, legacy_entry_top_hood(entry))].append(entry)
    return tuple(
        AgentsManifest(tuple(sorted(entries, key=lambda row: row.name)))
        for _key, entries in sorted(grouped.items())
    )


def legacy_entry_top_hood(entry: ManifestEntry) -> str:
    core = entry.name
    dismissed = _DISMISSED_PREFIX_RE.fullmatch(core)
    if dismissed is not None:
        core = dismissed.group(1)
    prefix = f"{entry.machine}."
    if not core.startswith(prefix) or core == prefix:
        raise AgentsSyncFormatError("legacy entry is not machine qualified")
    hood = agent_local_hood(core[len(prefix) :])
    return validate_component(hood, label="legacy top hood")


def legacy_group_digest(manifest: AgentsManifest) -> str:
    return hashlib.sha256(canonical_json_bytes(manifest.to_json_dict())).hexdigest()


def legacy_family_count(manifest: AgentsManifest) -> int:
    return int(any("--" in _legacy_local_name(entry) for entry in manifest.entries))


def legacy_group_machine_hood(manifest: AgentsManifest) -> tuple[str, str]:
    if not manifest.entries:
        raise AgentsSyncFormatError("legacy cache group cannot be empty")
    machines = {entry.machine for entry in manifest.entries}
    hoods = {legacy_entry_top_hood(entry) for entry in manifest.entries}
    if len(machines) != 1 or len(hoods) != 1:
        raise AgentsSyncFormatError("legacy cache group spans source hoods")
    return next(iter(machines)), next(iter(hoods))


def _legacy_local_name(entry: ManifestEntry) -> str:
    core = entry.name
    dismissed = _DISMISSED_PREFIX_RE.fullmatch(core)
    if dismissed is not None:
        core = dismissed.group(1)
    return core.removeprefix(f"{entry.machine}.")
