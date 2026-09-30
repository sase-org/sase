"""Audience decision wiring for bead attachment authoring.

Python gathers provenance facts, scans the ingested CAS object, and calls
the core ``attachment_audience_decision`` table. Reasons stay local: they
appear in the echo, local JSON, and CAS audience metadata, never in
descriptors or bead records.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any


def audience_enabled() -> bool:
    """Return whether the ``public_bead_attachments`` beta flag is on."""
    try:
        from sase.feature_flags import current_flags
        from sase.feature_flags.registry import FeatureFlag

        return bool(current_flags().enabled(FeatureFlag.public_bead_attachments))
    except Exception:
        return False


def requested_from_flags(
    *,
    private: bool = False,
    public: bool = False,
    local_only: bool = False,
) -> str:
    """Map CLI audience flags to a core ``requested`` value."""
    if local_only:
        return "local_only"
    if private:
        return "private"
    if public:
        return "public"
    return "auto"


def validate_audience_flags(
    *,
    private: bool,
    public: bool,
    allow_sensitive: bool,
    local_only: bool,
    has_attachments: bool,
) -> list[str]:
    """Validate ``-K``/``-W``/``-S``/``-L`` combinations.

    Returns dim ``hint:`` warning rows (empty when nothing to warn about).
    Exits non-zero on mutually exclusive or incompatible combinations.
    """
    if private and public:
        print(
            "Error: -K/--private and -W/--public are mutually exclusive.",
            file=sys.stderr,
        )
        sys.exit(1)
    if public and local_only:
        print(
            "Error: -W/--public cannot be combined with -L/--local-only.",
            file=sys.stderr,
        )
        sys.exit(1)
    if public and allow_sensitive:
        print(
            "Error: -W/--public cannot be combined with -S/--allow-sensitive.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not has_attachments and (private or public):
        return ["hint: audience flags ignored (no attachments in this invocation)"]
    return []


def refuse_public_when_flag_off() -> None:
    """Refuse ``-W`` with an enable hint when the beta flag is off."""
    print(
        "Error: -W/--public needs the public_bead_attachments beta flag "
        "(sase flag enable public_bead_attachments).",
        file=sys.stderr,
    )
    sys.exit(1)


def gather_audience_facts(
    *,
    source_path: Path | None,
    size_bytes: int,
    attachment_class: str,
    scan: dict[str, Any] | None,
    requested: str,
    actor: str | None = None,
    confirmed: bool = False,
    allow_sensitive: bool = False,
    public_max_bytes: int | None = None,
) -> dict[str, Any]:
    """Build an ``AttachmentAudienceFactsWire`` dict for one attachment."""
    from sase.bead.attachments import provenance
    from sase.bead.attachments.remote_visibility import resolve_remote_visibility
    from sase.bead.config import get_attachment_public_max_bytes

    home = str(Path.home())
    try:
        from sase.core.paths import sase_home

        sase_home_str = str(sase_home())
    except Exception:
        sase_home_str = str(Path.home() / ".sase")
    try:
        from sase.bead.config import get_attachment_sensitive_patterns

        extra_patterns = get_attachment_sensitive_patterns()
    except Exception:
        extra_patterns = []
    max_bytes = (
        public_max_bytes
        if public_max_bytes is not None
        else get_attachment_public_max_bytes()
    )
    resolved_actor = actor or provenance.current_actor()
    checkout: dict[str, Any] | None = None
    path_str: str | None = None
    owner_only = False
    produced: bool | None = None
    if source_path is not None:
        try:
            path_str = str(source_path.resolve())
        except OSError:
            path_str = str(source_path)
        owner_only = provenance.is_owner_only(source_path)
        facts = provenance.checkout_facts(source_path)
        produced = provenance.produced_during_run(source_path)
        if facts is not None:
            remote_visibility = "unknown"
            origin_url = facts.get("origin_url")
            if isinstance(origin_url, str) and origin_url:
                # Pre-decision shortcut: unknown can only make the result
                # more private, so skip the network probe when a public
                # remote could not change a non-public outcome.
                pre = _pre_decision(
                    bead_store_visibility=provenance.bead_store_visibility(),
                    requested=requested,
                    actor=resolved_actor,
                    confirmed=confirmed,
                    allow_sensitive=allow_sensitive,
                    path=path_str,
                    home=home,
                    sase_home=sase_home_str,
                    extra_patterns=extra_patterns,
                    size_bytes=size_bytes,
                    public_max_bytes=max_bytes,
                    attachment_class=attachment_class,
                    scan=scan,
                    owner_only=owner_only,
                    checkout={
                        "root": str(facts.get("root") or ""),
                        "remote_visibility": "public",
                        "ignored": bool(facts.get("ignored", False)),
                        "tracked_identical_to_remote": bool(
                            facts.get("tracked_identical_to_remote", False)
                        ),
                    },
                    produced=produced,
                )
                if pre is not None and str(pre.get("outcome") or "") != "public":
                    remote_visibility = "unknown"
                else:
                    remote_visibility = resolve_remote_visibility(origin_url)
            else:
                remote_visibility = "unknown"
            checkout = {
                "root": str(facts.get("root") or ""),
                "remote_visibility": remote_visibility,
                "ignored": bool(facts.get("ignored", False)),
                "tracked_identical_to_remote": bool(
                    facts.get("tracked_identical_to_remote", False)
                ),
            }
    try:
        workspace = provenance.workspace_root()
    except Exception:
        workspace = None
    try:
        scratches = provenance.scratch_roots()
    except Exception:
        scratches = []
    return {
        "bead_store_visibility": provenance.bead_store_visibility(),
        "requested": requested,
        "actor": resolved_actor,
        "confirmed": confirmed,
        "allow_sensitive": allow_sensitive,
        "path": path_str,
        "home": home,
        "sase_home": sase_home_str,
        "extra_sensitive_patterns": extra_patterns,
        "size_bytes": size_bytes,
        "public_max_bytes": max_bytes,
        "class": attachment_class,
        "scan": scan,
        "owner_only": owner_only,
        "checkout": checkout,
        "workspace_root": workspace,
        "scratch_roots": scratches,
        "produced_during_run": produced,
    }


def _pre_decision(
    *,
    bead_store_visibility: str,
    requested: str,
    actor: str,
    confirmed: bool,
    allow_sensitive: bool,
    path: str | None,
    home: str,
    sase_home: str,
    extra_patterns: list[str],
    size_bytes: int,
    public_max_bytes: int,
    attachment_class: str,
    scan: dict[str, Any] | None,
    owner_only: bool,
    checkout: dict[str, Any] | None,
    produced: bool | None,
) -> dict[str, Any] | None:
    """Run the core decision with a public remote, or None when unavailable."""
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_audience_decision")
    except Exception:
        return None
    try:
        from sase.bead.attachments import provenance

        facts = {
            "bead_store_visibility": bead_store_visibility,
            "requested": requested,
            "actor": actor,
            "confirmed": confirmed,
            "allow_sensitive": allow_sensitive,
            "path": path,
            "home": home,
            "sase_home": sase_home,
            "extra_sensitive_patterns": extra_patterns,
            "size_bytes": size_bytes,
            "public_max_bytes": public_max_bytes,
            "class": attachment_class,
            "scan": scan,
            "owner_only": owner_only,
            "checkout": checkout,
            "workspace_root": provenance.workspace_root(),
            "scratch_roots": provenance.scratch_roots(),
            "produced_during_run": produced,
        }
        return dict(binding(facts))
    except Exception:
        return None


def decide_audience(facts: dict[str, Any]) -> dict[str, Any]:
    """Call the core audience table; fail private when the binding is missing."""
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_audience_decision")
        return dict(binding(facts))
    except Exception:
        rule = "fail_private"
        return {
            "outcome": "private",
            "rule": rule,
            "reason": "audience decision unavailable",
            "widenable": True,
        }


def scan_cas_object(
    object_path: Path,
    *,
    max_bytes: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Scan the ingested CAS object; None when the binding is missing."""
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_scan_file")
    except Exception:
        return None
    home = str(Path.home())
    try:
        from sase.core.paths import sase_home

        sase_home_str = str(sase_home())
    except Exception:
        sase_home_str = str(Path.home() / ".sase")
    capture = dict(os.environ) if env is None else dict(env)
    try:
        return dict(binding(str(object_path), max_bytes, capture, home, sase_home_str))
    except Exception:
        return None


