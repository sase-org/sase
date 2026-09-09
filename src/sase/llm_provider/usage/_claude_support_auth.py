"""Claude auth-status classification and secret-scrubbed context material."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.llm_provider.usage._claude_support_command import ClaudeCommandResult
from sase.llm_provider.usage._claude_support_text import normalize_text

log = logging.getLogger(__name__)

_SECRET_FIELD_MARKERS = ("token", "secret", "password", "credential", "key")


@dataclass(frozen=True)
class ClaudeAuthInfo:
    """Sanitized Claude auth status classification."""

    mode: str | None
    plan: str | None = None
    context_material: tuple[str, ...] = ()


def auth_info_from_result(result: ClaudeCommandResult) -> ClaudeAuthInfo:
    """Classify Claude auth status output without retaining secrets."""
    if result.returncode != 0:
        return status_from_auth_text(f"{result.stdout}\n{result.stderr}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return status_from_auth_text(result.stdout)
    if not isinstance(payload, Mapping):
        return ClaudeAuthInfo(mode=None)
    mode = _auth_mode_from_payload(payload)
    plan = _extract_plan_from_payload(payload)
    material = tuple(sorted(_auth_context_material(payload)))
    return ClaudeAuthInfo(mode=mode, plan=plan, context_material=material)


def status_from_auth_text(text: str) -> ClaudeAuthInfo:
    """Classify plain-text Claude auth or usage output."""
    normalized = normalize_text(text).casefold()
    if _looks_logged_out(normalized):
        return ClaudeAuthInfo(mode="logged_out")
    if _looks_api_mode(normalized):
        return ClaudeAuthInfo(mode="api")
    if _looks_subscription_mode(normalized):
        return ClaudeAuthInfo(mode="subscription")
    return ClaudeAuthInfo(mode=None)


def extract_plan(result_text: str) -> str | None:
    """Extract a non-secret plan label from Claude usage prose."""
    match = re.search(
        r"using your\s+(?P<plan>.+?)\s+subscription",
        normalize_text(result_text),
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _safe_display_value(match.group("plan"))


def hashed_context_id(material: Sequence[str]) -> str:
    """Hash sanitized Claude auth material into a stable local context id."""
    hasher = hashlib.sha256()
    hasher.update(_installation_salt().encode("utf-8"))
    for item in material:
        hasher.update(b"\0")
        hasher.update(str(item).encode("utf-8", errors="replace"))
    return f"claude-usage-{hasher.hexdigest()[:24]}"


def _extract_plan_from_payload(payload: Mapping[str, Any]) -> str | None:
    """Extract a non-secret plan label from Claude auth status JSON."""
    for path in (
        ("plan",),
        ("subscription",),
        ("account", "plan"),
        ("account", "subscription"),
        ("user", "plan"),
    ):
        value: Any = payload
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str):
            sanitized = _safe_display_value(value)
            if sanitized:
                return sanitized
    return None


def _auth_mode_from_payload(payload: Mapping[str, Any]) -> str | None:
    if _payload_has_bool(payload, False, keys={"authenticated", "logged_in", "active"}):
        return "logged_out"
    blob = _payload_text_blob(payload)
    if _looks_logged_out(blob):
        return "logged_out"
    if _looks_api_mode(blob):
        return "api"
    if _payload_has_bool(payload, True, keys={"authenticated", "logged_in", "active"}):
        return "subscription"
    if _looks_subscription_mode(blob):
        return "subscription"
    return None


def _looks_logged_out(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "logged_out",
            "not logged in",
            "not_authenticated",
            "unauthenticated",
            "signed out",
            "login required",
        )
    )


def _looks_api_mode(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "api_key",
            "api key",
            "anthropic_api_key",
            "auth_mode=api",
            "authmode=api",
        )
    )


def _looks_subscription_mode(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "subscription",
            "claude.ai",
            "oauth",
            "max",
            "pro",
            "team",
            "logged_in",
            "authenticated",
        )
    )


def _safe_display_value(value: str) -> str | None:
    text = normalize_text(value)
    lowered = text.casefold()
    if (
        not text
        or "@" in text
        or any(marker in lowered for marker in _SECRET_FIELD_MARKERS)
    ):
        return None
    return text[:80]


def _auth_context_material(payload: Mapping[str, Any]) -> list[str]:
    material: list[str] = []

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value):
                key_text = str(key)
                if _is_secret_field(key_text):
                    continue
                walk(value[key], (*path, key_text))
            return
        if isinstance(value, str | int | float | bool):
            if path and path[-1].casefold() in {
                "email",
                "account",
                "account_id",
                "userid",
                "user_id",
                "organization",
                "organization_id",
                "org_id",
                "auth",
                "auth_type",
                "authtype",
                "auth_mode",
                "authmode",
                "plan",
                "subscription",
            }:
                material.append(f"{'.'.join(path)}={value}")

    walk(payload, ())
    return material


def _installation_salt() -> str:
    try:
        ensure = require_rust_binding("fleet_installation_identity_ensure")
        payload = ensure(str(sase_home()))
        record = payload.get("record") if isinstance(payload, Mapping) else None
        installation_id = (
            record.get("installation_id") if isinstance(record, Mapping) else None
        )
        if isinstance(installation_id, str) and installation_id:
            return installation_id
    except Exception:
        log.debug("provider usage installation salt was unavailable")
    return str(sase_home())


def _payload_text_blob(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value):
                key_text = str(key)
                if _is_secret_field(key_text):
                    continue
                walk(value[key], (*path, key_text))
            return
        if isinstance(value, str | int | float | bool):
            parts.append(f"{'.'.join(path)}={value}")

    walk(payload, ())
    return normalize_text(" ".join(parts)).casefold()


def _payload_has_bool(
    payload: Mapping[str, Any],
    expected: bool,
    *,
    keys: set[str],
) -> bool:
    found = False

    def walk(value: Any) -> None:
        nonlocal found
        if found:
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).casefold() in keys and item is expected:
                    found = True
                    return
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


def _is_secret_field(name: str) -> bool:
    lowered = name.casefold()
    return any(marker in lowered for marker in _SECRET_FIELD_MARKERS)
