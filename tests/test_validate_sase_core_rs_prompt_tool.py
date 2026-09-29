from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._validate_sase_core_rs_tool_helpers import (
    load_validate_sase_core_rs,
    module_with_required_bindings,
)


pytestmark = pytest.mark.contract


def test_validate_sase_core_rs_requires_prompt_stash_lifecycle_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "prompt_stash_lifecycle_wire_schema_version",
        "read_prompt_stash_lifecycle",
        "trash_prompt_stash",
        "restore_prompt_stash",
        "purge_prompt_stash",
        "reconcile_prompt_stash_trash",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_prompt_stash_lifecycle_wire_schema() -> None:
    validator = load_validate_sase_core_rs()

    assert validator._validate_prompt_stash_lifecycle_schema(
        SimpleNamespace(prompt_stash_lifecycle_wire_schema_version=lambda: 1)
    )
    assert not validator._validate_prompt_stash_lifecycle_schema(
        SimpleNamespace(prompt_stash_lifecycle_wire_schema_version=lambda: 2)
    )


def test_validate_sase_core_rs_probes_prompt_stash_lifecycle_contract() -> None:
    validator = load_validate_sase_core_rs()
    stores: dict[str, dict[str, list[dict[str, object]]]] = {}

    def store_for(path: str) -> dict[str, list[dict[str, object]]]:
        return stores.setdefault(path, {"active": [], "trash": []})

    def row_id(row: dict[str, object]) -> str:
        value = row["entry"] if "entry" in row else row
        if isinstance(value, dict):
            return str(value.get("id"))
        return str(value)

    def snapshot(path: str) -> dict[str, object]:
        store = store_for(path)
        ordered = sorted(
            store["trash"],
            key=lambda row: (str(row["trashed_at"]), row_id(row)),
            reverse=True,
        )
        return {
            "schema_version": 1,
            "active": list(store["active"]),
            "trash": ordered,
            "stats": {"loaded_rows": len(store["active"]) + len(store["trash"])},
        }

    def outcome(path: str, changed: list[str], evicted: list[str]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "changed": changed,
            "evicted": evicted,
            "snapshot": snapshot(path),
        }

    def append(path: str, row: dict[str, object]) -> dict[str, object]:
        store_for(path)["active"].append(row)
        return dict(snapshot(path), entries=list(store_for(path)["active"]))

    def enforce(path: str, trash_limit: int) -> list[str]:
        store = store_for(path)
        evicted: list[str] = []
        while len(store["trash"]) > trash_limit:
            oldest = min(
                store["trash"],
                key=lambda row: (str(row["trashed_at"]), row_id(row)),
            )
            store["trash"].remove(oldest)
            evicted.append(row_id(oldest))
        return evicted

    def trash(
        path: str, ids: list[str], trash_limit: int, stamp: str
    ) -> dict[str, object]:
        store = store_for(path)
        moved = [row for row in store["active"] if str(row["id"]) in ids]
        store["active"] = [row for row in store["active"] if str(row["id"]) not in ids]
        for row in moved:
            store["trash"].append({"trashed_at": stamp, "entry": row})
        evicted = enforce(path, trash_limit)
        moved_ids = [str(row["id"]) for row in moved]
        changed = [i for i in ids if i in moved_ids and i not in evicted]
        return outcome(path, changed, evicted)

    def restore(path: str, ids: list[str]) -> dict[str, object]:
        store = store_for(path)
        kept: list[dict[str, object]] = []
        changed: list[str] = []
        for row in store["trash"]:
            if row_id(row) in ids:
                entry_value = row["entry"]
                store["active"].append(
                    entry_value if isinstance(entry_value, dict) else {}
                )
                changed.append(row_id(row))
            else:
                kept.append(row)
        store["trash"] = kept
        return outcome(path, changed, [])

    def purge(path: str, ids: list[str]) -> dict[str, object]:
        store = store_for(path)
        changed = [row_id(row) for row in store["trash"] if row_id(row) in ids]
        store["trash"] = [row for row in store["trash"] if row_id(row) not in ids]
        return outcome(path, changed, [])

    def reconcile(path: str, trash_limit: int) -> dict[str, object]:
        return outcome(path, [], enforce(path, trash_limit))

    good = SimpleNamespace(
        append_prompt_stash=append,
        prompt_stash_lifecycle_wire_schema_version=lambda: 1,
        read_prompt_stash_lifecycle=snapshot,
        trash_prompt_stash=trash,
        restore_prompt_stash=restore,
        purge_prompt_stash=purge,
        reconcile_prompt_stash_trash=reconcile,
    )
    assert validator._validate_prompt_stash_lifecycle_contract(good)

    def stale_trash(
        path: str, ids: list[str], trash_limit: int, stamp: str
    ) -> dict[str, object]:
        return outcome(path, ids, [])

    stale = SimpleNamespace(**{**good.__dict__, "trash_prompt_stash": stale_trash})
    stores.clear()
    assert not validator._validate_prompt_stash_lifecycle_contract(stale)


