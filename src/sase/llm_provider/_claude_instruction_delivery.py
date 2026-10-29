"""Keep Claude's explicit instruction files alive across invocation cycles."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from ._claude_helper_channel import helper_channel_settings_json
from .instruction_delivery import (
    current_instruction_delivery,
    sase_owned_instruction_paths,
)


@contextmanager
def claude_instruction_files() -> Iterator[tuple[Path | None, Path | None, str]]:
    """Materialize each explicit slot once, retaining the guard on every path.

    A failed root keeps native discovery and the legacy directive. A failed
    helper uses the packaged helper template; the root never substitutes for it.
    """
    delivery = current_instruction_delivery()
    settings_json = helper_channel_settings_json()
    settings = json.loads(settings_json)
    settings["crossSessionInbound"] = "refuse"
    settings_json = json.dumps(settings)
    root_path = helper_path = None
    with ExitStack() as stack:
        if delivery is not None:
            if delivery.root.plan.status == "explicit":
                try:
                    settings = json.loads(settings_json)
                    settings["claudeMdExcludes"] = [
                        str(path) for path in sase_owned_instruction_paths()
                    ]
                    settings["autoMemoryEnabled"] = False
                    explicit_settings = json.dumps(settings)
                except Exception as exc:  # noqa: BLE001 - native fallback is atomic.
                    delivery.report_fallback("root", "delivery_failed", str(exc))
                else:
                    root_path = stack.enter_context(delivery.materialize("root"))
                    if root_path is not None:
                        settings_json = explicit_settings
            if delivery.subagent.plan.status == "explicit":
                helper_path = stack.enter_context(delivery.materialize("subagent"))
        yield root_path, helper_path, settings_json
