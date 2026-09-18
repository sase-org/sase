"""Mutation helpers for already-built load-tiering fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from tests.perf._agent_load_tiering_fixture_core import (
    _artifact_dir,
    _done_payload,
    _meta_payload,
    _write_json,
)


def write_completed_artifact(
    projects_root: Path,
    index: int,
    *,
    project: str = "gh_sase-org__sase",
    workflow: str = "ace-run",
    provider: str = "codex",
    model: str = "gpt-5.6-sol",
    hidden: bool = False,
    outcome: str = "completed",
    source_machine: str | None = None,
    owner_machine: str | None = None,
    meta_source_machine: str | None = None,
    done_source_machine: str | None = None,
    meta_owner_machine: str | None = None,
    done_owner_machine: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    parent_timestamp: str | None = None,
) -> Path:
    """Write one additional completed artifact without touching the index.

    Later phases use this to add production-shaped rows *after* a fixture's
    index has already been built, so the oracle can exercise post-build
    discovery and marker mutation without a full rebuild. Choose ``index``
    distinct from every index the base fixture already used (any value
    ``>= artifact_count``, or negative for a timestamp newer than the base
    fixture's rows, is always safe).

    ``source_machine`` and ``owner_machine`` apply to both markers when the
    more specific ``meta_*`` / ``done_*`` arguments are omitted. Pass values
    that differ to reproduce a conflicting-provenance row: live evaluation
    matches either field, and the indexed candidate must preserve both.
    """
    artifact_dir = _artifact_dir(projects_root, project, workflow, index)
    project_file = projects_root / project / f"{project}.sase"
    name = f"post-build-agent-{index:05d}"
    cl_name = f"post-build-{index % 37:02d}"
    meta = _meta_payload(
        index=index,
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        hidden=hidden,
    )
    done = _done_payload(
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        project_file=project_file,
        outcome=outcome,
        hidden=hidden,
    )
    if source_machine is not None:
        meta["source_machine"] = source_machine
        done["source_machine"] = source_machine
    if owner_machine is not None:
        owner = {"username": "bryan", "machine_name": owner_machine}
        meta["imported_source_owner"] = owner
        done["imported_source_owner"] = owner
    if meta_source_machine is not None:
        meta["source_machine"] = meta_source_machine
    if done_source_machine is not None:
        done["source_machine"] = done_source_machine
    if meta_owner_machine is not None:
        meta["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": meta_owner_machine,
        }
    if done_owner_machine is not None:
        done["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": done_owner_machine,
        }
    if agent_family is not None:
        meta["agent_family"] = agent_family
        if agent_family_role is not None:
            meta["agent_family_role"] = agent_family_role
    if agent_clan is not None:
        meta["agent_clan"] = agent_clan
        if agent_clan_generation is not None:
            meta["agent_clan_generation"] = agent_clan_generation
    if parent_timestamp is not None:
        meta["parent_timestamp"] = parent_timestamp
    _write_json(artifact_dir / "agent_meta.json", meta)
    _write_json(artifact_dir / "done.json", done)
    return artifact_dir


def write_waiting_artifact(
    projects_root: Path,
    index: int,
    *,
    project: str = "gh_sase-org__sase",
    workflow: str = "ace-run",
    provider: str = "codex",
    model: str = "gpt-5.6-sol",
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> Path:
    """Write a waiting-only artifact that cannot become an Agents-list base row."""

    artifact_dir = _artifact_dir(projects_root, project, workflow, index)
    name = f"waiting-only-{index:05d}"
    cl_name = f"waiting-{index % 37:02d}"
    meta = _meta_payload(
        index=index,
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        active=True,
    )
    if agent_clan is not None:
        meta["agent_clan"] = agent_clan
        if agent_clan_generation is not None:
            meta["agent_clan_generation"] = agent_clan_generation
    if clan_tribe is not None:
        meta["clan_tribe"] = clan_tribe
    if clan_summary is not None:
        meta["clan_summary"] = clan_summary
    _write_json(artifact_dir / "agent_meta.json", meta)
    _write_json(
        artifact_dir / "waiting.json",
        {"cl_name": cl_name, "waiting_for": ["upstream"]},
    )
    return artifact_dir


def set_artifact_machine_provenance(
    artifact_dir: Path,
    *,
    source_machine: str | None = None,
    owner_machine: str | None = None,
) -> None:
    """Rewrite machine provenance on an already-indexed artifact's markers."""

    for marker_name in ("agent_meta.json", "done.json"):
        path = artifact_dir / marker_name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if source_machine is None:
            payload.pop("source_machine", None)
        else:
            payload["source_machine"] = source_machine
        if owner_machine is None:
            payload.pop("imported_source_owner", None)
        else:
            payload["imported_source_owner"] = {
                "username": "bryan",
                "machine_name": owner_machine,
            }
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def set_artifact_hidden(artifact_dir: Path, hidden: bool) -> None:
    """Flip the ``hidden`` marker on an existing artifact's JSON markers in place.

    Simulates a mutation that moves a row into or out of visibility (the
    index query wire always sets ``include_hidden=False``) without a full
    index rebuild, so callers can exercise revalidate-driven repair of an
    already-indexed row.
    """
    for marker_name in ("done.json", "agent_meta.json"):
        path = artifact_dir / marker_name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if hidden:
            payload["hidden"] = True
        else:
            payload.pop("hidden", None)
        _write_json(path, payload)


def delete_artifact(artifact_dir: Path) -> None:
    """Remove an artifact directory outright, simulating a deleted run."""
    shutil.rmtree(artifact_dir, ignore_errors=True)
