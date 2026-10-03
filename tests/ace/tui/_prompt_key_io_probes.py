"""Main-thread I/O probes for the prompt ``<space>`` / ``<ctrl+n/p>`` key paths.

Helper for epic sase-1ex (phase key-perf-harness). Later phases assert zeros
through :func:`prompt_key_io_probe`: it counts **main-thread-only** calls
during a block, so off-thread warm-up workers doing legitimate I/O never
trip it.

Counts:

- MRU file reads (:func:`_load_vcs_xprompt_mru`) and writes
  (:func:`_save_vcs_xprompt_mru`);
- ``list_project_records`` calls, patched at the facade *and* at the modules
  that import it by name;
- :class:`subprocess.Popen` constructions (covers ``subprocess.run``, which
  builds ``Popen`` through the ``subprocess`` module globals);
- :meth:`ArtifactWatcher.start` / :meth:`ArtifactWatcher.stop`;
- :meth:`threading.Thread.join`.

Note: the first :meth:`ArtifactWatcher.start` per process also counts a
``Popen`` from ``ctypes.util.find_library`` resolving libc; later phases
asserting zeros should start the watcher once outside the probed block or
expect that single construction.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest import mock


@dataclass
class PromptKeyIoCounts:
    """Per-signal main-thread call counts observed inside a probe block."""

    mru_reads: int = 0
    mru_writes: int = 0
    list_project_records: int = 0
    popen: int = 0
    watcher_start: int = 0
    watcher_stop: int = 0
    thread_join: int = 0

    def nonzero(self) -> dict[str, int]:
        """Return only the signals that fired, for failure messages."""
        return {
            name: value
            for name, value in {
                "mru_reads": self.mru_reads,
                "mru_writes": self.mru_writes,
                "list_project_records": self.list_project_records,
                "popen": self.popen,
                "watcher_start": self.watcher_start,
                "watcher_stop": self.watcher_stop,
                "thread_join": self.thread_join,
            }.items()
            if value
        }

    @property
    def total(self) -> int:
        """Return the total main-thread I/O-adjacent calls observed."""
        return (
            self.mru_reads
            + self.mru_writes
            + self.list_project_records
            + self.popen
            + self.watcher_start
            + self.watcher_stop
            + self.thread_join
        )

    def assert_quiet(self) -> None:
        """Raise unless the probed block performed zero main-thread I/O."""
        hot = self.nonzero()
        assert not hot, f"main-thread I/O during prompt key path: {hot}"


#: Modules holding ``list_project_records`` by name (module-level
#: ``from ... import ...`` bindings keep a direct reference, so patching the
#: facade alone would miss them). Function-level importers resolve through
#: the facade module at call time and are covered by the facade patch.
_LIST_RECORDS_BY_NAME_MODULES: tuple[str, ...] = (
    "sase.ace.patch.discovery",
    "sase.ace.tui.modals.project_discovery",
    "sase.agent.launch_projects",
    "sase.history.prompt_history_project_filter",
    "sase.project_display_names",
    "sase.repo_inventory",
    "sase.workspace_provider.inventory",
    "sase.workspace_provider.occupancy_conflicts",
)

_WATCHER_CLASS_PATH = "sase.ace.tui.util.fs_watcher"


def _import_or_none(dotted: str) -> Any | None:
    import importlib

    try:
        return importlib.import_module(dotted)
    except Exception:  # noqa: BLE001 - optional provider surface.
        return None


@contextlib.contextmanager
def prompt_key_io_probe() -> Iterator[PromptKeyIoCounts]:
    """Count main-thread I/O-adjacent calls made inside the ``with`` block.

    Every patch calls through to the real implementation; only the counting
    is added, and only calls made on the entering thread are counted.
    """
    counts = PromptKeyIoCounts()
    main_ident = threading.get_ident()

    def _counted(field: str, real: Any) -> Any:
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            if threading.get_ident() == main_ident:
                setattr(counts, field, getattr(counts, field) + 1)
            return real(*args, **kwargs)

        return _wrapper

    with contextlib.ExitStack() as stack:
        import sase.history.vcs_macro_mru as mru_module

        stack.enter_context(
            mock.patch.object(
                mru_module,
                "_load_vcs_macro_mru",
                _counted("mru_reads", mru_module._load_vcs_macro_mru),
            )
        )
        stack.enter_context(
            mock.patch.object(
                mru_module,
                "_save_vcs_macro_mru",
                _counted("mru_writes", mru_module._save_vcs_macro_mru),
            )
        )

        import sase.core.project_lifecycle_facade as facade

        stack.enter_context(
            mock.patch.object(
                facade,
                "list_project_records",
                _counted("list_project_records", facade.list_project_records),
            )
        )
        for module_name in _LIST_RECORDS_BY_NAME_MODULES:
            module = _import_or_none(module_name)
            real = getattr(module, "list_project_records", None)
            if module is None or not callable(real):
                continue
            stack.enter_context(
                mock.patch.object(
                    module,
                    "list_project_records",
                    _counted("list_project_records", real),
                )
            )

        stack.enter_context(
            mock.patch.object(subprocess, "Popen", _counted("popen", subprocess.Popen))
        )

        watcher_module = _import_or_none(_WATCHER_CLASS_PATH)
        watcher_cls = getattr(watcher_module, "ArtifactWatcher", None)
        if watcher_cls is not None:
            stack.enter_context(
                mock.patch.object(
                    watcher_cls,
                    "start",
                    _counted("watcher_start", watcher_cls.start),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    watcher_cls,
                    "stop",
                    _counted("watcher_stop", watcher_cls.stop),
                )
            )

        stack.enter_context(
            mock.patch.object(
                threading.Thread,
                "join",
                _counted("thread_join", threading.Thread.join),
            )
        )

        yield counts


__all__ = [
    "PromptKeyIoCounts",
    "prompt_key_io_probe",
]
