"""Remote handoff path sets for machine-targeted sudo over SSH."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sase.notification_gates.models import GateError
from sase.sudo.ssh_defs import REMOTE_BASE, RemoteSudoPaths


def allocate_remote_sudo_paths(*, base: str = REMOTE_BASE) -> dict[str, str]:
    """Return a unique remote handoff path set under *base*."""
    return _remote_paths(base=base).to_dict()


def _remote_paths(*, base: str = REMOTE_BASE) -> RemoteSudoPaths:
    token = uuid4().hex
    directory = f"{base.rstrip('/')}/sase-sudo-{token}"
    return RemoteSudoPaths(
        directory=directory,
        handshake=f"{directory}/handshake.json",
        ledger=f"{directory}/ledger.json",
        log=f"{directory}/output.log",
        manifest=f"{directory}/manifest.json",
        stop=f"{directory}/stop",
    )


def coerce_paths(payload: Mapping[str, Any] | None) -> RemoteSudoPaths:
    if payload is None:
        return _remote_paths()
    return paths_from_payload(payload)


def paths_from_payload(payload: Mapping[str, Any]) -> RemoteSudoPaths:
    try:
        directory = str(payload["directory"])
        handshake = str(payload["handshake"])
        ledger = str(payload["ledger"])
        log = str(payload["log"])
        manifest = str(payload["manifest"])
        stop = str(payload["stop"])
    except KeyError as exc:
        raise GateError(
            "invalid_sudo_finalize",
            "remote.paths",
            f"remote sudo path payload is missing {exc.args[0]}",
        ) from exc
    if not all((directory, handshake, ledger, log, manifest, stop)):
        raise GateError(
            "invalid_sudo_finalize",
            "remote.paths",
            "remote sudo paths must be non-empty strings",
        )
    return RemoteSudoPaths(
        directory=directory,
        handshake=handshake,
        ledger=ledger,
        log=log,
        manifest=manifest,
        stop=stop,
    )


__all__ = [
    "coerce_paths",
    "paths_from_payload",
    "allocate_remote_sudo_paths",
]
