"""Shared publication-test helpers for post-paint Artifacts suites."""

from __future__ import annotations

import threading
from typing import Any

from sase.ace.testing import AcePage
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT

__all__ = [
    "catalog_for",
    "gated_blocking_factory",
    "plan_records",
    "publication_path",
    "switcher_child",
    "wait_for_status",
]


def plan_records() -> tuple[Any, ...]:
    """Return one healthy plan provider record through the real spec path."""

    from pathlib import Path

    from sase.ace.tui._artifact_tab_model import ProjectProviderRecord
    from sase.artifact_providers import builtin_plan_ref_provider_spec
    from sase.sidecar_ref_config import SidecarRefPolicy

    return (
        ProjectProviderRecord(
            project="sase",
            display_name="sase",
            workspace_dir=None,
            role="plans",
            root=Path("."),
            policy=SidecarRefPolicy(
                role="plans",
                ref_kind="plan",
                is_document=True,
                spec=builtin_plan_ref_provider_spec(),
            ),
        ),
    )


def gated_blocking_factory(
    entered: threading.Event,
    release: threading.Event,
    *,
    records: tuple[Any, ...] | None = None,
    issues: tuple[Any, ...] = (),
    token: tuple[object, ...] | None = ("test-token",),
    status: str = "completed",
) -> Any:
    """Build a gated fake for the publication worker's blocking body."""

    def _fake() -> tuple[Any, int, tuple[Any, ...], str]:
        from sase.ace.tui._artifact_tab_descriptors import (
            build_artifacts_strip,
            provider_descriptors,
        )
        from sase.ace.tui.artifact_tabs import artifacts_tab_cache_epoch

        entered.set()
        assert release.wait(timeout=LOAD_TOLERANT_TIMEOUT), "discovery gate stuck"
        providers = provider_descriptors(tuple(records or ()), issues)
        epoch = int(artifacts_tab_cache_epoch())
        return token, epoch, build_artifacts_strip(providers), status

    return _fake


def publication_path() -> str:
    return "sase.ace.tui.actions._artifacts_publication._fresh_artifacts_discovery_blocking"


async def wait_for_status(page: AcePage, status: str) -> None:
    def _is(status_name: str) -> bool:
        snapshot = page.app.artifacts_descriptor_snapshot
        return snapshot.status.value == status_name

    await page.wait_for(
        lambda _state: _is(status),
        timeout=LOAD_TOLERANT_TIMEOUT,
        timeout_message=lambda: f"artifacts discovery never reached {status}",
    )


def catalog_for(app: Any) -> list[Any]:
    from sase.ace.tui.commands import build_command_catalog

    return list(
        build_command_catalog(
            app._keymap_registry,
            snapshot=getattr(app, "artifacts_descriptor_snapshot", None),
        )
    )


def switcher_child(view: Any, widget_id: str) -> Any | None:
    switcher = view.query_one("#artifacts-content-switcher")
    return next(
        (
            child
            for child in switcher.children
            if getattr(child, "id", None) == widget_id
        ),
        None,
    )
