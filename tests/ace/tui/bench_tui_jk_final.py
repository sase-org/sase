"""Agents-tab j/k key-to-paint with the ⊛ FINAL deck pinned (the triage loop).

Epic sase-1b2 (``final-cutover``) asks for the j/k bench with FINAL pinned:
Reply above, FINAL below, stepping through agents whose finalizers ran. Keys
use a triage cadence -- each one waits out the detail debounce so the lower
panel loads that agent before the next key -- because rapid j/k never lets a
debounced deck load at all. The lower panel alternates between Main and FINAL
in interleaved rounds inside one app (the link-rail bench explains why
interleaving matters), so the printed delta is what FINAL adds to the loop. Every agent carries a
settled glance summary, so rows show ``⊛`` chips and Reply shows the receipt
in both arms. The off-thread loader, document build and card host are real;
only the Rust projection point serves a fixed multi-instance view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping
from sase.core.finalizer_run_view import finalizer_node_view_from_dict
from tests.ace.tui._bench_tui_jk_helpers import (
    _AGENTS_LARGE_LIST_P95_BUDGET_MS,
    _LINK_RAIL_AB_ROUNDS,
    _install_agents_fixture,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_T0 = 1_790_000_000.0
_TRIAGE_KEYS_PER_ROUND = 8
# Past the 0.15 s detail debounce plus the off-thread FINAL load and apply.
_TRIAGE_DWELL_S = 0.35
_SUMMARY = {
    "schema_version": 1,
    "phase": "settled",
    "status": "failed",
    "instances": [
        {"id": "commit", "status": "success"},
        {"id": "check", "status": "failed"},
        {"id": "lint", "status": "success"},
    ],
}


def _instance(instance_id: str, status: str, attempts: int) -> dict[str, Any]:
    """One run instance with ``attempts`` tries, an op and steps per try."""
    return {
        "instance_id": instance_id,
        "status": status,
        "provider_ref": "builtin@command",
        "selection_reason": "default",
        "attempt": attempts,
        "max_attempts": attempts,
        "op": instance_id,
        "attempts": [
            {
                "attempt": number,
                "status": status if number == attempts else "failed",
                "started_at": _T0 + 40 * number,
                "duration_seconds": 30.0,
            }
            for number in range(1, attempts + 1)
        ],
        "operations": [
            {
                "op": instance_id,
                "kind": "subprocess",
                "label": f"just {instance_id}",
                "attempt": number,
                "started_at": _T0 + 40 * number,
                "duration_seconds": 30.0,
                "returncode": 0 if status == "success" else 1,
                "argv": ["just", instance_id],
                "steps": [
                    {"step": f"step {step}", "state": "ok", "t": _T0 + step}
                    for step in range(6)
                ],
            }
            for number in range(1, attempts + 1)
        ],
        "diagnostics": (
            []
            if status == "success"
            else [
                {
                    "code": "command_failed",
                    "message": f"just {instance_id} exited 1",
                    "severity": "error",
                    "attempt": attempts,
                }
            ]
        ),
    }


def _node_view() -> Any:
    """A settled failed run: commit ok, check failed twice, lint ok."""
    instances = [
        _instance("commit", "success", 1),
        _instance("check", "failed", 2),
        _instance("lint", "success", 1),
    ]
    return finalizer_node_view_from_dict(
        {
            "schema_version": 1,
            "status": "failed",
            "glyph": "✗",
            "run_level_trouble": True,
            "attention_instance_id": "check",
            "instances": [
                {
                    "instance_id": item["instance_id"],
                    "selection_reason": "default",
                    "status": item["status"],
                    "provider_ref": "builtin@command",
                }
                for item in instances
            ],
            "unselected": [],
            "runs": [
                {
                    "run_id": "run-1",
                    "number": 0,
                    "label": "run",
                    "kind": "agent",
                    "disposition": "ran",
                    "cycles": 1,
                    "result_status": "failed",
                    "declarations": [
                        {"status": "accepted", "t": _T0, "payload_count": 1}
                    ],
                    "drift": [],
                    "diagnostics": [],
                    "instances": instances,
                }
            ],
        }
    )


def _give_agents_finalizer_runs(app: AceApp, tmp_path: Path) -> None:
    """Give every fixture agent Reply content and a settled finalizer summary."""
    for agent in app._agents:
        directory = tmp_path / str(agent.agent_name)
        directory.mkdir(parents=True, exist_ok=True)
        response = directory / "response.md"
        response.write_text("reply line\n" * 20, encoding="utf-8")
        agent.artifacts_dir = str(directory)
        agent.response_path = str(response)
        agent.finalizer_status = finalizer_status_from_mapping(_SUMMARY)


async def _collect_triage_jk(
    pilot: object, _perf_jsonl: Path
) -> list[dict[str, object]]:
    """Run one warmed j/k stretch at triage cadence; return its own samples."""
    await _warm_agents_navigation(pilot)
    await pilot.pause(_TRIAGE_DWELL_S)  # type: ignore[attr-defined]
    before = len(_read_samples(_perf_jsonl))
    for key in ("j", "k"):
        for _ in range(_TRIAGE_KEYS_PER_ROUND):
            await pilot.press(key)  # type: ignore[attr-defined]
            await pilot.pause(_TRIAGE_DWELL_S)  # type: ignore[attr-defined]
    return _read_samples(_perf_jsonl)[before:]


async def test_bench_agents_jk_with_final_pinned(
    _perf_jsonl: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Time the triage loop: Reply above, FINAL below, j/k across agents."""
    import sase.ace.tui.widgets.decks.final.loader as loader_module

    loader_module.clear_final_cache()
    view = _node_view()
    projected: list[object] = []

    def _project(targets: object) -> Any:
        projected.append(targets)
        return view

    monkeypatch.setattr(loader_module, "project_node_view", _project)

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app)
        _give_agents_finalizer_runs(app, tmp_path)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        detail.set_deck_preferred_card(0, "reply")

        async def _arm(*, final: bool) -> list[dict[str, object]]:
            # Uncached every round: each subject pays the full off-thread
            # load and document apply, the worst case of a first triage pass.
            loader_module.clear_final_cache()
            detail.show_deck(1, DeckId.FINAL if final else DeckId.MAIN)
            await pilot.pause()
            return await _collect_triage_jk(pilot, _perf_jsonl)

        # Discarded rounds absorb one-time layout and renderer work.
        await _arm(final=False)
        await _arm(final=True)
        assert detail.deck_area.panel(1)._final_document is not None, (
            "FINAL never loaded a document for the bench subjects"
        )
        assert len(projected) > 1, "FINAL did not follow j/k to new subjects"

        main_samples: list[dict[str, object]] = []
        final_samples: list[dict[str, object]] = []
        for _ in range(_LINK_RAIL_AB_ROUNDS):
            main_samples += await _arm(final=False)
            loaded = len(projected)
            final_samples += await _arm(final=True)
            assert len(projected) > loaded, "FINAL loaded no subject this round"

    main = _summarize(main_samples)
    final = _summarize(final_samples)
    _print_table("Agents tab j/k, Reply above Main (baseline):", main)
    _print_table("Agents tab j/k, Reply above FINAL (triage loop):", final)
    assert main and final, "perf JSONL captured no samples"
    for scenario, stats in final.items():
        baseline = main.get(scenario)
        delta = stats["p95"] - baseline["p95"] if baseline else float("nan")
        print(f"{scenario}: FINAL-pinned p95 delta {delta:+.2f} ms")
        assert stats["p95"] < _AGENTS_LARGE_LIST_P95_BUDGET_MS, (
            f"FINAL-pinned {scenario} p95 {stats['p95']:.2f} ms exceeded "
            f"{_AGENTS_LARGE_LIST_P95_BUDGET_MS:g} ms: {final}"
        )
