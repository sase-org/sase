"""Hard write boundary between pytest and the user's real SASE state."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger(__name__)

PYTEST_CONTEXT_ENV_VARS = ("PYTEST_CURRENT_TEST", "PYTEST_VERSION")
PYTEST_SANDBOX_DIR_ENV_VAR = "SASE_PYTEST_SANDBOX_DIR"
ALLOW_UNSANDBOXED_BEAD_WRITES_ENV_VAR = "SASE_ALLOW_UNSANDBOXED_BEAD_WRITES"

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


def pytest_path_is_sandboxed(
    target: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether *target* is safe to discover from a pytest process."""
    effective_environ = os.environ if environ is None else environ
    if not pytest_context_detected(effective_environ):
        return True

    sandbox = effective_environ.get(PYTEST_SANDBOX_DIR_ENV_VAR, "").strip()
    if not sandbox:
        return False
    return _is_at_or_below(_resolve_path(target), _resolve_path(sandbox))


def require_pytest_sandbox_root(
    *,
    purpose: str,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Return this pytest process's sandbox root, or ``None`` outside pytest.

    Callers redirect *purpose* into the returned root so a pytest process
    cannot write where a production run would. A pytest process that published
    no sandbox fails closed, because silently falling back to the production
    target is exactly the leak this guard exists to prevent.
    """
    effective_environ = os.environ if environ is None else environ
    if not pytest_context_detected(effective_environ):
        return None

    sandbox = effective_environ.get(PYTEST_SANDBOX_DIR_ENV_VAR, "").strip()
    if not sandbox:
        raise _PytestStateIsolationError(
            f"Refusing to resolve the {purpose} from a pytest process: "
            f"{PYTEST_SANDBOX_DIR_ENV_VAR} is unset or empty, so the write "
            "cannot be proven sandboxed. Publish a per-test temporary "
            f"directory through {PYTEST_SANDBOX_DIR_ENV_VAR}, the way "
            "tests/conftest.py does from tmp_path_factory."
        )
    return _resolve_path(sandbox)


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


def assert_bead_store_write_sandboxed(
    beads_dir: str | os.PathLike[str],
    *,
    operation: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Raise when a pytest process would mutate a bead store outside its sandbox."""
    effective_environ = os.environ if environ is None else environ
    if not pytest_context_detected(effective_environ):
        return
    if effective_environ.get(ALLOW_UNSANDBOXED_BEAD_WRITES_ENV_VAR) == "1":
        return

    resolved_beads_dir = _resolve_path(beads_dir)
    sandbox = effective_environ.get(PYTEST_SANDBOX_DIR_ENV_VAR, "").strip()
    if not sandbox:
        raise _PytestStateIsolationError(
            f"Refusing pytest bead-store {operation} write to "
            f"{resolved_beads_dir}: {PYTEST_SANDBOX_DIR_ENV_VAR} is unset or "
            "empty, so the write cannot be proven sandboxed. Create the bead "
            "store under a per-test temporary directory and publish that "
            f"directory through {PYTEST_SANDBOX_DIR_ENV_VAR}."
        )

    resolved_sandbox = _resolve_path(sandbox)
    if _is_at_or_below(resolved_beads_dir, resolved_sandbox):
        return
    raise _PytestStateIsolationError(
        f"Refusing pytest bead-store {operation} write to "
        f"{resolved_beads_dir}: target is outside pytest sandbox root "
        f"{resolved_sandbox}. Create the bead store at or below the sandbox root."
    )


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
    "ALLOW_UNSANDBOXED_BEAD_WRITES_ENV_VAR",
    "PYTEST_CONTEXT_ENV_VARS",
    "PYTEST_SANDBOX_DIR_ENV_VAR",
    "assert_bead_store_write_sandboxed",
    "assert_test_state_write_isolated",
    "best_effort_test_state_write_allowed",
    "pytest_context_detected",
    "pytest_path_is_sandboxed",
    "require_pytest_sandbox_root",
]
