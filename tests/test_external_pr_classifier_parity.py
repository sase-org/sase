"""Parity coverage for the external PR import classifier."""

from __future__ import annotations

from dataclasses import asdict

from sase.core.external_pr_conversion import _plan_external_pr_import_python
from sase.core.external_pr_facade import plan_external_pr_import
from sase.core.external_pr_wire import (
    EXTERNAL_PR_WIRE_SCHEMA_VERSION,
    ExternalPrImportRequestWire,
    LocalPatchWire,
    RemotePullRequestWire,
)


def _remote(
    *,
    body: str = "",
    title: str = "Feature Title",
    state: str = "open",
    is_draft: bool = False,
    merged_at: str = "",
) -> RemotePullRequestWire:
    return RemotePullRequestWire(
        number=17,
        url="https://github.com/sase-org/sase/pull/17",
        provider_id="PR_kw17",
        title=title,
        body=body,
        state=state,
        is_draft=is_draft,
        author="alice",
        head_ref="feature/branch",
        base_ref="main",
        created_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
        closed_at="",
        merged_at=merged_at,
    )


def _local(
    name: str,
    *,
    pr_url: str = "",
    pr_origin: str = "unknown",
    status: str = "Mailed",
) -> LocalPatchWire:
    return LocalPatchWire(
        name=name,
        pr_url=pr_url,
        pr_origin=pr_origin,
        status=status,
        archived=False,
        reserved=status == "Reserved",
    )


def _request(
    remote: RemotePullRequestWire,
    *local_patches: LocalPatchWire,
) -> ExternalPrImportRequestWire:
    return ExternalPrImportRequestWire(
        schema_version=EXTERNAL_PR_WIRE_SCHEMA_VERSION,
        remote=remote,
        local_patches=local_patches,
    )


def _owned_local(
    *,
    pr_origin: str,
    status: str = "Mailed",
    archived: bool = False,
) -> LocalPatchWire:
    return LocalPatchWire(
        name="pr_feature_1",
        pr_url="https://github.com/sase-org/sase/pull/17",
        pr_origin=pr_origin,
        status=status,
        archived=archived,
        reserved=status == "Reserved",
    )


def test_external_pr_classifier_python_rust_parity() -> None:
    cases = [
        _request(
            _remote(),
            _local(
                "sase_feature_1",
                pr_url="HTTP://WWW.GITHUB.COM/SASE-ORG/SASE.git/pulls/17/",
                pr_origin="unknown",
            ),
        ),
        _request(
            _remote(body="Body\n\nSASE_PATCH=sase_feature_1"),
            _local("sase_feature_1", status="Reserved"),
        ),
        _request(_remote(body="Body\n\nPATCH=sase_feature_2")),
        _request(_remote(body="Body")),
        _request(_remote(body="Body\n\nSASE_PATCH=")),
        _request(_remote(state="closed", merged_at="2026-08-03T00:00:00Z")),
        _request(_remote(title="", body="", state="open")),
        # Refresh: an owned external Patch whose status drifted from the
        # remote's mapped status (open -> Draft here).
        _request(
            _remote(is_draft=True),
            _owned_local(pr_origin="external", status="Mailed"),
        ),
        # Refresh: merged PR moves an owned external Patch to Submitted/archive.
        _request(
            _remote(merged_at="2026-08-03T00:00:00Z"),
            _owned_local(pr_origin="external", status="Mailed"),
        ),
        # Refresh: closed-unmerged PR moves an owned external Patch to Archived.
        _request(
            _remote(state="closed"),
            _owned_local(pr_origin="external", status="Mailed"),
        ),
        # Non-refresh: already matches remote status/destination.
        _request(
            _remote(merged_at="2026-08-03T00:00:00Z"),
            _owned_local(pr_origin="external", status="Submitted", archived=True),
        ),
        # Non-refresh: SASE-owned Patches are never refreshed.
        _request(
            _remote(merged_at="2026-08-03T00:00:00Z"),
            _owned_local(pr_origin="sase", status="Mailed"),
        ),
        # Non-refresh: unknown-origin Patches are never refreshed.
        _request(
            _remote(merged_at="2026-08-03T00:00:00Z"),
            _owned_local(pr_origin="unknown", status="Mailed"),
        ),
    ]

    for request in cases:
        assert asdict(plan_external_pr_import(request)) == asdict(
            _plan_external_pr_import_python(request)
        )
