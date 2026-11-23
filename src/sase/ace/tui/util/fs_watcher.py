"""Event-driven artifact-directory watcher for sase's TUI.

Split facade: the implementation lives in :mod:`_fs_watcher_common`,
:mod:`_fs_watcher_core`, :mod:`_fs_watcher_watches`, and
:mod:`_fs_watcher_runner`. This module re-exports the public names so the
original import path keeps working.
"""

from __future__ import annotations

from ._fs_watcher_core import (
    DEFAULT_COALESCE_S as DEFAULT_COALESCE_S,
    DEFAULT_DISPATCH_DEADLINE_S as DEFAULT_DISPATCH_DEADLINE_S,
    DEFAULT_EVENT_MASK as DEFAULT_EVENT_MASK,
    PIPE_IDLE_FALLBACK_S as PIPE_IDLE_FALLBACK_S,
)
from ._fs_watcher_runner import ArtifactWatcher as ArtifactWatcher
from ._fs_watcher_watches import MAX_INOTIFY_WATCHES as MAX_INOTIFY_WATCHES
