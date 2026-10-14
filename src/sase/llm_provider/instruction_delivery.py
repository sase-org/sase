"""Instruction delivery plan, active delivery, and adapter accessors (E3).

The boundary resolves a :class:`DeliveryPlan` from the
``llm_instruction_delivery`` hook, renders bundles, and exposes an
:class:`ActiveInstructionDelivery` to adapters through
:func:`current_instruction_delivery`. A missing hook, a hook error, or an
invalid return resolves to legacy native discovery and never raises.
"""

from __future__ import annotations

import logging
import os
import re
import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.instruction_manifest import INSTRUCTION_MANIFEST_FALLBACK_REASONS
from sase.core.paths import get_sase_managed_tmpdir
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.feature_flags.managed import project_is_sase_managed
from sase.instructions.fingerprints import CONTRACT_HEADING, HELPER_TEMPLATE_FIRST_LINE

log = logging.getLogger(__name__)

#: Shared channel ids (epic plan decision 13).
CHANNEL_CLAUDE_ROOT = "claude.append_system_prompt_file"
CHANNEL_CLAUDE_SUBAGENT = "claude.append_subagent_system_prompt_file"
CHANNEL_CODEX_ROOT = "codex.developer_instructions"
CHANNEL_GROK_ROOT = "grok.rules"
CHANNEL_MUSE_ROOT = "muse.prompt_prefix"

CHANNEL_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
MARKER_RE = re.compile(
    r"<!-- sase-instructions bundle=([0-9a-f]{12}) invocation=([0-9a-fA-F-]+) -->"
)

ROOT_STATUSES = frozenset({"explicit", "inherits_native"})
SLOT_STATUSES = frozenset({"explicit", "inherits_native", "inherits_root", "none"})
NOTIFY_REASONS = frozenset(
    {"render_failed", "invalid_bundle", "oversize", "delivery_failed"}
)

_VERSION_CACHE: dict[tuple[str, int, int], str | None] = {}
_CURRENT: ContextVar[ActiveInstructionDelivery | None] = ContextVar(
    "sase_instruction_delivery", default=None
)

_NOTIFY_SENDER = "instructions"
_NOTIFY_ICON = "!"
_NOTIFY_COLOR = "#D14343"
_NOTIFY_CATEGORY = "instruction-fallback"


@dataclass(frozen=True)
class SlotPlan:
    """One actor slot in a delivery plan."""

    status: str
    channel: str | None = None
    max_bytes: int | None = None
    reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class DeliveryPlan:
    """Resolved root and subagent slots for one invocation."""

    root: SlotPlan
    subagent: SlotPlan


@dataclass
class ActiveSlot:
    """Live slot state adapters read and report against."""

    plan: SlotPlan
    text: str | None = None
    sha256: str | None = None
    fallback: dict[str, str] | None = None


@dataclass
class ActiveInstructionDelivery:
    """Per-invocation delivery exposed to adapters through the contextvar."""

    invocation_id: str
    provider: str
    root: ActiveSlot
    subagent: ActiveSlot
    session_ids: list[str] = field(default_factory=list)

    def record_session(self, session_id: str) -> None:
        """Append *session_id* once; empty values are ignored."""
        if not session_id or session_id in self.session_ids:
            return
        self.session_ids.append(session_id)

    def report_fallback(
        self, slot: str, reason: str, detail: str | None = None
    ) -> None:
        """Record a per-slot fallback and notify when the reason is reportable."""
        if reason not in INSTRUCTION_MANIFEST_FALLBACK_REASONS:
            reason = "delivery_failed"
        active = self._slot(slot)
        payload: dict[str, str] = {"reason": reason}
        if detail:
            payload["detail"] = detail
        active.fallback = payload
        if active.plan.status == "explicit":
            active.plan = SlotPlan(
                status="inherits_native",
                reason=reason,
                detail=detail,
            )
        notify_instruction_fallback(self.provider, reason, detail=detail)

    @contextmanager
    def materialize(self, slot: str) -> Iterator[Path | None]:
        """Write a private 0600 file of the slot's delivered text, then unlink it.

        On any write failure, reports ``delivery_failed`` and yields ``None``.
        """
        active = self._slot(slot)
        path: Path | None = None
        fd: int | None = None
        try:
            if not active.text:
                raise RuntimeError(f"no delivered text for slot {slot!r}")
            directory = Path(
                get_sase_managed_tmpdir("instruction-delivery", self.invocation_id)
            )
            path = directory / f"{slot}.md"
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.fchmod(fd, 0o600)
            os.write(fd, active.text.encode("utf-8"))
            os.close(fd)
            fd = None
        except Exception as exc:  # noqa: BLE001 - materialize never raises to adapters.
            self.report_fallback(slot, "delivery_failed", str(exc)[:2000])
            path = None
        try:
            yield path
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _slot(self, slot: str) -> ActiveSlot:
        if slot == "root":
            return self.root
        if slot == "subagent":
            return self.subagent
        raise ValueError(f"unknown delivery slot {slot!r}")


