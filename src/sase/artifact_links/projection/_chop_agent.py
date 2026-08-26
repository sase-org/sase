"""Project `launched` rows from a chop's identity encoded in its agent name.

``metadata.chop_name``/``chop_lumberjack`` do not exist in published agent
metadata (they are written only to the local, never-published
``agent_meta.json``), so the ``.chop.<base>.`` segment of the agent name --
recovered against the live AXE config -- is the only available source. See
the plan's "Two corrections" section for the verification behind this.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

from sase.artifact_links.projection._cache import read_rule_cache, write_rule_cache
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs
from sase.config.core import current_config_token

_RULE_ID = "chop-agent"
_CHOP_SEGMENT_RE = re.compile(r"(?:^|\.)chop\.([^.]+)\.")


def project_chop_agent_rows(inputs: ProjectionInputs) -> tuple[ProjectedEdge, ...]:
    """Emit `chop:<lumberjack>/<base>` `launched` `agent:<global>` rows."""

    if inputs.agents_sidecar_root is None:
        return ()
    agents_dir = inputs.agents_sidecar_root / "agents"
    if not agents_dir.is_dir():
        return ()

    cached_signature, cached_rows = read_rule_cache(inputs.project_key, _RULE_ID)
    try:
        signature = _projection_signature(agents_dir)
    except OSError:
        return _edges_from_rows(cached_rows)
    if signature == cached_signature:
        return _edges_from_rows(cached_rows)

    try:
        chop_names = _sanitized_base_chop_names()
    except Exception:  # noqa: BLE001 - degrade to staleness, not deletion.
        return _edges_from_rows(cached_rows)

    rows: list[dict[str, str]] = []
    for entry in sorted(agents_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        match = _CHOP_SEGMENT_RE.search(entry.name)
        if match is None:
            continue
        resolved = chop_names.get(match.group(1))
        if resolved is None:
            continue
        lumberjack, base = resolved
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        rows.append(
            {
                "source_ref": f"chop:{lumberjack}/{base}",
                "relation": "launched",
                "target_ref": f"agent:{entry.name}",
                "description": (
                    f"agent name's `.chop.{match.group(1)}.` segment resolves to "
                    f"chop:{lumberjack}/{base} in the live AXE config"
                ),
                "created_at": datetime.fromtimestamp(mtime, tz=UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
    write_rule_cache(inputs.project_key, _RULE_ID, signature=signature, rows=rows)
    return _edges_from_rows(rows)


def _sanitized_base_chop_names() -> dict[str, tuple[str, str]]:
    # Deferred: `sase.axe.config` pulls in `sase.axe`'s package init, which
    # transitively imports `sase.sdd.artifact_link_store` -- a real import
    # cycle if this were a module-level import here.
    from sase.axe.config import load_axe_config
    from sase.core.axe_chop_facade import derive_chop_agent_name

    config = load_axe_config()
    resolved: dict[str, tuple[str, str]] = {}
    for lumberjack_name, lumberjack in config.lumberjacks.items():
        for chop in lumberjack.chops:
            # A `for_each`-expanded chop's own `.name` carries its bracketed
            # target (`refresh_docs[sase]`); `derive_chop_agent_name` only
            # ever sanitizes the unexpanded `base_name`.
            base = chop.base_name or chop.name
            sanitized = (
                derive_chop_agent_name(
                    base, target_key=None, proposal_index=0, run_token=None
                )
                .removeprefix("chop.")
                .removesuffix(".1")
            )
            resolved[sanitized] = (lumberjack_name, base)
    return resolved


def _projection_signature(agents_dir: Path) -> str:
    names = sorted(entry.name for entry in agents_dir.iterdir())
    payload = {"names": names, "config_token": list(current_config_token())}
    return json.dumps(payload, sort_keys=True, default=str)


def _edges_from_rows(rows: list[dict[str, str]]) -> tuple[ProjectedEdge, ...]:
    return tuple(
        ProjectedEdge(
            source_ref=row["source_ref"],
            relation=row["relation"],
            target_ref=row["target_ref"],
            description=row["description"],
            rule_id=_RULE_ID,
            created_at=row["created_at"],
        )
        for row in rows
    )


__all__ = ["project_chop_agent_rows"]
