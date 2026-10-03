"""Immutable launchable-MRU snapshot for prompt project cycling.

Epic sase-1ex, phase mru-snapshot. The prompt ``<ctrl+n/p>`` keys used to call
:func:`sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru` on every
press, re-validating the whole MRU (project records, ``git config``
subprocesses, stats) on the UI thread. This module is the Textual-free pure
model for the replacement: an immutable snapshot owned by ``AceApp`` that a
single-flight worker builds off the pump while the keys only peek it.

A build calls the existing
:func:`~sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru_pairs`
with ``prune=False``, so validation policy stays single-sourced and key
paths never write the MRU file. ``"ready"`` with no pairs means "the MRU is
empty" and is distinct from ``"cold"`` ("not built yet").
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Literal

LaunchableMruState = Literal["cold", "ready", "error"]


@dataclass(frozen=True, slots=True)
class LaunchableMruSnapshot:
    """One immutable view of the launchable VCS-xprompt MRU.

    ``pairs`` holds ``(canonical_prefix, display_prefix)`` in MRU order;
    cycle keys pin the display halves as their ring. ``token`` is the
    :func:`~sase.current_project.peek_current_project_change_token` value
    observed when the build started. ``inputs_signature`` is the cheap
    worker-side fingerprint used to skip validation when nothing changed.
    ``refresh_pending`` is set synchronously at submit/set-current time
    (pure memory) and cleared when the follow-up build publishes.
    """

    state: LaunchableMruState
    pairs: tuple[tuple[str, str], ...] = ()
    generation: int = 0
    token: tuple[object, ...] | None = None
    inputs_signature: tuple[object, ...] = ()
    refresh_pending: bool = False

    @property
    def display_ring(self) -> tuple[str, ...]:
        """Return the display halves cycle keys pin as their ring."""
        return tuple(display for _, display in self.pairs)

    def with_refresh_pending(self) -> LaunchableMruSnapshot:
        """Return a copy with the ``refresh_pending`` flag set."""
        if self.refresh_pending:
            return self
        return replace(self, refresh_pending=True)


#: The snapshot every app starts with: not built yet, distinct from an
#: empty MRU (``ready`` with no pairs).
COLD_LAUNCHABLE_MRU_SNAPSHOT = LaunchableMruSnapshot(state="cold")


def _compute_launchable_mru_inputs_signature() -> tuple[object, ...]:
    """Return a cheap fingerprint of the snapshot's file/config inputs.

    Best-effort and allocation-light: MRU ``(mtime_ns, size)``, the current
    config token, and the projects-dir stat. Project-spec and Patch drift
    invisible to this fingerprint is covered by forced periodic rebuilds,
    never by widening this probe into a resolving read.
    """
    parts: list[object] = []
    try:
        from sase.history.vcs_macro_mru import vcs_macro_mru_path

        parts.append(_stat_parts(vcs_macro_mru_path()))
    except Exception:  # noqa: BLE001 - a broken stat degrades to "changed".
        parts.append(("mru-stat-error",))
    try:
        from sase.config.core import current_config_token

        parts.append(current_config_token())
    except Exception:  # noqa: BLE001 - degrade rather than fail the build.
        parts.append(("config-token-error",))
    try:
        from sase.core.paths import sase_projects_dir

        parts.append(_stat_parts(sase_projects_dir()))
    except Exception:  # noqa: BLE001 - degrade rather than fail the build.
        parts.append(("projects-stat-error",))
    return tuple(parts)


def _stat_parts(path: object) -> tuple[object, ...]:
    """Return ``(str(path), mtime_ns, size)`` or a missing marker."""
    try:
        st = os.stat(path)  # type: ignore[arg-type]
    except FileNotFoundError:
        return (str(path), "missing")
    except OSError:
        return (str(path), "stat-error")
    return (str(path), st.st_mtime_ns, st.st_size)


def build_launchable_mru_data(
    *,
    force: bool = False,
    last_signature: tuple[object, ...] | None = None,
) -> tuple[tuple[object, ...], list[tuple[str, str]], tuple[object, ...]] | None:
    """Build fresh snapshot data off the UI thread.

    Returns ``(inputs_signature, pairs, token)``, or ``None`` when the
    worker fast path applies: the inputs signature matches
    *last_signature* and *force* is unset, so validation is skipped and
    nothing should publish. Raises on loader failure so the caller can
    publish an ``"error"`` snapshot instead of stale data.
    """
    from sase.current_project import peek_current_project_change_token
    from sase.history.vcs_macro_mru import (
        load_launchable_vcs_macro_mru_pairs,
    )
    from sase.macro.project_identity import warm_macro_project_identity

    # Warm the macro project identity registry first, before the fast-path
    # signature check, so the skip still shortens the cold window. This
    # runs off-thread (the caller invokes this via ``asyncio.to_thread``).
    warm_macro_project_identity()
    token = peek_current_project_change_token()
    signature = _compute_launchable_mru_inputs_signature()
    if not force and last_signature is not None and signature == last_signature:
        return None
    pairs = load_launchable_vcs_macro_mru_pairs(prune=False)
    return (signature, pairs, token)


__all__ = [
    "COLD_LAUNCHABLE_MRU_SNAPSHOT",
    "LaunchableMruSnapshot",
    "LaunchableMruState",
    "build_launchable_mru_data",
]
