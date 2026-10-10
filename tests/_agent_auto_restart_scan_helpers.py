"""Shared builders for auto-restart scan tests.

Split from ``tests.test_agent_auto_restart_scan``. Not a conftest so
files opt in by importing the helpers directly. Names are public so the
``test_agent_auto_restart_scan_*`` split modules can share them without
importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from typing import Any

from sase.agent.auto_restart.managed_roots import ManagedRoot

__all__ = [
    "scan_facts",
    "scan_managed_roots",
]


def scan_managed_roots(**overrides: Any) -> tuple[ManagedRoot, ...]:
    roots = {
        "sase": ManagedRoot(
            name="sase",
            role="host",
            source_root="/repo/sase",
            commit="9c5000f2db",
            version="0.17.1",
            install_type="editable",
        ),
        "sase-core-rs": ManagedRoot(
            name="sase-core-rs",
            role="core",
            source_root=None,
            commit=None,
            version="0.37.2",
            install_type="wheel",
        ),
    }
    roots.update(overrides)
    return tuple(roots.values())


def scan_facts(
    import_name: str = "sase.monitor.continuation_delivery",
    symbol: str = "auto_launch_prefix",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": "2026-10-09T12:00:00-04:00",
        "lifecycle_phase": "waiting",
        "exception_chain": [
            {
                "type": "ImportError",
                "qualname": "ImportError",
                "module": "builtins",
                "message": (f"cannot import name '{symbol}' from '{import_name}'"),
            }
        ],
        "import_error": {
            "name": import_name,
            "path": None,
            "missing_symbol": symbol,
        },
        "attribute_error": None,
        "frames": [
            {
                "file": "/repo/sase/src/sase/axe/run_agent_runner.py",
                "function": "_run_agent",
                "line": 232,
            }
        ],
        "last_frame_file": "/repo/sase/src/sase/axe/run_agent_runner.py",
        "skew_suspect": True,
        "error_text": None,
    }
