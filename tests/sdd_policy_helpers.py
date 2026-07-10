"""Test helpers for provider-owned SDD storage policy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest


def set_sdd_policy(monkeypatch: pytest.MonkeyPatch, storage: str) -> None:
    """Patch provider detection so *storage* is the authoritative policy."""

    vcs_name = {
        "in_tree": "bare_git",
        "separate_repo": "github",
    }.get(storage)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: vcs_name)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda _name: storage if storage != "local" else None,
    )


@contextmanager
def patched_sdd_policy(storage: str) -> Iterator[None]:
    """Context-manager form of :func:`set_sdd_policy`."""

    vcs_name = {
        "in_tree": "bare_git",
        "separate_repo": "github",
    }.get(storage)
    policy = storage if storage != "local" else None
    with (
        patch("sase.vcs_provider.detect_vcs", return_value=vcs_name),
        patch(
            "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
            return_value=policy,
        ),
    ):
        yield
