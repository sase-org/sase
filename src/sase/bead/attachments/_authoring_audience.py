"""Audience decisions and stdin wire for note attachments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._authoring_common import finish_wire
from ._authoring_models import NoteAttachmentAuthoringError

if TYPE_CHECKING:
    from collections.abc import Mapping


def decide_visibilities(
    resolved: dict[int, Path],
    blobs: dict[Path, Any],
    assigned: dict[int, str],
    *,
    notes: Any = (),
    allow_sensitive: bool = False,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
    audience_actor: str | None = None,
) -> dict[Path, dict[str, Any]]:
    """Run the audience decision per unique ingested path.

    Returns a map from resolved path to ``{"visibility", "reason",
    "rule", "explicit"}``. With the beta flag off, returns an empty map
    (no visibility is written). Exits non-zero before any bead event is
    written on agent-widening refusals and non-widenable ``--public``
    requests.
    """
    from sase.bead.attachments import audience as _audience

    if not _audience.audience_enabled():
        return {}
    from sase.bead.config import get_attachment_public_max_bytes

    public_max = get_attachment_public_max_bytes()
    try:
        from sase.bead.attachments import provenance as _provenance

        actor = audience_actor or _provenance.current_actor()
    except Exception:
        actor = audience_actor or "agent"
    # Duplicate intent: digests already stored privately stay private on auto.
    try:
        all_digests = [blobs[target].sha256 for target in set(resolved.values())]
        dup_private = _audience.duplicate_private_digest(all_digests, notes)
    except Exception:
        dup_private = set()
    visibilities: dict[Path, dict[str, Any]] = {}
    seen: set[Path] = set()
    for index in sorted(resolved):
        target = resolved[index]
        if target in seen:
            continue
        seen.add(target)
        blob = blobs[target]
        filename = assigned.get(index, target.name)
        # Classify from the ingested head (matches the stored MIME type).
        try:
            from sase.core.rust import require_rust_binding

            classify_binding = require_rust_binding("classify_attachment")
            classified: dict[str, Any] = dict(
                classify_binding(filename, bytes(blob.head))
            )
            attachment_class = str(classified.get("class") or "binary")
        except Exception:
            attachment_class = "binary"
        # Scan the CAS object for text classes up to the public cap.
        scan: dict[str, Any] | None = None
        try:
            scan = _audience.scan_cas_object(
                Path(str(blob.object_path)), max_bytes=public_max
            )
        except Exception:
            scan = None
        facts = _audience.gather_audience_facts(
            source_path=target,
            size_bytes=int(blob.size_bytes),
            attachment_class=attachment_class,
            scan=scan,
            requested=audience_requested,
            actor=actor,
            confirmed=audience_confirmed,
            allow_sensitive=allow_sensitive,
            public_max_bytes=public_max,
        )
        decision = _audience.decide_audience(facts)
        outcome = str(decision.get("outcome") or "private")
        rule = str(decision.get("rule") or "fail_private")
        reason = str(decision.get("reason") or "no public evidence")
        if outcome == "refuse":
            if audience_requested == "public" and actor == "agent":
                _audience.refuse_agent_widening(filename, reason, str(blob.sha256))
            import sys as _sys

            print(
                f"Error: refusing --public for {filename}: {reason}.",
                file=_sys.stderr,
            )
            raise NoteAttachmentAuthoringError(
                f"refusing --public for {filename}: {reason} — nothing was written."
            )
        if outcome == "confirm":
            confirmed_now = _audience.confirm_widening(
                filename, reason, confirmed=audience_confirmed, actor=actor
            )
            if confirmed_now:
                facts = _audience.gather_audience_facts(
                    source_path=target,
                    size_bytes=int(blob.size_bytes),
                    attachment_class=attachment_class,
                    scan=scan,
                    requested=audience_requested,
                    actor=actor,
                    confirmed=True,
                    allow_sensitive=allow_sensitive,
                    public_max_bytes=public_max,
                )
                decision = _audience.decide_audience(facts)
                outcome = str(decision.get("outcome") or "private")
                rule = str(decision.get("rule") or "fail_private")
                reason = str(decision.get("reason") or "human confirmed widening")
            else:
                if actor != "human":
                    _audience.refuse_agent_widening(filename, reason, str(blob.sha256))
                outcome = "private"
                rule = str(decision.get("rule") or "fail_private")
                reason = f"{reason} (staying private without confirmation)"
        # Duplicate-digest intent: an auto decision stays private with a warn.
        explicit = audience_requested in ("public", "private", "local_only")
        if (
            outcome == "public"
            and audience_requested == "auto"
            and str(blob.sha256) in dup_private
        ):
            outcome = "private"
            rule = "explicit"
            reason = "same bytes already stored privately"
            explicit = False
        visibility = "public" if outcome == "public" else "private"
        if outcome == "local_only":
            visibility = "private"
        _audience.write_audience_metadata(
            sha256=str(blob.sha256), rule=rule, reason=reason, explicit=explicit
        )
        visibilities[target] = {
            "visibility": visibility,
            "outcome": outcome,
            "reason": reason,
            "rule": rule,
            "explicit": explicit,
        }
    return visibilities


def stream_attachment_wire(
    candidate_name: str,
    *,
    sha256: str,
    size_bytes: int,
    head: bytes,
    object_path: object,
    roster: Mapping[str, dict[str, Any]],
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
    audience_actor: str | None = None,
    allow_sensitive: bool = False,
) -> tuple[dict[str, Any], str]:
    """Uniquify *candidate_name* against *roster* and build its wire + echo.

    Stdin attachments run the same decision and scan flow with ``path=None``
    (stdin always fails private unless explicitly narrowed). Returns the
    wire dict and the stderr echo row.
    """
    from sase.config import get_machine_name
    from sase.core.rust import require_rust_binding

    sanitize_binding = require_rust_binding("sanitize_attachment_name")
    unique_binding = require_rust_binding("unique_attachment_name")
    sanitized = str(sanitize_binding(candidate_name))
    existing = [
        {"name": name, "sha256": wire["sha256"]} for name, wire in roster.items()
    ]
    name = str(unique_binding(sanitized, sha256, existing))
    visibility: str | None = None
    reason: str | None = None
    outcome: str | None = None
    from sase.bead.attachments import audience as _audience

    if _audience.audience_enabled():
        try:
            classify_binding = require_rust_binding("classify_attachment")
            classified: dict[str, Any] = dict(classify_binding(name, bytes(head)))
            attachment_class = str(classified.get("class") or "binary")
        except Exception:
            attachment_class = "binary"
        from sase.bead.config import get_attachment_public_max_bytes

        public_max = get_attachment_public_max_bytes()
        scan: dict[str, Any] | None = None
        try:
            scan = _audience.scan_cas_object(
                Path(str(object_path)), max_bytes=public_max
            )
        except Exception:
            scan = None
        try:
            from sase.bead.attachments import provenance as _provenance

            actor = audience_actor or _provenance.current_actor()
        except Exception:
            actor = audience_actor or "agent"
        facts = _audience.gather_audience_facts(
            source_path=None,
            size_bytes=size_bytes,
            attachment_class=attachment_class,
            scan=scan,
            requested=audience_requested,
            actor=actor,
            confirmed=audience_confirmed,
            allow_sensitive=allow_sensitive,
            public_max_bytes=public_max,
        )
        decision = _audience.decide_audience(facts)
        outcome = str(decision.get("outcome") or "private")
        rule = str(decision.get("rule") or "fail_private")
        reason = str(decision.get("reason") or "no public evidence")
        if outcome == "refuse":
            if audience_requested == "public" and actor == "agent":
                _audience.refuse_agent_widening(name, reason, sha256)
            raise NoteAttachmentAuthoringError(
                f"refusing --public for {name}: {reason} — nothing was written."
            )
        if outcome == "confirm":
            confirmed_now = _audience.confirm_widening(
                name, reason, confirmed=audience_confirmed, actor=actor
            )
            if confirmed_now:
                facts = _audience.gather_audience_facts(
                    source_path=None,
                    size_bytes=size_bytes,
                    attachment_class=attachment_class,
                    scan=scan,
                    requested=audience_requested,
                    actor=actor,
                    confirmed=True,
                    allow_sensitive=allow_sensitive,
                    public_max_bytes=public_max,
                )
                decision = _audience.decide_audience(facts)
                outcome = str(decision.get("outcome") or "private")
                rule = str(decision.get("rule") or "fail_private")
                reason = str(decision.get("reason") or "human confirmed widening")
            else:
                if actor != "human":
                    _audience.refuse_agent_widening(name, reason, sha256)
                outcome = "private"
                reason = f"{reason} (staying private without confirmation)"
        visibility = "public" if outcome == "public" else "private"
        _audience.write_audience_metadata(
            sha256=sha256,
            rule=rule,
            reason=reason,
            explicit=audience_requested in ("public", "private", "local_only"),
        )
    wire, echo_row = finish_wire(
        name=name,
        sanitized=sanitized,
        sha256=sha256,
        size_bytes=size_bytes,
        head=head,
        object_path=object_path,
        origin=get_machine_name() or None,
        visibility=visibility,
        reason=reason,
        outcome=outcome,
    )
    return wire, echo_row
