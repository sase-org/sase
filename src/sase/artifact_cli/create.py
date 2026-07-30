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


def _attach_reference_to_bead(bead_id: str, reference: str) -> int:
    """Attach *reference* through the same write path ``sase bead ref`` uses."""

    from sase.main.bead_fast_path import try_handle_bead_fast_path

    exit_code = try_handle_bead_fast_path(["ref", "add", bead_id, reference])
    return 1 if exit_code is None else exit_code


def _error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


__all__ = ["handle_create"]
