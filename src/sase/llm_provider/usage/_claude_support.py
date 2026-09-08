"""Support functions for Claude Code subscription usage collection."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo as TzInfo
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packaging.version import InvalidVersion, Version

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.core.time import get_timezone
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    validate_observation,
    validated_status_observation,
)

log = logging.getLogger(__name__)

_COMMAND_TIMEOUT_FLOOR_SECONDS = 0.05
_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,3})")
_USAGE_ROW_RE = re.compile(
    r"^Current\s+(?P<label>[^:]+):\s*"
    r"(?P<percent>\d+(?:\.\d+)?)%\s+used"
    r"(?:\s+.*?\bresets?\s+(?P<reset>.+))?$",
    re.IGNORECASE,
)
_ZONE_NAME_RE = r"[A-Za-z_]+(?:/[A-Za-z_]+)+|UTC"
_ISO_RESET_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\s*(Z|UTC|[+-]\d{2}:\d{2}))?$",
    re.IGNORECASE,
)
_MONTH_RESET_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(\d{4}),?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\((" + _ZONE_NAME_RE + r")\))?$",
    re.IGNORECASE,
)
_TIME_RESET_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\((" + _ZONE_NAME_RE + r")\))?$",
    re.IGNORECASE,
)
_MONTH_ABBR_TO_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MODEL_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-fable-5", ("claude fable 5", "fable 5", "fable")),
    ("claude-haiku-4-5", ("claude haiku 4 5", "haiku 4 5", "haiku")),
    ("sonnet", ("sonnet",)),
    ("opus", ("opus",)),
)
_SECRET_FIELD_MARKERS = ("token", "secret", "password", "credential", "key")


@dataclass(frozen=True)
class ClaudeCommandResult:
    """One bounded Claude CLI command result."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ClaudeAuthInfo:
    """Sanitized Claude auth status classification."""

    mode: str | None
    plan: str | None = None
    context_material: tuple[str, ...] = ()


ClaudeCommandRunner = Callable[[Sequence[str], str | None, float], ClaudeCommandResult]


def parse_usage_windows(
    result_text: str,
    *,
    observed_at: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse Claude usage prose into provider-usage windows."""
    windows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    had_parse_error = False
    for raw_line in result_text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue
        match = _USAGE_ROW_RE.match(line)
        if match is None:
            if line.startswith("Current ") or "% used" in line:
                had_parse_error = True
            continue
        label = match.group("label").strip()
        percent_text = match.group("percent")
        reset_text = match.group("reset")
        try:
            used_percent = float(percent_text)
        except ValueError:
            had_parse_error = True
            continue
        if used_percent < 0.0:
            had_parse_error = True
            continue
        resets_at = None
        if reset_text:
            resets_at = _parse_claude_reset_timestamp(
                reset_text,
                observed_at=observed_at,
            )
            if resets_at is None:
                had_parse_error = True
        key, display_label, applicability = _usage_window_identity(label)
        if key in seen_keys:
            had_parse_error = True
            continue
        seen_keys.add(key)
        windows.append(
            {
                "key": key,
                "label": display_label,
                "used_percent": used_percent,
                "resets_at": resets_at,
                "duration_seconds": None,
                "period_start": None,
                "applicability": applicability,
                "observed_at": observed_at,
                "source": "probe",
                "vendor_state": "allowed",
            }
        )
    return windows, had_parse_error


def event_window(
    raw_key: str,
    used_percent: float,
    resets_at: float | None,
    observed_at: float,
) -> dict[str, Any]:
    """Normalize a Claude stream window name into a provider-usage window."""
    normalized = _slugify(raw_key)
    if normalized in {"five-hour", "five-hour-limit", "five-hour-window", "5-hour"}:
        key = "session"
        label = "Claude five-hour session"
        applicability = {"kind": "product", "product": "claude"}
    elif normalized in {
        "seven-day",
        "seven-day-limit",
        "seven-day-window",
        "7-day",
    }:
        key = "weekly"
        label = "Claude weekly all models"
        applicability = {"kind": "product", "product": "claude"}
    else:
        key = f"window:{normalized}"
        label = f"Claude {raw_key}"
        applicability = {
            "kind": "unknown",
            "vendor_label": raw_key,
            "vendor_id": normalized,
        }
    return {
        "key": key,
        "label": label,
        "used_percent": used_percent,
        "resets_at": resets_at,
        "duration_seconds": None,
        "period_start": None,
        "applicability": applicability,
        "observed_at": observed_at,
        "source": "stream_event",
        "vendor_state": "unknown",
    }


def print_help_supports_zero_cost_probe(help_text: str) -> bool:
    """Return whether Claude print mode supports the guarded usage probe."""
    required = (
        "--output-format",
        "json",
        "--max-budget-usd",
        "--safe-mode",
        "--no-session-persistence",
    )
    return all(item in help_text for item in required)


def usage_probe_argv(executable: str) -> tuple[str, ...]:
    """Build the guarded zero-budget Claude ``/usage`` argv."""
    return (
        executable,
        "-p",
        "--output-format",
        "json",
        "--safe-mode",
        "--no-session-persistence",
        "--permission-prompts",
        "none",
        "--max-budget-usd",
        "0",
        "/usage",
    )


def run_claude_command(
    argv: Sequence[str],
    cwd: str | None,
    deadline_at: float,
) -> ClaudeCommandResult:
    """Run one bounded Claude CLI command without shell expansion."""
    timeout = deadline_at - time.time()
    if timeout <= 0.0:
        raise subprocess.TimeoutExpired(list(argv), 0.0)
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=max(timeout, _COMMAND_TIMEOUT_FLOOR_SECONDS),
    )
    return ClaudeCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def safe_run(
    run: ClaudeCommandRunner,
    argv: Sequence[str],
    *,
    cwd: str | None,
    deadline_at: float,
) -> ClaudeCommandResult | str:
    """Convert expected Claude command failures into local sentinel values."""
    try:
        return run(argv, cwd, deadline_at)
    except FileNotFoundError:
        return "not_installed"
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "failed"


def resolve_claude_executable(executable: str | None) -> str | None:
    """Resolve an explicit or PATH-provided Claude executable."""
    if executable:
        return executable
    return shutil.which("claude")


def extract_version(text: str) -> Version | None:
    """Extract a semantic-looking Claude CLI version from command output."""
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


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
    normalized = _normalize_text(text).casefold()
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
        _normalize_text(result_text),
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _safe_display_value(match.group("plan"))


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


def hashed_context_id(material: Sequence[str]) -> str:
    """Hash sanitized Claude auth material into a stable local context id."""
    hasher = hashlib.sha256()
    hasher.update(_installation_salt().encode("utf-8"))
    for item in material:
        hasher.update(b"\0")
        hasher.update(str(item).encode("utf-8", errors="replace"))
    return f"claude-usage-{hasher.hexdigest()[:24]}"


def has_zero_cost_markers(payload: Mapping[str, Any]) -> bool:
    """Return whether Claude result JSON proves zero turns and zero cost."""
    turns = payload.get("num_turns")
    cost = payload.get("total_cost_usd")
    return _numeric_zero(turns) and _numeric_zero(cost)


def optional_epoch_seconds(value: object) -> float | Literal["malformed"] | None:
    """Parse an optional stream reset timestamp already represented as epoch."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not is_finite_number(value)
    ):
        return "malformed"
    return float(value)