def test_validate_sase_core_rs_requires_prompt_prediction_bindings() -> None:
    validator = load_validate_sase_core_rs()
    bindings = {
        "PromptPredictionCorpus",
        "PromptPredictionModel",
        "prompt_prediction_wire_schema_version",
        "evaluate_prompt_prediction_replay",
    }

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(module_with_required_bindings(validator))
    for binding in bindings:
        assert not validator._validate_bindings(
            module_with_required_bindings(validator, missing={binding})
        )


def _prompt_prediction_module(**overrides: object) -> SimpleNamespace:
    class _Corpus:
        def stats(self) -> dict[str, object]:
            return {
                "schema_version": 1,
                "rows_used": 3,
                "rows_generated_skipped": 0,
                "rows_duplicate_skipped": 0,
                "tokens": 18,
                "contexts": 10,
                "successor_entries": 12,
                "approx_bytes": 512,
            }

    class _Model:
        def predict(self, _request: str) -> dict[str, object]:
            return {
                "schema_version": 1,
                "blocked_reason": None,
                "context_words": ["help", "me", "implement"],
                "confident": True,
                "ghost": ["the"],
                "candidates": [
                    {
                        "word": "the",
                        "key": "the",
                        "score": 0.9,
                        "probability": 0.9,
                        "support": 3,
                        "order": 2,
                        "source_shares": {"history": 1.0},
                        "continuation": [],
                    }
                ],
            }

        def rank_prefix(self, _request: str) -> dict[str, object]:
            return {
                "schema_version": 1,
                "context_words": ["help", "me"],
                "matches": [
                    {
                        "word": "implement",
                        "key": "implement",
                        "score": 0.8,
                        "order": 2,
                        "support": 3,
                    }
                ],
            }

    def _replay(_rows: str, _options: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "rows_total": 3,
            "rows_typed": 3,
            "rows_warmed": 1,
            "rows_scored": 2,
            "positions_total": 12,
            "overall_top1": 0.5,
            "overall_top3": 0.75,
            "cautious": {"coverage": 0.1, "precision": 1.0},
            "balanced": {"coverage": 0.3, "precision": 0.8},
            "eager": {"coverage": 0.5, "precision": 0.6},
            "cohorts": [
                {"cohort": "novel", "positions": 4},
                {"cohort": "mid", "positions": 4},
                {"cohort": "near-duplicate", "positions": 4},
            ],
            "sweep": [{"min_p": 0.6, "min_margin": 0.2, "min_support": 3}],
            "latency_us_p50": 20,
            "latency_us_p95": 60,
            "corpus_bytes": 512,
            "corpus_rows_used": 3,
            "corpus_contexts": 10,
        }

    namespace = {
        "prompt_prediction_wire_schema_version": lambda: 1,
        "PromptPredictionCorpus": lambda _rows, _options: _Corpus(),
        "PromptPredictionModel": lambda _sources, _config: _Model(),
        "evaluate_prompt_prediction_replay": _replay,
    }
    namespace.update(overrides)
    return SimpleNamespace(**namespace)


def test_validate_sase_core_rs_probes_prompt_prediction_contract() -> None:
    validator = load_validate_sase_core_rs()
    assert validator._validate_prompt_prediction_contract(_prompt_prediction_module())
    assert not validator._validate_prompt_prediction_contract(
        _prompt_prediction_module(prompt_prediction_wire_schema_version=lambda: 2)
    )
