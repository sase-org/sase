"""Fresh-tag train facts for release-watch train start."""

from __future__ import annotations

from tests._release_watch_train_start_helpers import CANDIDATE
from tests._release_watch_train_start_helpers import VERSION
from tests._release_watch_train_start_helpers import fresh_context


def test_fresh_unsealed_tag_is_its_own_fact() -> None:
    trains, candidate = fresh_context()
    assert len(trains) == 1
    train = trains[0]
    assert train["candidate_id"] == CANDIDATE
    assert train["generation"] == 0
    assert train["manifest_mismatch"] is False
    assert train["abandoned"] is False
    assert train["py_files_present"] == 0
    assert candidate is None


def test_fresh_tag_without_merged_head_knowledge_is_still_fresh() -> None:
    trains, _candidate = fresh_context(merged_head_sha=None)
    assert trains[0]["manifest_mismatch"] is False


def test_fresh_tag_with_pypi_files_stays_mismatch() -> None:
    trains, _candidate = fresh_context(
        pypi_files=[
            {
                "filename": f"sase-{VERSION}-py3-none-any.whl",
                "version": VERSION,
                "sha256": "d" * 64,
                "yanked": False,
            }
        ]
    )
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_head_mismatch_stays_mismatch() -> None:
    trains, _candidate = fresh_context(merged_head_sha="d" * 40)
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_without_draft_release_stays_mismatch() -> None:
    trains, _candidate = fresh_context(draft=False)
    assert trains[0]["manifest_mismatch"] is True
    trains, _candidate = fresh_context(release_exists=False)
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_with_burned_observation_is_abandoned() -> None:
    name = "candidate-gen0-abandoned-run500-attempt1.json"
    trains, _candidate = fresh_context(
        extra_assets=[{"id": 7, "name": name}],
        asset_payloads={
            7: {
                "asset": name,
                "kind": "abandoned",
                "generation": 0,
                "candidate_id": CANDIDATE,
                "run_id": 500,
                "attempt": 1,
                "verdict": "abandoned",
            }
        },
    )
    assert trains[0]["manifest_mismatch"] is False
    assert trains[0]["abandoned"] is True


def test_fresh_tag_with_foreign_abandoned_observation_is_not_abandoned() -> None:
    name = "candidate-gen0-abandoned-run500-attempt1.json"
    trains, _candidate = fresh_context(
        extra_assets=[{"id": 7, "name": name}],
        asset_payloads={
            7: {
                "asset": name,
                "kind": "abandoned",
                "generation": 0,
                "candidate_id": "unsealed:v9.9.9:" + "e" * 40,
                "run_id": 500,
                "attempt": 1,
                "verdict": "abandoned",
            }
        },
    )
    assert trains[0]["abandoned"] is False
