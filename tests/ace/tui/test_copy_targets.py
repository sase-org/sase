"""Contracts for the shared copy-target registry and representations."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.clipboard import (
    _artifact_reference_resolution as _resolution,
)
from sase.ace.tui.actions.clipboard import _artifacts, _changespec
from sase.ace.tui.actions.clipboard._helpers import (
    MAX_COPY_CONTENT_BYTES,
    cap_copy_content,
    format_multi_copy_content_capped,
)
from sase.ace.tui.copy_targets import COPY_TARGETS, copy_targets_for
from sase.ace.tui.keymaps.mode_keymaps import CopyModeKeymaps
from tests.ace.tui._artifacts_copy_helpers import CopyHarness as _CopyHarness


def test_copy_target_registry_exactly_covers_default_keymap_targets() -> None:
    defaults = CopyModeKeymaps().keys

    assert {target.group for target in COPY_TARGETS} == set(defaults)
    for group, configured in defaults.items():
        assert isinstance(configured, dict)
        assert {target.target for target in copy_targets_for(group)} == set(configured)
        for target in copy_targets_for(group):
            assert target.footer_label
            assert target.palette_label
            assert target.plural_label


@pytest.mark.parametrize(
    ("kind", "label", "reference"),
    [
        ("commit", "Fix copy mode", "commit:sase@" + "a" * 40),
        ("plan", "Unified copy palette", "designs:202607/copy.md"),
        ("chat", "sase-az.2.md", "chat:202607/sase-az.2.md"),
        ("bug", "Copy links", "bug:SASE#42"),
    ],
)
def test_link_and_metadata_json_builders_cover_every_artifact_kind(
    kind: str,
    label: str,
    reference: str,
) -> None:
    item = _artifacts._ArtifactReferenceItem(
        label,
        (kind,),
        None,
        "sase",
        "/tmp",
        markdown_label=label,
        kind_label=kind,
    )
    metadata = {"reference": reference, "kind": kind}
    resolved = (_artifacts._ResolvedArtifactItem(item, reference, metadata),)

    assert (
        _artifacts._format_artifact_representation("link", resolved, marked=False)
        == f"[{label}]({reference})"
    )
    assert (
        json.loads(
            _artifacts._format_artifact_representation("json", resolved, marked=False)
        )
        == metadata
    )
    assert (
        _artifacts._artifact_representation_label(
            "json",
            resolved,
            marked=False,
            failure_count=0,
        )
        == f"{kind} metadata JSON"
    )


def test_marked_representations_are_paste_ready_and_report_partial_failures() -> None:
    items = tuple(
        _artifacts._ResolvedArtifactItem(
            _artifacts._ArtifactReferenceItem(
                f"Entry {index}",
                ("commit", str(index)),
                None,
                "sase",
                "/tmp",
                markdown_label=f"Entry {index}",
                kind_label="commit",
            ),
            f"commit:sase@{str(index) * 40}",
            {"reference": f"commit:sase@{str(index) * 40}"},
        )
        for index in (1, 2)
    )

    references = _artifacts._format_artifact_representation(
        "reference", items, marked=True
    )
    links = _artifacts._format_artifact_representation("link", items, marked=True)
    metadata = _artifacts._format_artifact_representation("json", items, marked=True)

    assert references == "\n".join(f"@{item.reference}" for item in items)
    assert links == "\n".join(
        f"- [Entry {index}]({item.reference})"
        for index, item in zip((1, 2), items, strict=True)
    )
    assert json.loads(metadata) == [item.metadata for item in items]
    assert (
        _artifacts._artifact_representation_label(
            "reference",
            items,
            marked=True,
            failure_count=2,
        )
        == "2 references — 2 entries have no reference"
    )


def test_metadata_resolution_skips_unrepresentable_items_and_reuses_cli_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = object()
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="commits",
        items=(
            _artifacts._ArtifactReferenceItem(
                "good",
                ("commit", "sase", "a" * 40),
                None,
                "sase",
                "/tmp",
            ),
            _artifacts._ArtifactReferenceItem(
                "missing",
                ("commit", "sase", "b" * 40),
                None,
                "sase",
                "/tmp",
            ),
        ),
        marked=True,
        prompt_project="sase",
        prompt_display_name="SASE",
        prompt_project_file="/tmp/sase.sase",
    )
    monkeypatch.setattr(_resolution, "artifact_ref_context", lambda *_args: context)
    monkeypatch.setattr(
        _resolution,
        "reference_for_entry_target",
        lambda _subtab, target, **_kwargs: (
            f"commit:sase@{target[2]}" if target[2].startswith("a") else None
        ),
    )
    monkeypatch.setattr(
        _resolution,
        "resolve_cli_reference",
        lambda reference, *, context: SimpleNamespace(
            to_json_dict=lambda: {"reference": reference, "source": "cli"}
        ),
    )

    resolved = _artifacts._resolve_artifact_selection(
        selection,
        include_metadata=True,
    )

    assert [item.reference for item in resolved.items] == [f"commit:sase@{'a' * 40}"]
    assert resolved.items[0].metadata == {
        "reference": f"commit:sase@{'a' * 40}",
        "source": "cli",
    }
    assert resolved.failures == (
        "missing cannot be referenced because its artifact identity is incomplete",
    )


def test_content_caps_bound_each_item_and_the_total_with_a_banner() -> None:
    oversized = "é" * MAX_COPY_CONTENT_BYTES

    single = cap_copy_content(oversized)
    marked = format_multi_copy_content_capped([("one", oversized), ("two", oversized)])

    assert single.truncated is True
    assert len(single.value.encode("utf-8")) <= MAX_COPY_CONTENT_BYTES
    assert f"[Truncated at {MAX_COPY_CONTENT_BYTES:,} bytes]" in single.value
    assert marked.truncated is True
    assert len(marked.value.encode("utf-8")) <= MAX_COPY_CONTENT_BYTES
    assert f"[Truncated at {MAX_COPY_CONTENT_BYTES:,} bytes]" in marked.value


@pytest.mark.parametrize("pr_url", [None, ""])
def test_changespec_link_warns_without_a_pr_url(pr_url: str | None) -> None:
    app = _CopyHarness()
    app.current_idx = 0
    app.changespecs = [SimpleNamespace(name="sase_copy", pr_url=pr_url)]

    app._copy_changespec_link()

    assert app.notifications[-1] == ("No PR URL available", "warning")


def test_changespec_link_uses_humanized_name_and_pr_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _CopyHarness()
    app.current_idx = 0
    app.changespecs = [
        SimpleNamespace(
            name="sase_copy",
            pr_url="https://github.com/sase-org/sase/pull/42",
        )
    ]
    scheduled: list[tuple[str, str]] = []
    monkeypatch.setattr(_changespec, "humanize_cl_name", lambda _name: "SASE copy")
    monkeypatch.setattr(
        _changespec,
        "schedule_copy_delivery",
        lambda _owner, value, *, copied_label, **_kwargs: scheduled.append(
            (value, copied_label)
        ),
    )

    app._copy_changespec_link()

    assert scheduled == [
        (
            "[SASE copy](https://github.com/sase-org/sase/pull/42)",
            "ChangeSpec Markdown link",
        )
    ]
