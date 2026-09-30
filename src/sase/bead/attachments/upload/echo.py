"""Write-echo annotations for attachment placement and upload."""

from __future__ import annotations

from typing import Any


def rewrite_echo_for_local(echo_rows: list[str]) -> None:
    """Mark write-echo rows as staying on this machine (local-only/no-store)."""
    for index, row in enumerate(list(echo_rows)):
        if row.startswith("hint: "):
            continue
        if "stayed local on this machine" in row:
            continue
        echo_rows[index] = f"{row} · stayed local on this machine"


def rewrite_echo_for_upload(
    echo_rows: list[str],
    wires: list[dict[str, Any]],
    *,
    label: str,
    elapsed: dict[str, float] | None = None,
    pending: set[str] | None = None,
) -> None:
    """Annotate write-echo rows with the private destination and timing."""
    pending = pending or set()
    elapsed = elapsed or {}
    by_name: dict[str, dict[str, Any]] = {}
    for wire in wires:
        name = str(wire.get("name") or "")
        if name:
            by_name[name] = wire
    for index, row in enumerate(list(echo_rows)):
        if row.startswith("hint: "):
            continue
        matched: dict[str, Any] | None = None
        for name, wire in by_name.items():
            if name in row:
                matched = wire
                break
        if matched is None:
            continue
        digest = str(matched.get("digest") or matched.get("sha256") or "")
        if digest in pending:
            echo_rows[index] = f"{row} → {label} (private) · pending upload"
        else:
            seconds = elapsed.get(digest)
            if seconds is None:
                echo_rows[index] = f"{row} → {label} (private)"
            else:
                echo_rows[index] = f"{row} → {label} (private) · {seconds:.1f}s"


__all__ = [
    "rewrite_echo_for_local",
    "rewrite_echo_for_upload",
]
