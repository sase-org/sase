"""Implementation of ``sase artifact create``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sase.core.artifact_file_facade import store_explicit_artifact_file


def handle_create(args: argparse.Namespace) -> int:
    """Copy a source file into persistent SASE artifact storage."""

    if os.environ.get("SASE_AGENT") != "1":
        return _error(
            "sase artifact create must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)"
        )

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        return _error("sase artifact create requires SASE_ARTIFACTS_DIR")

    source_path = Path(args.path).expanduser().absolute()
    if not source_path.is_file():
        return _error(f"artifact source not found: {source_path}")
    captured_file_hook_event = None
    produce_hook = None
    try:
        from sase.file_hooks.producer import (
            capture_artifact_source,
            produce_artifact_file_hook,
        )

        produce_hook = produce_artifact_file_hook
        captured_file_hook_event = capture_artifact_source(source_path)
    except Exception:
        captured_file_hook_event = None

    # Resolve and verify the attachment target first: an artifact created
    # without the attachment the caller asked for is worse than no artifact.
    try:
        bead_id = _resolve_bead_target(args.bead)
    except ValueError as exc:
        return _error(str(exc))

    try:
        artifact_file = store_explicit_artifact_file(
            source_path,
            agent_artifacts_dir,
            label=args.label,
            kind=args.kind,
            move=args.move,
        )
    except Exception as exc:
        return _error(f"failed to create artifact: {exc}")

    reference = f"file:{artifact_file.id}"
    print(f"id: {artifact_file.id}")
    print(f"source: {source_path}")
    print(f"path: {artifact_file.path}")
    print(f"ref: {reference}")

    if (
        captured_file_hook_event is not None
        and artifact_file.path
        and produce_hook is not None
    ):
        produce_hook(captured_file_hook_event, artifact_file.path)

    _derive_links_for_created_artifact(
        reference, artifact_file.path, agent_artifacts_dir
    )

    if bead_id is not None:
        exit_code = _attach_reference_to_bead(bead_id, reference)
        if exit_code != 0:
            return _error(f"failed to attach {reference} to bead {bead_id}")
        print(f"bead: {bead_id}")
    return 0


def _resolve_bead_target(bead: str | None) -> str | None:
    """Return the bead ``--bead`` names, or ``None`` when it was not passed.

    A bare ``--bead`` means "the bead this agent is working", which only the
    launch environment knows. Attaching to the wrong bead is silent data
    corruption, so an absent ``SASE_BEAD_ID`` is an error, never a fallback.
    """

    if bead is None:
        return None
    bead_id = bead.strip()
    if not bead_id:
        bead_id = (os.environ.get(_bead_id_env()) or "").strip()
        if not bead_id:
            raise ValueError(
                "sase artifact create --bead was passed without a bead id and "
                f"{_bead_id_env()} is not set; pass the bead id explicitly"
            )
    if not _bead_exists(bead_id):
        raise ValueError(f"bead not found: {bead_id}")
    return bead_id


def _bead_id_env() -> str:
    from sase.bead.work import SASE_BEAD_ID_ENV

    return SASE_BEAD_ID_ENV


def _bead_exists(bead_id: str) -> bool:
    from sase.bead.cli_common import get_read_view

    try:
        with get_read_view() as view:
            view.show(bead_id)
    except KeyError:
        return False
    except Exception as exc:  # noqa: BLE001 - an unreadable store is fatal here.
        raise ValueError(f"bead store is unavailable: {exc}") from exc
    return True


def _resolved_created_by() -> str:
    """Return the acting agent's name, else the OS user, else ``"unknown"``."""

    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return (
        identity.name if identity is not None else (os.environ.get("USER") or "unknown")
    )


def _derive_links_for_created_artifact(
    reference: str, path: str | None, agent_artifacts_dir: str
) -> None:
    """Best-effort: derive candidate links for the artifact just created.

    A no-op today for every ``file:`` reference this command produces, since
    no derivation rule recognizes that kind -- wired anyway so a future rule
    over created artifacts needs no new call site. Never raises: a derivation
    failure must not turn a successful artifact creation into a failed one.
    """

    if not path:
        return
    from sase.artifact_links.derive import artifact_link_derivation_enabled

    if not artifact_link_derivation_enabled():
        return
    try:
        from sase.artifact_links.derive import DerivableDocument
        from sase.sdd.artifact_link_derivation import derive_and_persist_artifact_links
        from sase.sdd.artifact_link_store import resolve_artifact_link_store

        derive_and_persist_artifact_links(
            resolve_artifact_link_store(),
            (DerivableDocument(ref=reference, path=Path(path)),),
            created_by=_resolved_created_by(),
            artifacts_dir=agent_artifacts_dir,
        )
    except Exception:
        pass


def _attach_reference_to_bead(bead_id: str, reference: str) -> int:
    """Attach *reference* to *bead_id* as a typed ``related`` artifact link.

    ``reference_added`` (``sase bead ref add``) is a legacy, untyped
    vocabulary; this writes through the same typed-link store path
    ``sase artifact link add`` uses instead of adding to it.
    """

    from datetime import UTC, datetime

    from sase.sdd._artifact_link_commit import (
        ArtifactLinkPersistError,
        persist_artifact_link_graph_mutation,
    )
    from sase.sdd.artifact_link_store import (
        ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        resolve_artifact_link_store,
    )

    created_by = _resolved_created_by()
    row = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": reference,
        "relation": "related",
        "target_ref": f"bead:{bead_id}",
        "description": "attached via sase artifact create --bead",
        "origin": "manual",
        "created_by": created_by,
        "created_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uses": 1,
    }
    try:
        store = resolve_artifact_link_store()
        outcome = store.upsert_row(row)
        persist_artifact_link_graph_mutation(
            store,
            changed_indexes=tuple(
                Path(path) for path in outcome.get("changed_indexes") or ()
            ),
            beads_changed=bool(outcome.get("beads_changed")),
        )
    except (RuntimeError, TypeError, ValueError, ArtifactLinkPersistError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


__all__ = ["handle_create"]
