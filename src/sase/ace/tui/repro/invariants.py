"""Invariant checks for Agents-tab reproduction bundles."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import AgentIdentity, ReproAgentRow, ReproBundle, ReproLoadStep


@dataclass(frozen=True)
class ReproInvariantFailure:
    """One failed invariant with a stable code for CLI and tests."""

    code: str
    message: str
    step_id: str | None = None


@dataclass(frozen=True)
class ReproInvariantReport:
    """Aggregated invariant-check result."""

    failures: list[ReproInvariantFailure]

    @property
    def ok(self) -> bool:
        return not self.failures

    def assert_ok(self) -> None:
        if self.failures:
            details = "\n".join(
                f"{failure.code}: {failure.message}" for failure in self.failures
            )
            raise AssertionError(details)


def check_bundle_invariants(bundle: ReproBundle) -> ReproInvariantReport:
    """Check all Phase 1 structured invariants for a bundle."""

    failures: list[ReproInvariantFailure] = []
    known_rows: dict[AgentIdentity, ReproAgentRow] = {}
    complete_history_visible: set[AgentIdentity] = set()
    saw_complete_history = False
    previous_selected: AgentIdentity | None = None

    for step in bundle.load_steps:
        for row in step.agent_rows:
            known_rows[row.identity] = row

        visible = list(step.app_state.visible_identities)
        visible_set = set(visible)
        dismissed_set = set(step.app_state.dismissed_identities)

        failures.extend(_check_visible_identity_shape(step, visible, known_rows))
        failures.extend(
            _check_post_complete_incomplete_shrink(
                step=step,
                visible_set=visible_set,
                dismissed_set=dismissed_set,
                complete_history_visible=complete_history_visible,
                saw_complete_history=saw_complete_history,
            )
        )
        failures.extend(_check_duplicate_roots(step, visible, known_rows))
        failures.extend(_check_children_have_visible_parents(step, visible, known_rows))
        failures.extend(
            _check_selection(
                step=step,
                visible_set=visible_set,
                previous_selected=previous_selected,
            )
        )

        if step.load_state.complete_history:
            saw_complete_history = True
            complete_history_visible.update(visible_set - dismissed_set)
        previous_selected = step.app_state.selected_identity

    failures.extend(_check_expected_visible(bundle))
    failures.extend(_check_stability(bundle))
    return ReproInvariantReport(failures)


def _check_visible_identity_shape(
    step: ReproLoadStep,
    visible: list[AgentIdentity],
    known_rows: dict[AgentIdentity, ReproAgentRow],
) -> list[ReproInvariantFailure]:
    failures: list[ReproInvariantFailure] = []
    seen: set[AgentIdentity] = set()
    for identity in visible:
        if identity in seen:
            failures.append(
                ReproInvariantFailure(
                    code="duplicate_visible_identity",
                    step_id=step.step_id,
                    message=f"{identity!r} appears more than once",
                )
            )
        seen.add(identity)
        if identity not in known_rows:
            failures.append(
                ReproInvariantFailure(
                    code="unknown_visible_identity",
                    step_id=step.step_id,
                    message=f"{identity!r} is visible but has no row summary",
                )
            )
    return failures


def _check_post_complete_incomplete_shrink(
    *,
    step: ReproLoadStep,
    visible_set: set[AgentIdentity],
    dismissed_set: set[AgentIdentity],
    complete_history_visible: set[AgentIdentity],
    saw_complete_history: bool,
) -> list[ReproInvariantFailure]:
    if step.load_state.complete_history or not saw_complete_history:
        return []

    missing = sorted(
        complete_history_visible - visible_set - dismissed_set,
        key=_identity_sort_key,
    )
    if not missing:
        return []
    return [
        ReproInvariantFailure(
            code="post_complete_incomplete_shrink",
            step_id=step.step_id,
            message=(
                "post-complete-history incomplete load hid historical rows: "
                + ", ".join(_format_identity(identity) for identity in missing)
            ),
        )
    ]


def _check_duplicate_roots(
    step: ReproLoadStep,
    visible: list[AgentIdentity],
    known_rows: dict[AgentIdentity, ReproAgentRow],
) -> list[ReproInvariantFailure]:
    roots_by_key: dict[tuple[str, str], list[AgentIdentity]] = {}
    for identity in visible:
        row = known_rows.get(identity)
        if row is None or row.is_child or row.raw_suffix is None:
            continue
        roots_by_key.setdefault((row.cl_name, row.raw_suffix), []).append(identity)

    failures: list[ReproInvariantFailure] = []
    for root_key, identities in roots_by_key.items():
        if len(identities) <= 1:
            continue
        failures.append(
            ReproInvariantFailure(
                code="duplicate_visible_root",
                step_id=step.step_id,
                message=(
                    f"visible root {root_key!r} has duplicate root rows: "
                    + ", ".join(_format_identity(identity) for identity in identities)
                ),
            )
        )
    return failures


def _check_children_have_visible_parents(
    step: ReproLoadStep,
    visible: list[AgentIdentity],
    known_rows: dict[AgentIdentity, ReproAgentRow],
) -> list[ReproInvariantFailure]:
    flattened = set(step.app_state.flattened_parent_timestamps)
    visible_parent_suffixes = {
        row.raw_suffix
        for identity in visible
        if (row := known_rows.get(identity)) is not None
        and not row.is_child
        and row.raw_suffix is not None
    }

    failures: list[ReproInvariantFailure] = []
    for identity in visible:
        row = known_rows.get(identity)
        if row is None or row.parent_timestamp is None:
            continue
        if row.parent_timestamp in visible_parent_suffixes:
            continue
        if row.parent_timestamp in flattened:
            continue
        failures.append(
            ReproInvariantFailure(
                code="visible_child_without_parent",
                step_id=step.step_id,
                message=(
                    f"visible child {_format_identity(identity)} references "
                    f"hidden parent suffix {row.parent_timestamp!r}"
                ),
            )
        )
    return failures


def _check_selection(
    *,
    step: ReproLoadStep,
    visible_set: set[AgentIdentity],
    previous_selected: AgentIdentity | None,
) -> list[ReproInvariantFailure]:
    selected = step.app_state.selected_identity
    fallback = step.app_state.selection_fallback
    failures: list[ReproInvariantFailure] = []

    if selected is not None and selected not in visible_set:
        failures.append(
            ReproInvariantFailure(
                code="selected_identity_not_visible",
                step_id=step.step_id,
                message=f"selected identity {_format_identity(selected)} is hidden",
            )
        )

    if (
        previous_selected is not None
        and previous_selected in visible_set
        and selected != previous_selected
        and fallback is None
    ):
        failures.append(
            ReproInvariantFailure(
                code="selected_identity_not_preserved",
                step_id=step.step_id,
                message=(
                    "selection moved from "
                    f"{_format_identity(previous_selected)} to "
                    f"{_format_identity(selected)} without a fallback marker"
                ),
            )
        )

    if fallback is not None:
        if fallback.to_identity != selected:
            failures.append(
                ReproInvariantFailure(
                    code="selection_fallback_target_mismatch",
                    step_id=step.step_id,
                    message="selection fallback target does not match selected identity",
                )
            )
        if (
            previous_selected is not None
            and previous_selected in visible_set
            and fallback.from_identity != previous_selected
        ):
            failures.append(
                ReproInvariantFailure(
                    code="selection_fallback_source_mismatch",
                    step_id=step.step_id,
                    message="selection fallback source does not match prior selection",
                )
            )
    return failures


def _check_expected_visible(bundle: ReproBundle) -> list[ReproInvariantFailure]:
    step_by_id = {step.step_id: step for step in bundle.load_steps}
    failures: list[ReproInvariantFailure] = []
    for (
        step_id,
        expected,
    ) in bundle.assertions.expected_visible_identities_by_step.items():
        step = step_by_id.get(step_id)
        if step is None:
            failures.append(
                ReproInvariantFailure(
                    code="expected_visible_unknown_step",
                    step_id=step_id,
                    message=f"assertions reference unknown step {step_id!r}",
                )
            )
            continue
        if step.app_state.visible_identities != expected:
            failures.append(
                ReproInvariantFailure(
                    code="expected_visible_mismatch",
                    step_id=step_id,
                    message=(
                        "visible identities do not match expected fixed projection"
                    ),
                )
            )
    return failures


def _check_stability(bundle: ReproBundle) -> list[ReproInvariantFailure]:
    stable_step_ids = bundle.assertions.stable_step_ids
    if len(stable_step_ids) < 2:
        return []

    step_by_id = {step.step_id: step for step in bundle.load_steps}
    signatures: list[tuple[str, tuple[AgentIdentity, ...], AgentIdentity | None]] = []
    failures: list[ReproInvariantFailure] = []
    for step_id in stable_step_ids:
        step = step_by_id.get(step_id)
        if step is None:
            failures.append(
                ReproInvariantFailure(
                    code="stable_unknown_step",
                    step_id=step_id,
                    message=f"stability assertion references unknown step {step_id!r}",
                )
            )
            continue
        signatures.append(
            (
                step_id,
                tuple(step.app_state.visible_identities),
                step.app_state.selected_identity,
            )
        )

    if len(signatures) < 2:
        return failures

    _, first_visible, first_selected = signatures[0]
    for step_id, visible, selected in signatures[1:]:
        if visible == first_visible and selected == first_selected:
            continue
        failures.append(
            ReproInvariantFailure(
                code="replay_refresh_not_stable",
                step_id=step_id,
                message=f"step {step_id!r} did not converge to the stable projection",
            )
        )
    return failures


def _identity_sort_key(identity: AgentIdentity) -> tuple[str, str, str]:
    return (identity[1], identity[2] or "", identity[0])


def _format_identity(identity: AgentIdentity | None) -> str:
    if identity is None:
        return "<none>"
    return f"{identity[0]}:{identity[1]}:{identity[2] or '<none>'}"