LEGACY_PLAN = DeliveryPlan(
    root=SlotPlan(status="inherits_native", reason="provider_legacy"),
    subagent=SlotPlan(status="inherits_native", reason="provider_legacy"),
)


def legacy_instruction_delivery(*, reason: str = "provider_legacy") -> dict[str, Any]:
    """Return the declared-legacy hook payload for built-in providers."""
    slot = {"status": "inherits_native", "reason": reason}
    return {"root": dict(slot), "subagent": dict(slot)}


def current_instruction_delivery() -> ActiveInstructionDelivery | None:
    """Return the active delivery for this invocation, or ``None``."""
    return _CURRENT.get()


def bind_instruction_delivery(
    delivery: ActiveInstructionDelivery | None,
) -> Token[ActiveInstructionDelivery | None]:
    """Install *delivery* as the current active delivery and return the token."""
    return _CURRENT.set(delivery)


def reset_instruction_delivery(
    token: Token[ActiveInstructionDelivery | None],
) -> None:
    """Restore the previous active delivery from *token*."""
    _CURRENT.reset(token)


def delivered_text(bundle_text: str, sha256: str, invocation_id: str) -> str:
    """Return *bundle_text* plus the trailing bundle marker line."""
    marker = (
        f"<!-- sase-instructions bundle={sha256[:12]} invocation={invocation_id} -->"
    )
    body = bundle_text if bundle_text.endswith("\n") else f"{bundle_text}\n"
    return f"{body}{marker}\n"


def resolve_delivery_plan(provider: Any) -> DeliveryPlan:
    """Return a validated plan for *provider*; never raises."""
    try:
        method = getattr(provider, "instruction_delivery", None)
        raw = method() if callable(method) else None
    except Exception:  # noqa: BLE001 - hook errors resolve to legacy.
        return LEGACY_PLAN
    parsed = _parse_plan(raw)
    return parsed if parsed is not None else LEGACY_PLAN


def sase_owned_instruction_paths(cwd: str | Path | None = None) -> tuple[Path, ...]:
    """Return exact SASE-owned instruction file paths for native suppression.

    Includes the project root ``AGENTS.md`` and ``CLAUDE.md`` when the project
    is SASE-managed, and ``~/AGENTS.md`` / ``~/CLAUDE.md`` when those files
    carry the contract heading. Never a glob.
    """
    paths: list[Path] = []
    start = Path(cwd) if cwd is not None else Path.cwd()
    if project_is_sase_managed(start):
        from sase.content_layout import discover_project_root

        root = discover_project_root(start) or start
        for name in ("AGENTS.md", "CLAUDE.md"):
            paths.append((root / name).resolve())
    home = Path.home()
    for name in ("AGENTS.md", "CLAUDE.md"):
        candidate = home / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if CONTRACT_HEADING in text:
            paths.append(candidate.resolve())
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


