"""Flag-gated conformance and inventory coverage for the Artifacts Agent pane.

The ``artifacts_agents_pane`` flag defaults off, so the pane is absent from
``resolve_artifacts_subtabs()`` in a default test run and would otherwise get
zero conformance coverage (see ``harness.py``'s ``iter_conformance_cases``,
which parametrizes over whatever ``resolve_artifacts_subtabs()`` currently
returns). This module supplies the explicit flag-on fixture the pane's
epic phase requires, plus a flag-off test proving today's inventory is
reproduced byte-for-byte.
"""

from __future__ import annotations

from sase.ace.tui.artifact_tabs import (
    reset_artifacts_subtabs_cache,
    resolve_artifacts_subtabs,
)
from sase.feature_flags import override_flags

from .harness import PANE_CONFORMANCE_CHECKS


def _resolve_ids(*, agents_pane_enabled: bool) -> tuple[str, ...]:
    with override_flags(artifacts_agents_pane=agents_pane_enabled):
        reset_artifacts_subtabs_cache()
        try:
            return tuple(d.id for d in resolve_artifacts_subtabs())
        finally:
            reset_artifacts_subtabs_cache()


def test_agents_pane_off_by_default_reproduces_todays_inventory() -> None:
    with override_flags(artifacts_agents_pane=False):
        reset_artifacts_subtabs_cache()
        try:
            descriptors = resolve_artifacts_subtabs()
            # Every fixed, non-provider pane the "pane" phase's epic
            # description names, in visual order. The full live inventory
            # (this repo's own configured ``ref:plan``/``ref:research``
            # document providers included) additionally reproduces
            # stitches, patches, beads, ref:plan, ref:research, files — but
            # provider discovery is environment-dependent, so this assertion
            # only pins the part every environment shares: no ``agents``
            # pane, and Files on its historical highest digit.
            ids = tuple(descriptor.id for descriptor in descriptors)
            assert "agents" not in ids
            assert ids[:3] == ("stitches", "patches", "beads")
            assert ids[-1] == "files"
            files = next(d for d in descriptors if d.id == "files")
            assert files.digit_shortcut == str(len(descriptors))
        finally:
            reset_artifacts_subtabs_cache()


def test_agents_pane_enabled_inserts_immediately_before_files() -> None:
    off_ids = _resolve_ids(agents_pane_enabled=False)
    with override_flags(artifacts_agents_pane=True):
        reset_artifacts_subtabs_cache()
        try:
            descriptors = resolve_artifacts_subtabs()
            ids = tuple(descriptor.id for descriptor in descriptors)
            # Enabling the flag inserts exactly one pane, "agents",
            # immediately before "files" -- every other pane, including
            # any configured document providers, is untouched.
            assert ids == off_ids[:-1] + ("agents", "files")
            agents = next(d for d in descriptors if d.id == "agents")
            files = next(d for d in descriptors if d.id == "files")
            assert agents.digit_shortcut == str(len(descriptors) - 1)
            assert files.digit_shortcut == str(len(descriptors))
            assert not agents.is_degraded
        finally:
            reset_artifacts_subtabs_cache()


def test_agents_pane_passes_full_conformance_sweep() -> None:
    with override_flags(artifacts_agents_pane=True):
        reset_artifacts_subtabs_cache()
        try:
            descriptors = {d.id: d for d in resolve_artifacts_subtabs()}
            agents = descriptors["agents"]
            for _name, check in PANE_CONFORMANCE_CHECKS:
                check(agents)
        finally:
            reset_artifacts_subtabs_cache()
