"""Descriptor-diff helpers for Artifacts generation publication."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from sase.ace.tui.actions._artifacts_publication_diff import (
    _staged_replacement_pane_id,
    _widget_signature,
    diff_artifact_descriptors,
    is_staged_replacement_widget,
    mark_staged_replacement,
    promote_staged_replacement,
)
from sase.ace.tui._artifact_tab_model import ArtifactsTabDescriptor


def _descriptor(
    id_: str,
    *,
    pane_id: str | None = None,
    error: str | None = None,
    digit: str | None = "1",
    label: str | None = None,
) -> ArtifactsTabDescriptor:
    return ArtifactsTabDescriptor(
        id=id_,
        label=label or id_.title(),
        accent="#000000",
        pane_id=pane_id or f"{id_}-pane",
        digit_shortcut=digit,
        error=error,
        error_code=None if error is None else "provider_error",
        error_source=None if error is None else "test",
        provider_kind="plan" if id_.startswith("ref:") else None,
    )


def test_same_id_healthy_to_degraded_is_a_replacement() -> None:
    healthy = _descriptor("ref:plan", pane_id="artifacts-plans-pane")
    degraded = replace(healthy, error="provider exploded", error_code="boom")
    added, removed, replaced = diff_artifact_descriptors((healthy,), (degraded,))
    assert added == []
    assert removed == ()
    assert [descriptor.id for descriptor in replaced] == ["ref:plan"]
    assert _widget_signature(healthy) != _widget_signature(degraded)


def test_digit_only_change_does_not_replace_the_widget() -> None:
    first = _descriptor("files", pane_id="artifacts-files-pane", digit="4")
    second = replace(first, digit_shortcut="9")
    added, removed, replaced = diff_artifact_descriptors((first,), (second,))
    assert added == []
    assert removed == ()
    assert replaced == []
    assert _widget_signature(first) == _widget_signature(second)


def test_staged_replacements_promote_without_a_temporary_dom_id() -> None:
    pane_id = "artifacts-plans-pane"
    widget = SimpleNamespace(id=None)
    mark_staged_replacement(widget, pane_id)
    assert is_staged_replacement_widget(widget)
    assert _staged_replacement_pane_id(widget) == pane_id
    promote_staged_replacement(widget)
    assert widget.id == pane_id
    assert not is_staged_replacement_widget(widget)


def test_contract_digit_change_does_not_replace_the_widget() -> None:
    from sase.ace.tui._artifact_tab_contract import (
        attach_contract,
        compile_builtin_contract,
        contract_with_digit,
    )

    first_contract = contract_with_digit(
        compile_builtin_contract(
            "files",
            label="Files",
            icon="▤",
            accent="#FFAF5F",
        ),
        digit="4",
        order=4,
    )
    second_contract = contract_with_digit(
        compile_builtin_contract(
            "files",
            label="Files",
            icon="▤",
            accent="#FFAF5F",
        ),
        digit="9",
        order=5,
    )
    first = attach_contract(
        _descriptor("files", pane_id="artifacts-files-pane", digit="4"),
        first_contract,
    )
    second = attach_contract(
        _descriptor("files", pane_id="artifacts-files-pane", digit="9"),
        second_contract,
    )
    added, removed, replaced = diff_artifact_descriptors((first,), (second,))
    assert added == []
    assert removed == ()
    assert replaced == []
    assert _widget_signature(first) == _widget_signature(second)