def vendor_state_from_rate_limit_info(info: Mapping[str, Any]) -> str:
    """Map Claude rate-limit status fields into provider-usage vendor states."""
    status = str(info.get("status") or "").casefold()
    overage = str(info.get("overageStatus") or "").casefold()
    combined = f"{status} {overage}"
    if any(marker in status for marker in ("reject", "blocked", "denied", "limited")):
        return "rejected"
    if any(marker in status for marker in ("warn", "approach")):
        return "warning"
    if "allowed" in status:
        return "allowed"
    if any(marker in combined for marker in ("reject", "blocked", "denied", "limited")):
        return "rejected"
    if any(marker in combined for marker in ("warn", "approach")):
        return "warning"
    return "unknown"


def is_finite_number(value: object) -> bool:
    """Return whether a JSON value is a finite numeric value."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    number = float(value)
    return number == number and number not in {float("inf"), float("-inf")}


def status_observation(
    context: UsageProbeContext,
    *,
    now: float,
    outcome: str,
    reason_code: str | None = None,
    diagnostic: str | None = None,
    account_mode: str | None = None,
    plan: str | None = None,
) -> dict[str, Any]:
    """Build and validate a status-only provider-usage observation."""
    observation = validated_status_observation(
        context,
        now=now,
        outcome=outcome,  # type: ignore[arg-type]
        reason_code=reason_code,  # type: ignore[arg-type]
        diagnostic=diagnostic,
    )
    if account_mode is None and plan is None:
        return observation
    enriched = dict(observation)
    enriched["account_mode"] = account_mode
    enriched["plan"] = plan
    try:
        return validate_observation(enriched, now=max(now, context.request_started_at))
    except (TypeError, ValueError, AttributeError):
        return observation


def _parse_claude_reset_timestamp(text: str, *, observed_at: float) -> float | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    match = _ISO_RESET_RE.match(normalized)
    if match:
        return _resolve_iso_datetime(match.groups())
    match = _MONTH_RESET_RE.match(normalized)
    if match:
        return _resolve_month_datetime(match.groups(), observed_at=observed_at)
    match = _TIME_RESET_RE.match(normalized)
    if match:
        return _resolve_time_only(match.groups(), observed_at=observed_at)
    return None


def _usage_window_identity(label: str) -> tuple[str, str, dict[str, Any]]:
    normalized = _label_words(label)
    if "session" in normalized or ("five" in normalized and "hour" in normalized):
        return "session", "Claude session", {"kind": "product", "product": "claude"}
    model_id = _model_id_from_label(normalized)
    if model_id is not None and ("week" in normalized or "weekly" in normalized):
        return (
            f"weekly:{_slugify(model_id)}",
            f"Claude weekly {label}",
            {"kind": "models", "model_ids": [model_id]},
        )
    if (
        normalized in {"week", "weekly", "seven day", "7 day"}
        or ("week" in normalized and "all" in normalized and "model" in normalized)
        or ("weekly" in normalized and "all" in normalized and "model" in normalized)
    ):
        return (
            "weekly",
            "Claude weekly all models",
            {"kind": "product", "product": "claude"},
        )
    slug = _slugify(label)
    return (
        f"window:{slug}",
        f"Claude {label}",
        {"kind": "unknown", "vendor_label": label, "vendor_id": slug},
    )


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
    text = _normalize_text(value)
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
    return _normalize_text(" ".join(parts)).casefold()


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


def _numeric_zero(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return float(value) == 0.0
    if isinstance(value, str):
        try:
            return float(value) == 0.0
        except ValueError:
            return False
    return False


def _resolve_iso_datetime(groups: tuple[str | None, ...]) -> float | None:
    year_str, month_str, day_str, hour_str, minute_str, second_str, zone_str = groups
    try:
        year = int(year_str or "")
        month = int(month_str or "")
        day = int(day_str or "")
        hour = int(hour_str or "")
        minute = int(minute_str or "")
        second = int(second_str) if second_str else 0
    except ValueError:
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tz).timestamp()
    except ValueError:
        return None


def _resolve_month_datetime(
    groups: tuple[str | None, ...],
    *,
    observed_at: float,
) -> float | None:
    month_str, day_str, year_str, hour_str, minute_str, meridiem, zone_str = groups
    month = _MONTH_ABBR_TO_NUM.get(str(month_str or "")[:3].casefold())
    if month is None:
        return None
    try:
        day = int(day_str or "")
        hour = _hour_24(hour_str, meridiem)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if hour is None or not (0 <= minute <= 59):
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    if year_str is not None:
        try:
            candidate = datetime(
                int(year_str),
                month,
                day,
                hour,
                minute,
                tzinfo=tz,
            )
            return candidate.timestamp()
        except ValueError:
            return None
    now_dt = datetime.fromtimestamp(observed_at, tz=tz)
    candidates: list[datetime] = []
    for year in (now_dt.year - 1, now_dt.year, now_dt.year + 1):
        try:
            candidates.append(datetime(year, month, day, hour, minute, tzinfo=tz))
        except ValueError:
            continue
    if not candidates:
        return None
    closest = min(candidates, key=lambda candidate: abs(candidate - now_dt))
    return closest.timestamp()


def _resolve_time_only(
    groups: tuple[str | None, ...],
    *,
    observed_at: float,
) -> float | None:
    hour_str, minute_str, meridiem, zone_str = groups
    try:
        hour = _hour_24(hour_str, meridiem)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if hour is None or not (0 <= minute <= 59):
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    now_dt = datetime.fromtimestamp(observed_at, tz=tz)
    candidate = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() < observed_at - 300.0:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _hour_24(hour_str: str | None, meridiem: str | None) -> int | None:
    try:
        hour = int(hour_str or "")
    except ValueError:
        return None
    if not (1 <= hour <= 12):
        return None
    hour %= 12
    if str(meridiem or "").casefold() == "pm":
        hour += 12
    return hour


def _resolve_zone(zone_str: str | None) -> TzInfo | None:
    if zone_str is None:
        return get_timezone()
    if zone_str.upper() in {"Z", "UTC"}:
        return ZoneInfo("UTC")
    if zone_str.startswith(("+", "-")):
        try:
            hours, minutes = zone_str[1:].split(":", 1)
            offset = timedelta(hours=int(hours), minutes=int(minutes))
        except ValueError:
            return None
        if zone_str.startswith("-"):
            offset = -offset
        return timezone(offset)
    try:
        return ZoneInfo(zone_str)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def _model_id_from_label(normalized_label: str) -> str | None:
    padded = f" {normalized_label} "
    for model_id, aliases in _MODEL_LABELS:
        for alias in aliases:
            if f" {alias} " in padded:
                return model_id
    return None


def _label_words(text: str) -> str:
    slug = _slugify(text)
    return slug.replace("-", " ")


def _slugify(text: str) -> str:
    normalized = _normalize_text(text).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "unknown"


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", normalized).strip()
