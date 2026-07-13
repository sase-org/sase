"""Configuration merging and defaults for linked repositories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

LINKED_REPOS_CONFIG_KEY = "linked_repos"
SIBLING_REPOS_CONFIG_KEY = "sibling_repos"
DEFAULT_LINKED_REPOS_CONFIG_KEY = "default_linked_repos"

DEFAULT_PLANS_DESCRIPTION = "Durable SASE plans, prompt snapshots, and bead state."
DEFAULT_RESEARCH_DESCRIPTION = "Durable SASE research reports and generated media."

_DEFAULT_LINKED_REPO_MARKER = "_sase_default_linked_repo"


def resolution_config(
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if config is not None:
        return config

    from sase.config.core import load_merged_config

    merged = load_merged_config()
    local_config = read_project_local_config(primary_workspace_dir)
    if local_config:
        return _merge_resolution_config(merged, local_config)
    return merged


def _merge_resolution_config(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, override_value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            result[key] = _merge_resolution_config(base_value, override_value)
        elif isinstance(base_value, list) and isinstance(override_value, list):
            result[key] = [*base_value, *override_value]
        else:
            result[key] = override_value
    return result


def merged_entries_from_config(
    config: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Merge canonical ``linked_repos`` with deprecated ``sibling_repos``.

    Within a single key, exact duplicates are deduped but distinct same-name
    entries remain. Across keys, canonical entries win; divergent legacy
    entries with the same name produce a non-fatal warning.
    """

    canonical = _dedupe_entries(_entries_for_key(config, LINKED_REPOS_CONFIG_KEY))
    legacy = _dedupe_entries(_entries_for_key(config, SIBLING_REPOS_CONFIG_KEY))

    canonical_by_name: dict[str, Mapping[str, Any]] = {}
    for entry in canonical:
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            canonical_by_name.setdefault(name.strip(), entry)

    merged: list[Mapping[str, Any]] = list(canonical)
    warnings: list[str] = []
    for entry in legacy:
        name = entry.get("name")
        key_name = name.strip() if isinstance(name, str) else ""
        canonical_entry = canonical_by_name.get(key_name) if key_name else None
        if canonical_entry is not None:
            if not _entries_equivalent(canonical_entry, entry):
                warnings.append(
                    f"Linked repo {key_name!r} is defined in both linked_repos "
                    "and sibling_repos with different settings; using the "
                    "linked_repos definition and ignoring the sibling_repos one"
                )
            continue
        merged.append(entry)

    return merged, warnings


def inject_default_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    local_config: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Inject managed-project sidecar repos unless locally disabled."""

    merged = list(entries)
    if local_config.get("is_sase_managed") is not True:
        return merged
    if local_config.get(DEFAULT_LINKED_REPOS_CONFIG_KEY) is False:
        return merged

    project_name = Path(primary_workspace_dir).resolve(strict=False).name
    if not project_name:
        return merged

    configured_names = {
        name.strip()
        for entry in entries
        if isinstance((name := entry.get("name")), str) and name.strip()
    }
    defaults = (
        (f"{project_name}--plans", DEFAULT_PLANS_DESCRIPTION, True),
        (f"{project_name}--research", DEFAULT_RESEARCH_DESCRIPTION, False),
    )
    for name, description, auto_clone in defaults:
        if name in configured_names:
            continue
        merged.append(
            {
                "name": name,
                "path": f"../{name}",
                "description": description,
                "auto_clone": auto_clone,
                _DEFAULT_LINKED_REPO_MARKER: True,
            }
        )
    return merged


def _entries_for_key(config: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    entries: list[Mapping[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            entries.append({str(name): value for name, value in item.items()})
    return entries


def _dedupe_entries(
    entries: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    deduped: list[Mapping[str, Any]] = []
    for entry in entries:
        key = json.dumps(_json_safe_entry(entry), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def read_project_local_config(primary_workspace_dir: str) -> dict[str, Any]:
    path = Path(primary_workspace_dir) / "sase.yml"
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _entries_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _json_safe_entry(left) == _json_safe_entry(right)


def _json_safe_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    name = entry.get("name")
    path = entry.get("path")
    return {
        "name": name if isinstance(name, str) else "",
        "path": path if isinstance(path, str) else "",
        "auto_clone": entry.get("auto_clone") is True,
    }


def resolve_config_path(path: str, *, relative_to: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(relative_to) / candidate
    return normalize_path(str(candidate))


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
