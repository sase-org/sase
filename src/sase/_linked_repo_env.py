"""Linked-repository metadata and environment-variable handling."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Literal

# Canonical linked-repo env vars.
LINKED_REPOS_JSON_ENV = "SASE_LINKED_REPOS_JSON"
LINKED_REPO_ENV_PREFIX = "SASE_LINKED_REPO_"
LINKED_REPO_ENV_SUFFIXES = ("_DIR", "_PRIMARY_DIR")

# Deprecated sibling-repo aliases emitted alongside canonical values during the
# compatibility window so that mixed-version tooling and rollback remain safe.
SIBLING_REPOS_JSON_ENV = "SASE_SIBLING_REPOS_JSON"
SIBLING_REPO_ENV_PREFIX = "SASE_SIBLING_REPO_"
SIBLING_REPO_ENV_SUFFIXES = ("_DIR", "_PRIMARY_DIR")


@dataclass(frozen=True)
class ResolvedLinkedRepo:
    """Concrete linked repository paths exposed to an agent run."""

    name: str
    env_name: str
    primary_dir: str
    workspace_dir: str
    workspace_num: int
    auto_clone: bool = False
    kind: Literal["linked", "sidecar"] = "linked"
    slug: str | None = None
    remote_url: str | None = None

    @property
    def is_materialized(self) -> bool:
        """Return whether the workspace path can safely be exported."""

        return Path(self.workspace_dir).is_dir()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "env_name": self.env_name,
            "primary_dir": self.primary_dir,
            "workspace_dir": self.workspace_dir,
            "workspace_num": self.workspace_num,
            "auto_clone": self.auto_clone,
            "kind": self.kind,
            "slug": self.slug,
            "remote_url": self.remote_url,
        }


@dataclass(frozen=True)
class LinkedRepoResolution:
    """Resolved linked repos plus non-fatal configuration warnings."""

    repos: tuple[ResolvedLinkedRepo, ...]
    warnings: tuple[str, ...] = ()

    def to_jsonable(self) -> list[dict[str, object]]:
        return [repo.to_json_dict() for repo in self.repos]

    def to_json_env_value(self) -> str:
        return json.dumps(self.to_jsonable(), sort_keys=True)

    def to_env(self) -> dict[str, str]:
        if not self.repos:
            return {}
        json_value = self.to_json_env_value()
        env = {
            LINKED_REPOS_JSON_ENV: json_value,
            SIBLING_REPOS_JSON_ENV: json_value,
        }
        for repo in self.repos:
            if not repo.is_materialized:
                continue
            env[f"{LINKED_REPO_ENV_PREFIX}{repo.env_name}_DIR"] = repo.workspace_dir
            env[f"{LINKED_REPO_ENV_PREFIX}{repo.env_name}_PRIMARY_DIR"] = (
                repo.primary_dir
            )
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_DIR"] = repo.workspace_dir
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_PRIMARY_DIR"] = (
                repo.primary_dir
            )
        return env


def scrub_linked_repo_env(env: MutableMapping[str, str]) -> None:
    """Remove inherited linked- and sibling-repo env from *env*.

    Both prefixes are scrubbed so a child agent gets only fresh mappings and no
    stale inherited related-repo paths can leak in.
    """

    for key in list(env):
        if key in (LINKED_REPOS_JSON_ENV, SIBLING_REPOS_JSON_ENV):
            env.pop(key, None)
        elif key.startswith(LINKED_REPO_ENV_PREFIX) and key.endswith(
            LINKED_REPO_ENV_SUFFIXES
        ):
            env.pop(key, None)
        elif key.startswith(SIBLING_REPO_ENV_PREFIX) and key.endswith(
            SIBLING_REPO_ENV_SUFFIXES
        ):
            env.pop(key, None)


def apply_linked_repo_env(
    env: MutableMapping[str, str], resolution: LinkedRepoResolution
) -> None:
    """Replace linked- and sibling-repo env in *env* with *resolution*."""

    scrub_linked_repo_env(env)
    env.update(resolution.to_env())


def linked_repo_metadata_from_env(
    env: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return the canonical linked-repo metadata from env, if present.

    Reads the canonical ``SASE_LINKED_REPOS_JSON`` and falls back to the legacy
    ``SASE_SIBLING_REPOS_JSON`` so old agents and old env still resolve.
    """

    source = os.environ if env is None else env
    raw = source.get(LINKED_REPOS_JSON_ENV) or source.get(SIBLING_REPOS_JSON_ENV)
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    metadata: list[dict[str, object]] = []
    for item in loaded:
        if isinstance(item, Mapping):
            metadata.append({str(key): value for key, value in item.items()})
    return metadata


def is_legacy_static_linked_repo_record(mapping: Mapping[str, object]) -> bool:
    """Return whether *mapping* is an old shared-primary linked-repo record."""

    return mapping.get("workspace_strategy") == "none"
