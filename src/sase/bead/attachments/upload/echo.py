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
    """Annotate write-echo rows with the destination and timing.

    The authoring echo already carries the audience badge (``🌐 public`` or
    ``🔒 private (…)``), so this appends only the destination. ``label``
    already includes its own ``(private)``/``(public)`` suffix when it comes
    from :func:`describe_label`; no second audience suffix is added here,
    fixing the old ``(private) (private)`` duplication.
    """
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
        visibility = str(matched.get("visibility") or "private")
        badge = "🌐" if visibility == "public" else "🔒"
        if f"{badge} " not in row and (
            "🌐 public" not in row and "🔒 private" not in row
        ):
            row = f"{row} · {badge} {visibility}"
            echo_rows[index] = row
        if digest in pending:
            echo_rows[index] = f"{row} → {label} · ⇡ pending upload"
        else:
            seconds = elapsed.get(digest)
            if seconds is None:
                echo_rows[index] = f"{row} → {label}"
            else:
                echo_rows[index] = f"{row} → {label} · {seconds:.1f}s"


def rewrite_echo_for_public_pending(
    echo_rows: list[str],
    wires: list[dict[str, Any]],
) -> None:
    """Mark public wires as queued for the missing public store."""
    by_name: dict[str, dict[str, Any]] = {}
    for wire in wires:
        name = str(wire.get("name") or "")
        if name:
            by_name[name] = wire
    for index, row in enumerate(list(echo_rows)):
        if row.startswith("hint: "):
            continue
        matched = None
        for name, wire in by_name.items():
            if name in row:
                matched = wire
                break
        if matched is None:
            continue
        if str(matched.get("visibility") or "") != "public":
            continue
        if "pending upload" in row:
            continue
        echo_rows[index] = (
            f"{row} · ⇡ pending upload "
            "(public store not yet available; run sase repo init)"
        )


__all__ = [
    "rewrite_echo_for_local",
    "rewrite_echo_for_public_pending",
    "rewrite_echo_for_upload",
]