def _scanner_rules_version() -> int:
    """Return the core scanner rules version, or 1 when unavailable."""
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_scanner_rules_version")
        return int(binding())
    except Exception:
        return 1


def audience_metadata_path(sha256: str) -> Path:
    """Return the local CAS audience metadata path for *sha256*."""
    from sase.bead.attachments.store import default_store_root

    root = default_store_root()
    return root / "audience" / "sha256" / sha256[:2] / f"{sha256}.json"


def write_audience_metadata(
    *,
    sha256: str,
    rule: str,
    reason: str,
    explicit: bool,
) -> None:
    """Write local-only audience metadata (never published)."""
    try:
        path = audience_metadata_path(sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "rule": rule,
            "reason": reason,
            "explicit": explicit,
            "scanner_rules_version": _scanner_rules_version(),
            "decided_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def read_audience_reason(sha256: str) -> str | None:
    """Return the local audience reason for *sha256*, if recorded.

    The reason lives only in the machine-local CAS audience metadata; it
    never enters descriptors, pages, or commit messages. Returns ``None``
    when no metadata exists or it carries no reason. Never raises.
    """
    try:
        raw = audience_metadata_path(sha256).read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    return reason.strip()


def duplicate_private_digest(digests: list[str], notes: Any) -> set[str]:
    """Return digests already stored privately in *notes* (duplicate intent)."""
    private: set[str] = set()
    try:
        for note in notes or ():
            for attachment in getattr(note, "attachments", ()) or ():
                sha = str(getattr(attachment, "sha256", "") or "")
                if not sha or sha not in digests:
                    continue
                visibility = getattr(attachment, "visibility", None)
                effective = (
                    visibility
                    if visibility in ("public", "private")
                    else getattr(
                        attachment, "effective_visibility", lambda: "private"
                    )()
                    if callable(getattr(attachment, "effective_visibility", None))
                    else "private"
                )
                if effective != "public":
                    private.add(sha)
    except Exception:
        pass
    return private


def confirm_widening(
    filename: str, reason: str, *, confirmed: bool, actor: str
) -> bool:
    """Confirm a human widening on a TTY; ``-y`` skips the prompt."""
    if confirmed:
        return True
    if actor != "human":
        return False
    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False
    try:
        answer = (
            input(
                f"Publish {filename} publicly? SASE classified it private ({reason}). [y/N] "
            )
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def refuse_agent_widening(filename: str, reason: str, digest: str) -> None:
    """Refuse an agent ``--public`` before any bead event is written."""
    _ = digest
    print(
        f"refusing --public for {filename}: SASE classified it private ({reason}).",
        file=sys.stderr,
    )
    print(
        "Re-run without --public; it will be stored privately. "
        "A human can publish it later:",
        file=sys.stderr,
    )
    print("  sase bead attachment publish sase-ab " + filename, file=sys.stderr)
    print("Offer that command to the user with /sase_gate.", file=sys.stderr)
    sys.exit(1)


__all__ = [
    "audience_enabled",
    "audience_metadata_path",
    "confirm_widening",
    "decide_audience",
    "duplicate_private_digest",
    "gather_audience_facts",
    "read_audience_reason",
    "refuse_agent_widening",
    "refuse_public_when_flag_off",
    "requested_from_flags",
    "scan_cas_object",
    "validate_audience_flags",
    "write_audience_metadata",
]
