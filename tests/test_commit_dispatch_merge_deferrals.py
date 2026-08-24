"""Coverage for merging per-repository deferrals into one result wire."""

from __future__ import annotations

from sase.core.finalizer_wire import FinalizerDeferralWire
from sase.finalizers.commit_dispatch import _DeferredRepoOutcome, merge_deferrals
from sase.llm_provider.commit_finalizer_types import DirtyRepo


def _repo(name: str) -> DirtyRepo:
    return DirtyRepo(name=name, path=f"/repos/{name}", changed_files=(), kind="main")


def test_merge_deferrals_dedupes_paths_within_one_reason() -> None:
    deferred = [
        _DeferredRepoOutcome(
            repo=_repo("a"),
            deferral=FinalizerDeferralWire(
                reason="protected_paths", paths=["x.txt", "y.txt"]
            ),
        ),
        _DeferredRepoOutcome(
            repo=_repo("b"),
            deferral=FinalizerDeferralWire(
                reason="protected_paths", paths=["y.txt", "z.txt"]
            ),
        ),
    ]

    merged = merge_deferrals(deferred)

    assert merged.reason == "protected_paths"
    assert merged.paths == ["x.txt", "y.txt", "z.txt"]


def test_merge_deferrals_keeps_first_reason_for_mixed_reasons() -> None:
    deferred = [
        _DeferredRepoOutcome(
            repo=_repo("a"),
            deferral=FinalizerDeferralWire(reason="unsafe_content", paths=["x.txt"]),
        ),
        _DeferredRepoOutcome(
            repo=_repo("b"),
            deferral=FinalizerDeferralWire(reason="foreign_work", paths=["y.txt"]),
        ),
    ]

    merged = merge_deferrals(deferred)

    assert merged.reason == "unsafe_content"
    assert merged.paths == ["x.txt", "y.txt"]