def probe_provider_cli_version(provider: Any) -> str | None:
    """Return a cached CLI version for *provider*, or ``None`` on failure.

    One subprocess per executable fingerprint (path, size, mtime).
    """
    try:
        name = provider.provider_name()
    except Exception:  # noqa: BLE001 - version probe fails open.
        return None
    if not isinstance(name, str) or not name:
        return None
    try:
        from sase.agent_clis.detect import probe_version, resolve_executable
        from sase.llm_provider.registry import get_llm_metadata_payload

        payload = get_llm_metadata_payload()
        providers = payload.get("providers")
        meta = providers.get(name) if isinstance(providers, Mapping) else None
        if not isinstance(meta, Mapping):
            return None
        cli_name = meta.get("autodetect_cli_name")
        if not isinstance(cli_name, str) or not cli_name:
            return None
        executable = resolve_executable(cli_name)
        if not executable:
            return None
        stat = os.stat(executable)
        key = (executable, int(stat.st_size), int(stat.st_mtime_ns))
        if key in _VERSION_CACHE:
            return _VERSION_CACHE[key]
        install = meta.get("install")
        install_map = install if isinstance(install, Mapping) else {}
        raw_argv = install_map.get("version_argv")
        version_argv = (
            tuple(str(part) for part in raw_argv)
            if isinstance(raw_argv, (list, tuple)) and raw_argv
            else ("--version",)
        )
        version_regex = install_map.get("version_regex")
        regex = version_regex if isinstance(version_regex, str) else None
        probe = probe_version(
            executable, version_argv=version_argv, version_regex=regex
        )
        _VERSION_CACHE[key] = probe.version
        return probe.version
    except Exception:  # noqa: BLE001 - version probe fails open.
        return None


def notify_instruction_fallback(
    provider: str,
    reason: str,
    *,
    detail: str | None = None,
) -> None:
    """Upsert one host/provider/reason/day notification; declared states skip."""
    if reason not in NOTIFY_REASONS:
        return
    try:
        from sase.notifications.models import Notification, normalize_notification_tags
        from sase.notifications.store import (
            notifications_file_path,
            upsert_notification,
        )
    except Exception:  # noqa: BLE001 - notification must never break invoke.
        log.debug("instruction fallback notification import failed", exc_info=True)
        return
    host = _short_host()
    day = datetime.now(UTC).date().isoformat()
    dedup_key = f"instructions:fallback:{host}:{provider}:{reason}:{day}"
    try:
        path = notifications_file_path()
    except Exception:  # noqa: BLE001 - notification must never break invoke.
        return
    if not best_effort_test_state_write_allowed(path, category=_NOTIFY_CATEGORY):
        return
    notes = [
        f"Instruction delivery fell back to legacy for {provider}: {reason}",
    ]
    if detail:
        notes.append(detail[:2000])
    notification = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        sender=_NOTIFY_SENDER,
        icon=_NOTIFY_ICON,
        color=_NOTIFY_COLOR,
        notes=notes,
        tags=normalize_notification_tags(
            ["instructions", "fallback", provider, reason]
        ),
        dedup_key=dedup_key,
    )
    try:
        upsert_notification(
            notification,
            plus_one_note=f"Repeated {reason} fallback",
            plus_one_timestamp=notification.timestamp,
        )
    except Exception:  # noqa: BLE001 - notification must never break invoke.
        log.debug("instruction fallback notification failed", exc_info=True)


def helper_bundle_is_valid(text: str) -> bool:
    """Return whether *text* is a helper bundle (heading present, no contract)."""
    return HELPER_TEMPLATE_FIRST_LINE in text and CONTRACT_HEADING not in text


def root_bundle_is_valid(text: str, *, provider: str, sections: Any) -> bool:
    """Return whether *text* is a valid explicit root bundle."""
    if text.count(CONTRACT_HEADING) != 1:
        return False
    from sase.instructions.directives import has_provider_directive

    if not has_provider_directive(provider):
        return True
    section_id = f"pkg.provider.{provider}"
    if not isinstance(sections, (list, tuple)):
        return False
    return any(
        isinstance(section, Mapping)
        and section.get("id") == section_id
        and section.get("status") == "included"
        for section in sections
    )


