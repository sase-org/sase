"""Bead attachment publish and unpublish commands.

``publish`` widens a note attachment to public: it is human-only (an agent
run is refused unless the command runs as an approved gate option, detected
through the ``SASE_GATE_COMMAND`` marker that owned gate commands export).
``unpublish`` narrows a note attachment to private, so agents may run it.
Both edit manifests through ``NoteEdited`` (``project.edit_note`` with the
note text unchanged). +1 evidence manifests are immutable and are refused
with a clear message.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sase.bead.attachment_presentation import strip_display_name
from sase.bead.attachments.fetch import format_attachment_size
from sase.bead.attachments.lifecycle import roster_for_issue
from sase.bead.cli_common import (
    get_project,
    get_read_view,
    resolve_bead_operation_context,
)

GATE_COMMAND_ENV = "SASE_GATE_COMMAND"

_NON_WIDENABLE_METADATA_RULES = ("sensitive_path",)
_WITHDRAW_COMMIT_PREFIX = "chore(attachments): withdraw"


def _is_gate_option_command(env: dict[str, str] | None = None) -> bool:
    """Return whether this process runs as an approved gate option command.

    Owned gate commands (see ``sase.notification_gates.command_runner``)
    export ``SASE_GATE_COMMAND=1`` with a hash-verified argv, so a publish
    offered through ``/sase_gate`` arrives with the marker while an ordinary
    agent run does not.
    """
    current = env if env is not None else os.environ
    return str(current.get(GATE_COMMAND_ENV) or "") == "1"


def current_actor() -> str:
    """Return ``human`` or ``agent``, failing closed to ``agent``."""
    try:
        from sase.bead.attachments import provenance

        return provenance.current_actor()
    except Exception:
        return "agent"


def _find_note_with_name(issue: Any, name: str) -> tuple[int, Any, Any] | None:
    """Return ``(ordinal, note, attachment)`` for the latest note with *name*."""
    found: tuple[int, Any, Any] | None = None
    for ordinal, note in enumerate(getattr(issue, "notes", ()) or (), start=1):
        for attachment in getattr(note, "attachments", ()) or ():
            if str(getattr(attachment, "name", "") or "") == name:
                found = (ordinal, note, attachment)
    return found


def _evidence_has_name(issue: Any, name: str) -> bool:
    """Return whether any +1 evidence manifest carries *name*."""
    for evidence in getattr(issue, "plus_one_evidence", ()) or ():
        for attachment in getattr(evidence, "attachments", ()) or ():
            if str(getattr(attachment, "name", "") or "") == name:
                return True
    return False


def _manifest_with_visibility(
    note: Any, digest: str, visibility: str
) -> list[dict[str, Any]]:
    """Build a ``NoteEdited`` manifest with *digest* narrowed/widened."""
    from sase.bead.note_codec import attachment_to_dict

    manifest: list[dict[str, Any]] = []
    for attachment in getattr(note, "attachments", ()) or ():
        wire = dict(attachment_to_dict(attachment))
        if str(wire.get("sha256") or "") == digest:
            wire["visibility"] = visibility
        manifest.append(wire)
    return manifest


def _read_audience_metadata(digest: str) -> dict[str, Any] | None:
    """Return the local audience metadata for *digest*, if recorded."""
    try:
        from sase.bead.attachments import audience as _audience

        path = _audience.audience_metadata_path(digest)
    except Exception:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _metadata_refuses_publish(metadata: dict[str, Any] | None) -> str | None:
    """Return a refusal reason when stored metadata blocks widening."""
    if not metadata:
        return None
    rule = str(metadata.get("rule") or "")
    reason = str(metadata.get("reason") or "")
    if rule in _NON_WIDENABLE_METADATA_RULES:
        return reason or rule
    if rule == "scan_hit" and "known" in reason.lower():
        return reason or "known value"
    return None


def _ensure_local_bytes(digest: str, bead_context: Any = None) -> Path | None:
    """Ensure the local CAS holds *digest*; fetch from shared stores if needed."""
    from sase.bead.attachments.store import LocalAttachmentStore

    local = LocalAttachmentStore()
    try:
        if local.has(digest) and local.verify(digest):
            return local.object_path(digest)
    except Exception:
        pass
    try:
        from sase.bead.attachments.upload import discover_stores

        stores = discover_stores(bead_context)
    except Exception:
        stores = {}
    for store in stores.values():
        try:
            store.get(digest, local.root)
        except Exception:
            continue
        try:
            if local.has(digest) and local.verify(digest):
                return local.object_path(digest)
        except Exception:
            continue
    return None


def _rescan_digest(
    digest: str, object_path: Path, max_bytes: int
) -> dict[str, Any] | None:
    """Rescan *object_path* with the current rules; None when unavailable."""
    try:
        from sase.bead.attachments import audience as _audience

        return _audience.scan_cas_object(object_path, max_bytes=max_bytes)
    except Exception:
        return None


def _confirm_irreversible(name: str, *, assume_yes: bool, verb: str) -> bool:
    """Confirm an irreversible audience change; False declines."""
    if assume_yes:
        return True
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        print(
            f"Refusing to {verb} without confirmation on a non-TTY; re-run "
            "with -y/--yes.",
            file=sys.stderr,
        )
        sys.exit(2)
    prompt = (
        f"{verb.capitalize()} {name} publicly? Publication is irreversible — "
        "forks, clones, caches, and GitHub's retention of unreachable objects "
        "persist. [y/N] "
        if verb == "publish"
        else f"Unpublish {name}? [y/N] "
    )
    print(prompt, file=sys.stderr, end="")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def handle_bead_attachment_publish(args: argparse.Namespace) -> None:
    """Widen one note attachment to public (human-only, gate-compatible)."""
    name = str(getattr(args, "name", "") or "")
    assume_yes = bool(getattr(args, "yes", False))
    if not name:
        print("Error: attachment name cannot be empty.", file=sys.stderr)
        sys.exit(1)
    actor = current_actor()
    if actor == "agent" and not _is_gate_option_command():
        print(
            "Error: sase bead attachment publish is human-only; agents cannot "
            "widen an attachment audience. Offer it to the user with /sase_gate.",
            file=sys.stderr,
        )
        sys.exit(1)
    bead_context = resolve_bead_operation_context([args.id])
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        try:
            issue = view.show(resolved_id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        target = _find_note_with_name(issue, name)
        if target is None:
            if _evidence_has_name(issue, name):
                print(
                    f"Error: {strip_display_name(name)} is +1 evidence, whose "
                    "manifest is immutable; publish handles note attachments "
                    "only.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"Error: attachment not found: {strip_display_name(name)} "
                f"on {resolved_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        ordinal, note, attachment = target
        digest = str(getattr(attachment, "sha256", "") or "")
        size_bytes = int(getattr(attachment, "size_bytes", 0) or 0)
        mime_type = str(getattr(attachment, "mime_type", "") or "")
        effective = attachment.effective_visibility()
        note_text = str(getattr(note, "text", "") or "")
    if effective == "public":
        print(f"{strip_display_name(name)} on {resolved_id} is already public.")
        return
    from sase.bead.attachments import provenance as _provenance
    from sase.bead.config import get_attachment_public_max_bytes

    public_max = get_attachment_public_max_bytes()
    if _provenance.bead_store_visibility() == "private":
        print(
            "Error: refusing to publish: the bead store is private "
            "(repos.sidecar.builtin.beads.visibility: private); a private "
            "bead store can never be widened.",
            file=sys.stderr,
        )
        sys.exit(1)
    if size_bytes > public_max:
        print(
            f"Error: refusing to publish: {format_attachment_size(size_bytes)} "
            f"exceeds bead.attachments.public_max_bytes "
            f"({format_attachment_size(public_max)}); large files never go public.",
            file=sys.stderr,
        )
        sys.exit(1)
    metadata = _read_audience_metadata(digest)
    refusal = _metadata_refuses_publish(metadata)
    if refusal:
        print(
            f"Error: refusing to publish {strip_display_name(name)}: SASE "
            f"recorded it under a non-widenable rule ({refusal}).",
            file=sys.stderr,
        )
        sys.exit(1)
    object_path = _ensure_local_bytes(digest, bead_context)
    if object_path is None:
        print(
            f"Error: cannot publish {strip_display_name(name)}: no local "
            f"object for sha256:{digest[:12]} and no shared store copy.",
            file=sys.stderr,
        )
        sys.exit(1)
    scan = _rescan_digest(digest, object_path, public_max)
    if scan is not None and str(scan.get("outcome") or "") == "hit":
        hit = scan.get("hit") or {}
        kind = str(hit.get("kind") or "")
        if kind == "known_value":
            print(
                f"Error: refusing to publish {strip_display_name(name)}: "
                "the current scan still matches a known secret value; "
                "rotate the credential first.",
                file=sys.stderr,
            )
            sys.exit(1)
    try:
        from sase.bead.attachments.upload import discover_public_store

        public_store = discover_public_store(bead_context)
    except Exception:
        public_store = None
    if public_store is None:
        print(
            "Error: no public attachment store on this machine; run "
            "sase repo init to create the <project>--attachments sidecar.",
            file=sys.stderr,
        )
        sys.exit(1)
    label = public_store.describe()
    print(
        f"Publishing {strip_display_name(name)} ({mime_type or 'unknown type'}, "
        f"{format_attachment_size(size_bytes)}) from {resolved_id} to {label}."
    )
    print(f"The bead page for {resolved_id} will link this file publicly.")
    print(
        "Warning: publication is irreversible — forks, clones, caches, and "
        "GitHub's retention of unreachable objects persist. Rotate any "
        "embedded credential first."
    )
    if not _confirm_irreversible(name, assume_yes=assume_yes, verb="publish"):
        print("Publish cancelled; nothing was published.")
        return
    try:
        public_store.put(digest, object_path, size_bytes, mime_type=mime_type or None)
    except TypeError:
        try:
            public_store.put(digest, object_path, size_bytes)
        except Exception as exc:
            print(f"Error: public upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"Error: public upload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    manifest = _manifest_with_visibility(note, digest, "public")
    try:
        project = get_project(bead_context=bead_context)
        project.edit_note(resolved_id, ordinal, note_text, attachments=manifest)
    except Exception as exc:
        print(f"Error: widening the descriptor failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"Published {strip_display_name(name)} · {mime_type or 'unknown type'} · "
        f"{format_attachment_size(size_bytes)} · 🌐 public → {label}"
    )


def handle_bead_attachment_unpublish(args: argparse.Namespace) -> None:
    """Narrow one note attachment to private (agents may run this)."""
    name = str(getattr(args, "name", "") or "")
    assume_yes = bool(getattr(args, "yes", False))
    if not name:
        print("Error: attachment name cannot be empty.", file=sys.stderr)
        sys.exit(1)
    bead_context = resolve_bead_operation_context([args.id])
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        try:
            issue = view.show(resolved_id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        target = _find_note_with_name(issue, name)
        if target is None:
            if _evidence_has_name(issue, name):
                print(
                    f"Error: {strip_display_name(name)} is +1 evidence, whose "
                    "manifest is immutable; unpublish handles note attachments "
                    "only.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"Error: attachment not found: {strip_display_name(name)} "
                f"on {resolved_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        ordinal, note, attachment = target
        digest = str(getattr(attachment, "sha256", "") or "")
        size_bytes = int(getattr(attachment, "size_bytes", 0) or 0)
        mime_type = str(getattr(attachment, "mime_type", "") or "")
        effective = attachment.effective_visibility()
        origin = getattr(attachment, "origin", None)
        note_text = str(getattr(note, "text", "") or "")
    object_path = _ensure_local_bytes(digest, bead_context)
    if object_path is None:
        print(
            f"Error: cannot unpublish {strip_display_name(name)}: no local "
            f"object for sha256:{digest[:12]} and no shared store copy.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from sase.bead.attachments.upload import (
            discover_public_store,
            discover_shared_store,
        )

        public_store = discover_public_store(bead_context)
        private_store = discover_shared_store(bead_context)
    except Exception:
        public_store = None
        private_store = None
    if effective != "public" and (
        public_store is None or not _store_has(public_store, digest)
    ):
        print(f"{strip_display_name(name)} on {resolved_id} is already private.")
        return
    print(
        f"Unpublishing {strip_display_name(name)} "
        f"({format_attachment_size(size_bytes)}) on {resolved_id}: narrowing "
        "the descriptor to 🔒 private."
    )
    if not _confirm_irreversible(name, assume_yes=assume_yes, verb="unpublish"):
        print("Unpublish cancelled; nothing was changed.")
        return
    private_ready = False
    if private_store is not None:
        try:
            if _store_has(private_store, digest):
                private_ready = True
            else:
                private_store.put(digest, object_path, size_bytes)
                private_ready = True
        except TypeError:
            try:
                private_store.put(digest, object_path, size_bytes)
                private_ready = True
            except Exception as exc:
                print(f"Warning: private copy failed: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"Warning: private copy failed: {exc}", file=sys.stderr)
    if not private_ready:
        machine = str(origin or "").strip()
        if not machine:
            try:
                from sase.config import get_machine_name

                machine = str(get_machine_name() or "").strip() or "this machine"
            except Exception:
                machine = "this machine"
        print(f"⚠ only on {machine}: no private shared store; bytes stay local.")
    if public_store is not None and _store_has(public_store, digest):
        try:
            withdraw = getattr(public_store, "withdraw", None)
            if callable(withdraw):
                withdraw(digest)
            else:
                public_store.delete(digest)
        except Exception as exc:
            print(
                f"Error: withdrawing the public object failed: {exc}", file=sys.stderr
            )
            sys.exit(1)
    manifest = _manifest_with_visibility(note, digest, "private")
    try:
        project = get_project(bead_context=bead_context)
        project.edit_note(resolved_id, ordinal, note_text, attachments=manifest)
    except Exception as exc:
        print(f"Error: narrowing the descriptor failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"Unpublished {strip_display_name(name)} (sha256:{digest[:12]}…): "
        "descriptor is now 🔒 private."
    )
    print(
        "Caveat: forks, clones, caches, and GitHub's retention of unreachable "
        "objects persist, so rotate any embedded credential first."
    )
    try:
        from sase.bead.attachments.upload import resolve_project_key

        project_key = resolve_project_key(bead_context)
    except Exception:
        project_key = None
    remote_hint = (
        f"<{project_key or 'project'}--attachments-remote>"
        if project_key
        else "<attachments-remote>"
    )
    _ = mime_type
    print(
        "To erase the bytes from the public repo history (attachments repo "
        "only, not beads):\n"
        f"  git clone --bare {remote_hint} /tmp/attachments-scrub\n"
        f"  git -C /tmp/attachments-scrub filter-repo --path "
        f"files/objects/sha256/{digest[:2]}/{digest} --invert-paths --force\n"
        "  git -C /tmp/attachments-scrub push --force --all"
    )


def _store_has(store: Any, digest: str) -> bool:
    """Return whether *store* holds *digest*, never raising."""
    try:
        return bool(store.has(digest))
    except Exception:
        return False


__all__ = [
    "GATE_COMMAND_ENV",
    "_WITHDRAW_COMMIT_PREFIX",
    "current_actor",
    "handle_bead_attachment_publish",
    "handle_bead_attachment_unpublish",
]
