"""Prefix-renamed k× copies of a real bead store for benchmarking.

Companion to ``_bead_corpus``: the research report scales history by
laying down length-preserving prefix-renamed copies of a store, and
every renamed event is re-minted with that module's ``mint_event_id``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from tests.perf._bead_corpus_common import dump_payload, mint_event_id
from tests.perf._bead_corpus_store import (
    export_projection,
    git_commit,
    summarize_corpus,
)


def _copy_prefix_variant(prefix: str, copy_index: int) -> str:
    """Return a length-preserving, still-valid issue prefix for copy *i*."""
    if copy_index == 0:
        return prefix
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    head, last = prefix[:-1], prefix[-1:]
    try:
        rotated = alphabet[(alphabet.index(last) + copy_index) % len(alphabet)]
    except ValueError:
        rotated = alphabet[copy_index % len(alphabet)]
    candidate = f"{head}{rotated}"
    if candidate == prefix:
        candidate = (
            f"{head}{alphabet[(len(alphabet) - 1 - copy_index) % len(alphabet)]}"
        )
    return candidate


def _remap_bead_id(value: str, old_prefix: str, new_prefix: str) -> str:
    """Rename one bead ID across a prefix boundary, leaving others alone."""
    if not isinstance(value, str):
        return value
    if value == old_prefix or value.startswith(old_prefix + "-"):
        return new_prefix + value[len(old_prefix) :]
    return value


def _is_bead_store_root(candidate: Path) -> bool:
    return (candidate / "events" / "manifest.json").is_file() and (
        candidate / "config.json"
    ).is_file()


def _refuses_sidecar_destination(dest: Path) -> str | None:
    """Return a refusal reason when *dest* sits inside a bead-store clone.

    Only a directory that both hosts a bead store and is itself versioned
    (a ``.git`` entry) counts: a plain home directory that merely contains
    an ``sdd/beads`` store is not a clone.
    """
    current = dest
    while True:
        if _is_bead_store_root(current) and (current / ".git").exists():
            return f"{dest} is inside the bead store clone at {current}"
        if (current / "sdd" / "beads").is_dir() and _is_bead_store_root(
            current / "sdd" / "beads"
        ):
            if (current / ".git").exists():
                return f"{dest} is inside the workspace checkout at {current}"
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _remap_event(
    event: dict[str, Any],
    old_prefix: str,
    new_prefix: str,
    copy_index: int,
    event_ids: dict[str, str],
) -> dict[str, Any]:
    """Return *event* with every bead ID renamed to *new_prefix*."""
    remap = lambda value: _remap_bead_id(value, old_prefix, new_prefix)  # noqa: E731
    issue_id = remap(event["issue_id"])
    payload = event["payload"]
    kind = payload.get("kind")
    rebuilt: dict[str, Any] = {"kind": kind}
    for key, value in payload.items():
        if key == "kind":
            continue
        if kind == "issue_created" and key == "issue":
            issue = dict(value)
            issue["id"] = remap(issue["id"])
            if issue.get("parent_id"):
                issue["parent_id"] = remap(issue["parent_id"])
            issue["dependencies"] = [
                {
                    **dep,
                    "issue_id": remap(dep["issue_id"]),
                    "depends_on_id": remap(dep["depends_on_id"]),
                }
                for dep in issue.get("dependencies", [])
            ]
            if issue.get("external_ref"):
                issue["external_ref"] = f"{issue['external_ref']}.c{copy_index}"
            rebuilt[key] = issue
        elif kind in ("dependency_added", "dependency_removed") and key == "dependency":
            dep = dict(value)
            dep["issue_id"] = remap(dep["issue_id"])
            dep["depends_on_id"] = remap(dep["depends_on_id"])
            rebuilt[key] = dep
        elif kind in ("note_edited", "note_removed") and key == "note_id":
            rebuilt[key] = event_ids[value]
        elif kind == "issue_closed" and key == "forced_descendant_ids":
            rebuilt[key] = [remap(item) for item in value]
        elif kind == "issue_removed" and key == "cascade_removed_issue_ids":
            rebuilt[key] = [remap(item) for item in value]
        else:
            rebuilt[key] = value
    return {
        "schema_version": event.get("schema_version", 1),
        "event_id": "",
        "timestamp": event["timestamp"],
        "actor": event["actor"],
        "operation": event["operation"],
        "issue_id": issue_id,
        "payload": rebuilt,
    }


def copy_store_scaled(
    source: str | Path, dest: str | Path, *, copies: int = 1
) -> dict[str, Any]:
    """Copy a real bead store to *dest*, optionally as *copies* prefix copies.

    The source is never modified. With ``copies > 1`` the destination holds
    the original store plus ``copies - 1`` length-preserving prefix-renamed
    copies (the research report's scaling method); every renamed event is
    re-minted with :func:`mint_event_id`. The destination must not exist yet
    and must not sit inside the source or any sidecar clone.
    """
    if copies < 1:
        raise ValueError(f"copies must be >= 1, got {copies}")
    source = Path(source).resolve()
    dest = Path(dest)
    if dest.exists():
        raise ValueError(f"refusing to copy into existing {dest}")
    resolved = dest.resolve()
    if resolved == source or source in resolved.parents:
        raise ValueError(f"refusing to copy a store inside itself: {dest}")
    refusal = _refuses_sidecar_destination(resolved)
    if refusal is not None:
        raise ValueError(f"refusing sidecar-clone destination: {refusal}")
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    old_prefix = str(config.get("issue_prefix", ""))
    if not old_prefix:
        raise ValueError(f"source store at {source} has no issue_prefix")
    prefixes = [_copy_prefix_variant(old_prefix, idx) for idx in range(copies)]
    if len(set(prefixes)) != len(prefixes):
        raise ValueError(
            f"prefix variants collided for {copies} copies of {old_prefix!r}"
        )

    streams_dir = dest / "events" / "streams"
    streams_dir.mkdir(parents=True)
    source_streams = sorted((source / "events" / "streams").glob("*.jsonl"))
    if not source_streams:
        raise ValueError(f"source store at {source} has no event streams")
    for copy_index, new_prefix in enumerate(prefixes):
        event_ids: dict[str, str] = {}
        for path in source_streams:
            old_stream = path.stem
            new_stream = _remap_bead_id(old_stream, old_prefix, new_prefix)
            if copy_index == 0:
                shutil.copyfile(path, streams_dir / f"{new_stream}.jsonl")
                continue
            lines = []
            ordinal = 0
            with open(path, encoding="utf-8") as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    ordinal += 1
                    event = json.loads(raw)
                    renamed = _remap_event(
                        event, old_prefix, new_prefix, copy_index, event_ids
                    )
                    event_id = mint_event_id(
                        new_stream,
                        ordinal,
                        renamed["timestamp"],
                        renamed["actor"],
                        renamed["operation"],
                        renamed["issue_id"],
                        renamed["payload"],
                    )
                    event_ids[event["event_id"]] = event_id
                    renamed["event_id"] = event_id
                    lines.append(dump_payload(renamed))
            (streams_dir / f"{new_stream}.jsonl").write_text(
                "".join(f"{line}\n" for line in lines), encoding="utf-8"
            )
    (dest / "events" / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stream_count": len(source_streams) * copies,
                "generated_from": "issues.jsonl",
                "migration_tool": "sase-core bead events",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (dest / "config.json").write_text(
        json.dumps(
            {
                "issue_prefix": old_prefix,
                "next_counter": config.get("next_counter", 1),
                "owner": config.get("owner", ""),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    beads_db = source / "beads.db"
    if beads_db.is_file():
        shutil.copyfile(beads_db, dest / "beads.db")
    else:
        (dest / "beads.db").write_bytes(b"")
    export_projection(dest)
    git_commit(dest, f"Scaled bead corpus copies={copies} from {source}")
    shape = summarize_corpus(dest)
    shape.update({"copies": copies, "prefixes": prefixes, "source": str(source)})
    return shape
