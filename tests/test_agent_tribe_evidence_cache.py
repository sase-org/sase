"""One live version per key for the tribe-evidence cache (sase-1ez closeout)."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core import agent_tribe_evidence as evidence_mod


def test_tribe_evidence_replaces_entry_across_external_rewrites(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    tribes_path = tmp_path / "agent_tribes.json"
    legacy_path = tmp_path / "agent_tags.json"

    evidence_mod._CACHE.clear()
    try:
        rewrites = 16
        last: tuple[str, ...] = ()
        for i in range(rewrites):
            payload = [
                {
                    "id": ["run", "clan", f"ts-{i}"],
                    "tribe": f"tribe-{i}",
                    "pad": "x" * i,
                }
            ]
            tribes_path.write_text(json.dumps(payload), encoding="utf-8")
            last = evidence_mod.stored_tribe_names_for_resolution(
                projects_root=projects,
                agent_tribes_path=tribes_path,
                legacy_store_path=legacy_path,
            )
        assert len(evidence_mod._CACHE) == 1
        assert last == (f"tribe-{rewrites - 1}",)
    finally:
        evidence_mod._CACHE.clear()
