from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui.repro import (
    ReproAgentRow,
    ReproAppState,
    ReproAssertions,
    ReproBundle,
    ReproLoadStep,
    check_bundle_invariants,
    load_bundle,
)


FIXTURE = Path(__file__).parent / "fixtures" / "agents_tab_disappear_reappear_v1.json"


def _failure_codes(bundle: ReproBundle) -> set[str]:
    return {failure.code for failure in check_bundle_invariants(bundle).failures}


def _with_steps(
    bundle: ReproBundle,
    replacements: dict[str, ReproLoadStep],
    *,
    assertions: ReproAssertions | None = None,
) -> ReproBundle:
    return replace(
        bundle,
        load_steps=[replacements.get(step.step_id, step) for step in bundle.load_steps],
        assertions=bundle.assertions if assertions is None else assertions,
    )


def _repair_expected_visible_projection(bundle: ReproBundle) -> ReproBundle:
    replacements: dict[str, ReproLoadStep] = {}
    for step in bundle.load_steps:
        expected = bundle.assertions.expected_visible_identities_by_step.get(
            step.step_id
        )
        if expected is None:
            continue
        replacements[step.step_id] = replace(
            step,
            app_state=replace(step.app_state, visible_identities=expected),
        )
    return _with_steps(bundle, replacements)


def test_fixture_is_commit_safe_and_loadable() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")

    bundle = load_bundle(FIXTURE)

    assert bundle.manifest.commit_safe is True
    assert bundle.manifest.schema_version == 1
    assert "/home/" not in raw
    assert "prompt_body" not in raw
    assert "chat_body" not in raw
    assert "diff_body" not in raw


def test_broken_fixture_flags_post_complete_incomplete_shrink() -> None:
    bundle = load_bundle(FIXTURE)

    codes = _failure_codes(bundle)

    assert "post_complete_incomplete_shrink" in codes
    assert "expected_visible_mismatch" in codes


def test_expected_merged_visible_projection_passes_invariants() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))

    report = check_bundle_invariants(bundle)

    report.assert_ok()


def test_duplicate_visible_root_is_reported() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))
    step = bundle.load_steps[1]
    duplicate = ReproAgentRow(
        agent_type="run",
        cl_name="history_work",
        raw_suffix="20260510103000",
        status="RUNNING",
        workflow="run",
        pid=39001,
        workspace_num=100,
    )
    broken_step = replace(
        step,
        agent_rows=[*step.agent_rows, duplicate],
        app_state=replace(
            step.app_state,
            visible_identities=[*step.app_state.visible_identities, duplicate.identity],
        ),
    )
    bundle = _with_steps(
        bundle,
        {step.step_id: broken_step},
        assertions=ReproAssertions(),
    )

    assert "duplicate_visible_root" in _failure_codes(bundle)


def test_visible_child_without_parent_is_reported() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))
    step = bundle.load_steps[1]
    child_identity = ("workflow", "history_work", "20260510103000.01")
    broken_step = replace(
        step,
        app_state=replace(
            step.app_state,
            visible_identities=[
                identity
                for identity in step.app_state.visible_identities
                if identity != ("workflow", "history_work", "20260510103000")
            ],
            selected_identity=child_identity,
        ),
    )
    bundle = _with_steps(
        bundle,
        {step.step_id: broken_step},
        assertions=ReproAssertions(),
    )

    assert "visible_child_without_parent" in _failure_codes(bundle)


def test_selection_change_without_fallback_is_reported() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))
    step = bundle.load_steps[1]
    broken_step = replace(
        step,
        app_state=replace(
            step.app_state,
            selected_identity=("workflow", "history_work", "20260510103000"),
        ),
    )
    bundle = _with_steps(
        bundle,
        {step.step_id: broken_step},
        assertions=ReproAssertions(),
    )

    assert "selected_identity_not_preserved" in _failure_codes(bundle)


def test_flattened_child_parent_exception_is_honored() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))
    step = bundle.load_steps[1]
    flattened_state = replace(
        step.app_state,
        visible_identities=[
            identity
            for identity in step.app_state.visible_identities
            if identity != ("workflow", "history_work", "20260510103000")
        ],
        flattened_parent_timestamps=["20260510103000"],
    )
    bundle = _with_steps(
        bundle,
        {step.step_id: replace(step, app_state=flattened_state)},
        assertions=ReproAssertions(),
    )

    assert "visible_child_without_parent" not in _failure_codes(bundle)


def test_repeated_refresh_stability_mismatch_is_reported() -> None:
    bundle = _repair_expected_visible_projection(load_bundle(FIXTURE))
    repeat_step = bundle.load_steps[3]
    broken_repeat = replace(
        repeat_step,
        app_state=replace(
            repeat_step.app_state,
            visible_identities=[("run", "current_work", "20260513120000")],
        ),
    )
    bundle = _with_steps(bundle, {repeat_step.step_id: broken_repeat})

    assert "replay_refresh_not_stable" in _failure_codes(bundle)