def fallback_wire(slot: SlotPlan | ActiveSlot) -> dict[str, str] | None:
    """Return the v2 fallback block for a non-explicit slot, if any."""
    if isinstance(slot, ActiveSlot):
        if slot.fallback:
            return dict(slot.fallback)
        plan = slot.plan
    else:
        plan = slot
    if plan.status == "explicit" or not plan.reason:
        return None
    payload: dict[str, str] = {"reason": plan.reason}
    if plan.detail:
        payload["detail"] = plan.detail
    return payload


def subagent_wire(slot: ActiveSlot) -> dict[str, Any]:
    """Return the v2 ``delivery.subagent`` mapping for *slot*."""
    payload: dict[str, Any] = {"status": slot.plan.status}
    if slot.plan.status == "explicit":
        if slot.plan.channel:
            payload["channel"] = slot.plan.channel
        if slot.sha256:
            payload["bundle_sha256"] = slot.sha256
    fallback = fallback_wire(slot)
    if fallback is not None and slot.plan.status == "inherits_native":
        payload["fallback"] = fallback
    return payload


def _parse_plan(raw: Any) -> DeliveryPlan | None:
    if not isinstance(raw, Mapping):
        return None
    root = _parse_slot(raw.get("root"), root=True)
    subagent = _parse_slot(raw.get("subagent"), root=False)
    if root is None or subagent is None:
        return None
    return DeliveryPlan(root=root, subagent=subagent)


def _parse_slot(raw: Any, *, root: bool) -> SlotPlan | None:
    if not isinstance(raw, Mapping):
        return None
    status = raw.get("status")
    allowed = ROOT_STATUSES if root else SLOT_STATUSES
    if status not in allowed:
        return None
    channel = raw.get("channel")
    if channel is not None and (
        not isinstance(channel, str) or not CHANNEL_RE.fullmatch(channel)
    ):
        return None
    if status == "explicit" and not channel:
        return None
    max_bytes = raw.get("max_bytes")
    if max_bytes is not None and (
        isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0
    ):
        return None
    reason = raw.get("reason")
    if reason is not None and reason not in INSTRUCTION_MANIFEST_FALLBACK_REASONS:
        return None
    detail = raw.get("detail")
    if detail is not None and not isinstance(detail, str):
        return None
    return SlotPlan(
        status=str(status),
        channel=channel if status == "explicit" else None,
        max_bytes=max_bytes if status == "explicit" else None,
        reason=reason if isinstance(reason, str) else None,
        detail=detail if isinstance(detail, str) else None,
    )


def _short_host() -> str:
    try:
        return socket.gethostname().split(".", 1)[0] or "unknown"
    except OSError:
        return "unknown"


__all__ = [
    "CHANNEL_CLAUDE_ROOT",
    "CHANNEL_CLAUDE_SUBAGENT",
    "CHANNEL_CODEX_ROOT",
    "CHANNEL_GROK_ROOT",
    "CHANNEL_MUSE_ROOT",
    "CHANNEL_RE",
    "HELPER_TEMPLATE_FIRST_LINE",
    "LEGACY_PLAN",
    "MARKER_RE",
    "ActiveInstructionDelivery",
    "ActiveSlot",
    "DeliveryPlan",
    "SlotPlan",
    "bind_instruction_delivery",
    "current_instruction_delivery",
    "delivered_text",
    "fallback_wire",
    "helper_bundle_is_valid",
    "legacy_instruction_delivery",
    "notify_instruction_fallback",
    "probe_provider_cli_version",
    "reset_instruction_delivery",
    "resolve_delivery_plan",
    "root_bundle_is_valid",
    "sase_owned_instruction_paths",
    "subagent_wire",
]
