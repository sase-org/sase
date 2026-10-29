"""Import-budget guard for the TUI startup-critical app module."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

import pytest

_MAX_ELAPSED_SECONDS = 5.0
# Ratchet policy: the cap only moves down. The guard counts first-party
# modules (``sase`` and ``sase.*``) after ``import sase.ace.tui.app`` in a
# fresh interpreter. Measured 2839 on 2026-10-29, so the cap is measured
# plus 5 with a strict ``<``. Raising the cap requires a named first-party
# module that is genuinely needed on the first-paint path with deferral
# impossible: the comment must name that module and its commit, and the
# raise covers only the attributed amount. Never redefine success as
# ``<=`` and never raise the cap to absorb unattributed drift. Third-party
# and stdlib growth no longer fail this cap. When this guard fails,
# attribute the growth with
# ``tools/tui_import_closure --diff $(git merge-base HEAD origin/master)``
# and defer the new edges with use-site or ``TYPE_CHECKING`` imports.
#
# The previous total-module cap (sys.modules length, last 3550) re-broke
# about weekly on dependency/stdlib drift with no sase.* growth (sase-1ic).
_MAX_SASE_MODULE_COUNT = 2844
# Loose total-module bound: measured 3549 on 2026-10-29 plus 10%, strict
# ``<``. Only a large dependency regression trips this.
_MAX_TOTAL_MODULE_COUNT = 3904


def _sase_module_count(module_names: list[str]) -> int:
    return sum(1 for name in module_names if name == "sase" or name.startswith("sase."))


def _assert_sase_module_budget(
    sase_module_count: int, *, cap: int = _MAX_SASE_MODULE_COUNT
) -> None:
    assert sase_module_count < cap, (
        f"TUI app import loads {sase_module_count} sase.* modules "
        f"against the {cap} cap; attribute the growth with "
        f"`tools/tui_import_closure --diff "
        f"$(git merge-base HEAD origin/master)` and defer the new edges"
    )


def _assert_total_module_budget(
    module_count: int, *, cap: int = _MAX_TOTAL_MODULE_COUNT
) -> None:
    assert module_count < cap, (
        f"TUI app import loads {module_count} total modules against the loose {cap} cap"
    )


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
                    "sase_modules": sorted(
                        name
                        for name in sys.modules
                        if name == "sase" or name.startswith("sase.")
                    ),
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
    sase_module_count = len(payload["sase_modules"])
    _assert_sase_module_budget(sase_module_count)
    _assert_total_module_budget(int(payload["module_count"]))
    payload["sase_module_count"] = sase_module_count
    return payload


def test_first_party_count_includes_sase_package_and_submodules() -> None:
    names = [
        "sase",
        "sase.ace.tui.app",
        "sase_core",
        "sase_core_rs",
        "textual",
        "sys",
        "json",
    ]
    assert _sase_module_count(names) == 2


def test_first_party_cap_fails_when_a_new_sase_module_joins_the_closure() -> None:
    """A synthetic eager ``sase.*`` import must trip the first-party cap."""
    baseline = ["sase", "sase.ace.tui.app"]
    with_new = [*baseline, "sase._import_budget_synthetic"]
    cap = _sase_module_count(baseline) + 1
    _assert_sase_module_budget(_sase_module_count(baseline), cap=cap)
    with pytest.raises(AssertionError, match=r"3 sase\.\* modules against the 3 cap"):
        _assert_sase_module_budget(_sase_module_count(with_new), cap=cap)


def test_first_party_cap_ignores_third_party_growth() -> None:
    """Stdlib/dependency module growth must not trip the first-party cap."""
    baseline = ["sase", "sase.ace.tui.app", "textual", "json"]
    with_third_party = [*baseline, "new_dependency.foo", "email._parseaddr"]
    assert _sase_module_count(baseline) == _sase_module_count(with_third_party) == 2
    _assert_sase_module_budget(_sase_module_count(with_third_party), cap=3)


def test_first_party_cap_uses_strict_less_than() -> None:
    _assert_sase_module_budget(_MAX_SASE_MODULE_COUNT - 1)
    with pytest.raises(AssertionError, match="against the"):
        _assert_sase_module_budget(_MAX_SASE_MODULE_COUNT)


def test_tui_app_import_stays_under_startup_budget() -> None:
    """Importing the app should not pull known heavy deferred profile edges."""

    last_elapsed = 0.0
    last_sase_count = 0
    last_count = 0
    for _ in range(2):
        payload = _measure_tui_app_import()
        last_elapsed = float(payload["elapsed_seconds"])
        last_sase_count = int(payload["sase_module_count"])
        last_count = int(payload["module_count"])
        if last_elapsed < _MAX_ELAPSED_SECONDS:
            return

    raise AssertionError(
        f"TUI app import stayed over the {_MAX_ELAPSED_SECONDS}s CPU budget "
        f"after 2 attempts (elapsed={last_elapsed!r}, "
        f"sase_module_count={last_sase_count!r}, module_count={last_count!r})"
    )
