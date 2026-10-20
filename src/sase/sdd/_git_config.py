"""Shared git configuration for SDD bounded execution."""

import os

ENV_LOCAL_TIMEOUT = "SASE_SDD_GIT_LOCAL_TIMEOUT"
ENV_NETWORK_TIMEOUT = "SASE_SDD_GIT_NETWORK_TIMEOUT"
ENV_NETWORK_TRANSFER_CEILING = "SASE_SDD_GIT_NETWORK_TRANSFER_CEILING"
ENV_SLOW_MS = "SASE_SDD_GIT_SLOW_MS"

DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS = 120.0
DEFAULT_NETWORK_GIT_TRANSFER_CEILING_SECONDS = 900.0
DEFAULT_SLOW_GIT_MS = 1_000.0
DEFAULT_NETWORK_GIT_MAX_ATTEMPTS = 3
DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS = (0.25, 1.0)
_DISABLE_RERERE_ARGS = (
    "-c",
    "rerere.enabled=false",
    "-c",
    "rerere.autoupdate=false",
)


class SddGitCommandTimeout(RuntimeError):
    """Raised when a bounded SDD git command exceeds its timeout."""


def sdd_git_command(args: list[str]) -> list[str]:
    """Return a git argv for machine-managed SDD repositories."""
    # SDD stores contain generated append-only JSONL. Their conflicts are
    # resolved semantically by SASE, so ambient rerere must not replay or
    # auto-stage a cached textual resolution over that semantic merge.
    return ["git", *_DISABLE_RERERE_ARGS, *args]


def float_env(name: str, default: float) -> float:
    """Return a positive float env var, falling back to *default*."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def stream_text(value: str | bytes | None) -> str:
    """Return *value* as text, decoding bytes with replacement."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def decode_stream(value: bytes, *, text: bool) -> str | bytes:
    """Decode streaming bytes when *text* mode is requested."""
    if text:
        return value.decode("utf-8", errors="replace")
    return value


def format_seconds(value: float) -> str:
    """Format a timeout in seconds for timeout messages."""
    return f"{value:.3g}"
