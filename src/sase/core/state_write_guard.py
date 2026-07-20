"""Hard write boundary between pytest and the user's real SASE state."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

PYTEST_CONTEXT_ENV_VARS = ("PYTEST_CURRENT_TEST", "PYTEST_VERSION")

_warned_refusals: set[tuple[str, str]] = set()
_warned_refusals_lock = threading.Lock()


class _PytestStateIsolationError(RuntimeError):
    """Raised when pytest attempts to write into the real user state tree."""


def pytest_context_detected(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether this process carries an established pytest marker."""
    effective_environ = os.environ if environ is None else environ
    return any(name in effective_environ for name in PYTEST_CONTEXT_ENV_VARS)


def _account_home() -> Path:
    """Resolve the OS account home without trusting ``HOME`` or ``Path.home``."""
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def assert_test_state_write_isolated(
    target: str | os.PathLike[str],
    *,
    category: str,
    environ: Mapping[str, str] | None = None,
    resolved_account_home: Path | None = None,
) -> None:
    """Raise if a pytest process targets the account's real ``.sase`` tree."""
    refusal = _refusal_message(
        target,
        category=category,
        environ=environ,
        resolved_account_home=resolved_account_home,
    )
    if refusal is not None:
        raise _PytestStateIsolationError(refusal)


def best_effort_test_state_write_allowed(
    target: str | os.PathLike[str],
    *,
    category: str,
    environ: Mapping[str, str] | None = None,
    resolved_account_home: Path | None = None,
) -> bool:
    """Fail closed for daemon writes and warn once per target/category."""
    refusal = _refusal_message(
        target,
        category=category,
        environ=environ,
        resolved_account_home=resolved_account_home,
    )
    if refusal is None:
        return True

    key = (category, str(_resolve_path(target)))
    with _warned_refusals_lock:
        if key in _warned_refusals:
            return False
        _warned_refusals.add(key)
    log.warning(refusal)
    return False


def _refusal_message(
    target: str | os.PathLike[str],
    *,
    category: str,
    environ: Mapping[str, str] | None,
    resolved_account_home: Path | None,
) -> str | None:
    if not pytest_context_detected(environ):
        return None

    resolved_target = _resolve_path(target)
    try:
        real_state_root = _resolve_path(
            (resolved_account_home or _account_home()) / ".sase"
        )
    except (KeyError, OSError, RuntimeError) as exc:
        return (
            f"Refusing pytest {category} write to {resolved_target}: unable to "
            f"resolve the OS account home independently ({exc}). Set SASE_HOME "
            "to a per-test temporary directory."
        )

    if not _is_at_or_below(resolved_target, real_state_root):
        return None
    return (
        f"Refusing pytest {category} write to real user state target "
        f"{resolved_target}. Set SASE_HOME to a per-test temporary directory "
        f"outside {real_state_root}."
    )


def _resolve_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_at_or_below(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


__all__ = [
    "PYTEST_CONTEXT_ENV_VARS",
    "assert_test_state_write_isolated",
    "best_effort_test_state_write_allowed",
    "pytest_context_detected",
]
