"""Tier placement policy for attachment uploads."""

from __future__ import annotations

import sys
from typing import Any

from sase.bead.attachments.upload.errors import (
    AttachmentStoreMissingError,
    AttachmentTooLargeError,
)

# Public helpers from sibling modules resolve through the ``upload`` facade
# at call time, so monkeypatching ``sase.bead.attachments.upload.<name>``
# keeps working after the split.


def placement_tiers(
    stores: dict[str, Any], *, git_max_bytes: int
) -> list[dict[str, Any]]:
    """Build the ordered core-policy tier list for the reachable *stores*."""
    tiers: list[dict[str, Any]] = []
    if stores.get("git") is not None:
        tiers.append({"name": "git", "max_bytes": git_max_bytes})
    large_store = stores.get("large")
    if large_store is not None:
        try:
            large_max = int(getattr(large_store, "max_bytes", 2147483648))
        except (TypeError, ValueError):
            large_max = 2147483648
        tiers.append({"name": "large", "max_bytes": large_max})
    return tiers


def split_wires_by_tier(
    wires: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Route each wire to its core-policy tier name; raise on oversize.

    Raises :class:`AttachmentTooLargeError` naming the first wire no
    configured tier accepts.
    """
    from sase.core.rust import require_rust_binding

    placement = require_rust_binding("attachment_placement")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for wire in wires:
        size = int(wire.get("size_bytes") or 0)
        try:
            decision = placement(size, tiers, False)
            tier_name = str(decision.get("store"))
        except Exception:
            tier_name = ""
        if not tier_name:
            name = str(wire.get("name") or "attachment")
            raise AttachmentTooLargeError((name, size))
        grouped.setdefault(tier_name, []).append(wire)
    return grouped


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):g} MiB"
    return f"{size_bytes / (1024 * 1024 * 1024):g} GiB"


def decide_placement(
    wires: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
    *,
    local_only: bool,
    require_upload: bool,
) -> str:
    """Return ``local_only`` | ``no_store`` | a tier name | ``mixed``.

    *tiers* is the ordered reachable-tier list from :func:`placement_tiers`
    (empty when no shared store exists). Raises
    :class:`AttachmentTooLargeError` when a size is rejected and ``-L`` was
    not passed/accepted, and :class:`AttachmentStoreMissingError` when
    ``require_upload`` needs a store that does not exist. On a TTY, an
    oversize prompts y/N to continue local-only.
    """
    from sase.bead.attachments import upload

    if not wires:
        if not tiers:
            return "no_store"
        return str(tiers[0]["name"])
    if local_only:
        return "local_only"
    if not tiers:
        if require_upload:
            raise AttachmentStoreMissingError(
                "require_upload is set but no attachments-private shared "
                "store exists on this machine; attachment bytes cannot upload."
            )
        return "no_store"
    try:
        grouped = upload.split_wires_by_tier(wires, tiers)
    except AttachmentTooLargeError as exc:
        oversize: dict[str, Any] | None = None
        if exc.args and isinstance(exc.args[0], tuple):
            oversize_name, oversize_size = exc.args[0]
            oversize = {"name": oversize_name, "size_bytes": oversize_size}
        if oversize is None:
            oversize = wires[0]
        size = int(oversize.get("size_bytes") or 0)
        name = str(oversize.get("name") or "attachment")
        caps = "; ".join(
            f"{spec['name']} tier accepts up to {_format_size(int(spec['max_bytes']))}"
            for spec in tiers
        )
        hint = (
            f"attachment {name} is {_format_size(size)} ({caps}); "
            "pass -L/--local-only to keep it on this machine."
        )
        if sys.stdin.isatty():
            try:
                answer = (
                    input(f"{hint}\nKeep {name} local-only instead? [y/N] ")
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer in {"y", "yes"}:
                return "local_only"
            raise AttachmentTooLargeError(hint) from exc
        raise AttachmentTooLargeError(hint) from exc
    names = sorted(grouped)
    if len(names) == 1:
        return names[0]
    return "mixed"


def prepare_placement(
    wires: list[dict[str, Any]],
    *,
    local_only: bool,
    bead_context: Any | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    """Decide placement, exiting non-zero before any bead write on refusal.

    Returns ``(placement, stores, project_key)`` where *stores* maps every
    reachable tier name to its store. Prints ``Error:`` and exits 1 when an
    oversize or missing-store refusal must leave the store unchanged.
    """
    from sase.bead.attachments import upload
    from sase.bead.config import (
        get_attachment_git_max_bytes,
        get_attachment_require_upload,
    )

    git_max = get_attachment_git_max_bytes()
    require_upload = get_attachment_require_upload()
    stores = upload.discover_stores(bead_context)
    tiers = upload.placement_tiers(stores, git_max_bytes=git_max)
    try:
        project_key = upload.resolve_project_key(bead_context)
        placement = upload.decide_placement(
            wires,
            tiers,
            local_only=local_only,
            require_upload=require_upload,
        )
    except (AttachmentTooLargeError, AttachmentStoreMissingError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return (placement, stores, project_key)


__all__ = [
    "decide_placement",
    "placement_tiers",
    "prepare_placement",
    "split_wires_by_tier",
]
