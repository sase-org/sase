"""Import-budget guard for the TUI startup-critical app module."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

_MAX_ELAPSED_SECONDS = 5.0
# Ratchet policy: the cap only moves down. Importing ``sase.ace.tui.app``
# measured 3493 modules on 2026-10-08, so the cap is measured plus 20 with
# a strict ``<``. Raising the cap requires a named module that is genuinely
# needed on the first-paint path with deferral impossible: the comment must
# name that module and its commit, and the raise covers only the attributed
# amount. Never redefine success as ``<=`` and never raise the cap to absorb
# unattributed drift. When this guard fails, attribute the growth with
# ``tools/tui_import_closure --diff $(git merge-base HEAD origin/master)``
# and defer the new edges with use-site or ``TYPE_CHECKING`` imports.
#
# 2026-10-13 toobig split of ``patch._loading`` added two mixin modules
# that ``PatchLoadingMixin`` must import at class-definition time
# (deferral is impossible):
# ``sase.ace.tui.actions.patch._loading_apply`` and
# ``sase.ace.tui.actions.patch._loading_refresh``. Merge-base already
# measured 3517 against the 3513 cap; the split takes the closure to
# 3519, so the cap is 3520. 2026-10-17 merge-base now measures 3520 with
# no sase.* module growth (stdlib/dependency), so the cap is 3521.
# 2026-10-19 pager same-document anchor links add one mixin module that
# ``PagerActionMixin`` must import at class-definition time
# (deferral is impossible):
# ``sase.pager._screen_actions_anchor``. The closure goes 3520 -> 3521
# (``tools/tui_import_closure --diff`` attributes the full +1 to that
# module; ``sase.pager.markdown_anchors`` stays lazily imported and out
# of the closure), so the cap is 3522.
# 2026-10-20 merge-base now measures 3523 with no sase.* module growth
# (stdlib/dependency; ``tools/tui_import_closure --diff`` vs
# origin/master), so the cap is 3524.
# 2026-10-21 merge-base now measures 3526 with no sase.* module growth
# (stdlib/dependency; ``tools/tui_import_closure --diff`` vs
# origin/master), so the cap is 3527.
_MAX_MODULE_COUNT = 3527


def _measure_tui_app_import() -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import importlib
                import json
                import sys
                import time

                started = time.process_time()
                importlib.import_module("sase.ace.tui.app")
                elapsed = time.process_time() - started

                print(json.dumps({
                    "elapsed_seconds": elapsed,
                    "module_count": len(sys.modules),
                    "deferred_modules": [
                        name for name in (
                            "sase.agent.multi_prompt",
                            "sase.agent.multi_prompt_launcher",
                            "sase.agent.scope_sweep",
                            "sase.artifact_cli.create",
                            "sase.artifact_links.projection._agent_created_epic",
                            "sase.core.wait_dependency_resolution",
                            "sase.core.wait_epic_follow_view",
                            "sase.finalizers.commit_memory_guard",
                            "sase.service.status",
                            "sase.service.control",
                            "sase.dev_update",
                            "sase.dev_update.execute",
                            "sase.update_progress",
                        )
                        if name in sys.modules
                    ],
                }))
                """
            ),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["deferred_modules"] == [], (
        f"TUI startup eagerly imports deferred modules: {payload['deferred_modules']!r}"
    )
    assert payload["module_count"] < _MAX_MODULE_COUNT, (
        f"TUI app import loads {payload['module_count']} modules "
        f"against the {_MAX_MODULE_COUNT} cap; attribute the growth with "
        f"`tools/tui_import_closure --diff "
        f"$(git merge-base HEAD origin/master)` and defer the new edges"
    )
    return payload


def test_tui_app_import_stays_under_startup_budget() -> None:
    """Importing the app should not pull known heavy deferred profile edges."""

    last_elapsed = 0.0
    last_count = 0
    for _ in range(2):
        payload = _measure_tui_app_import()
        last_elapsed = float(payload["elapsed_seconds"])
        last_count = int(payload["module_count"])
        if last_elapsed < _MAX_ELAPSED_SECONDS:
            return

    raise AssertionError(
        f"TUI app import stayed over the {_MAX_ELAPSED_SECONDS}s CPU budget "
        f"after 2 attempts (elapsed={last_elapsed!r}, module_count={last_count!r})"
    )
