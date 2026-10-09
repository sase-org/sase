"""Quiescence gate: act only once the code swap has settled.

Two checks, in order:

1. No update writer holds the code-swap writer lock (non-blocking probe;
   taking the real writer lock would itself disturb the lock-file mtime, so
   the probe only asks for a shared lock and treats failure as "writer
   active").
2. At least ``quiescence_seconds`` since the last code change, where "last
   change" is the maximum of the lock-file mtime, the newest dev-update
   journal row, and each managed root's HEAD commit time.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class QuiescenceResult:
    """Outcome of one quiescence check."""

    ok: bool
    reason: str
    quiet_seconds: float | None = None


def check_quiescence(*, quiescence_seconds: float) -> QuiescenceResult:
    """Return whether the tree is quiet enough to relaunch."""
    writer = _writer_holds_lock()
    if writer is None:
        return QuiescenceResult(ok=False, reason="could not probe the code-swap lock")
    if writer:
        return QuiescenceResult(
            ok=False, reason="a sase update currently holds the code-swap lock"
        )
    last_change = _last_code_change_epoch()
    if last_change is None:
        return QuiescenceResult(ok=True, reason="no code-change signal found")
    quiet = time.time() - last_change
    if quiet < quiescence_seconds:
        return QuiescenceResult(
            ok=False,
            reason=(
                "code changed "
                f"{quiet:.0f}s ago; waiting for {quiescence_seconds:.0f}s of quiet"
            ),
            quiet_seconds=quiet,
        )
    return QuiescenceResult(
        ok=True,
        reason=f"code quiet for {quiet:.0f}s",
        quiet_seconds=quiet,
    )


def _writer_holds_lock() -> bool | None:
    """Return whether a writer holds the exclusive code-swap lock.

    ``None`` means the probe itself failed; callers treat that as "cannot
    act", never as quiet.
    """
    try:
        from sase.dev_update.code_swap_lock import code_swap_lock_path
    except Exception:
        return None
    try:
        path = code_swap_lock_path()
    except Exception:
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        return False
    finally:
        os.close(fd)


def _last_code_change_epoch() -> float | None:
    """Return the newest code-change signal, or ``None`` when unknown."""
    candidates: list[float] = []
    lock_mtime = _lock_file_mtime()
    if lock_mtime is not None:
        candidates.append(lock_mtime)
    journal_time = _newest_journal_epoch()
    if journal_time is not None:
        candidates.append(journal_time)
    candidates.extend(_managed_head_epochs())
    if not candidates:
        return None
    return max(candidates)


def _lock_file_mtime() -> float | None:
    try:
        from sase.dev_update.code_swap_lock import code_swap_lock_path

        return code_swap_lock_path().stat().st_mtime
    except Exception:
        return None


def _newest_journal_epoch() -> float | None:
    """Return the newest dev-update journal timestamp, else the file mtime."""
    import json
    from datetime import datetime

    try:
        from sase.dev_update.journal import dev_update_journal_path

        path = dev_update_journal_path()
    except Exception:
        return None
    newest: float | None = None
    try:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                stamp = record.get("timestamp") if isinstance(record, dict) else None
                if not isinstance(stamp, str):
                    continue
                try:
                    parsed = datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                epoch = parsed.timestamp()
                if newest is None or epoch > newest:
                    newest = epoch
    except (FileNotFoundError, NotADirectoryError, OSError):
        return None
    if newest is not None:
        return newest
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _managed_head_epochs() -> list[float]:
    """Return one HEAD commit epoch per managed root (bounded git calls)."""
    try:
        from sase.agent.auto_restart.managed_roots import collect_managed_roots
    except Exception:
        return []
    try:
        roots = collect_managed_roots()
    except Exception:
        return []
    epochs: list[float] = []
    for root in roots:
        source = getattr(root, "source_root", None)
        if not source:
            continue
        try:
            proc = subprocess.run(
                ["git", "-C", str(source), "log", "-1", "--format=%ct", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        try:
            epochs.append(float(proc.stdout.strip()))
        except ValueError:
            continue
    return epochs


__all__ = ["QuiescenceResult", "check_quiescence"]
