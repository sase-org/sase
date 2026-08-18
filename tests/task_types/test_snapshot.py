from __future__ import annotations

from typing import Any

from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)
from sase.task_types._validation import validate_task_type_spec
from sase.task_types.snapshot import (
    build_committed_task_type_snapshot_entries,
    committed_task_type_records,
    describe_task_type_snapshot_drift,
    render_task_type_snapshot_json,
    task_type_snapshot_entry,
)


def _spec(slug: str, **overrides: Any) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "task_type": slug,
        "label": slug.title(),
        "summary": f"A {slug} task type used by snapshot tests.",
        "when_to_use": f"File a {slug} when the snapshot tests need one.",
    }
    spec.update(overrides)
    return spec


def _record(
    slug: str,
    *,
    source: str = "builtin",
    package: str = "sase",
    version: str = "1.0.0",
    digest: str = "a" * 64,
    builtin: bool = False,
    spec_overrides: dict[str, Any] | None = None,
) -> TaskTypeRecord:
    return TaskTypeRecord(
        task_type=slug,
        spec=_spec(slug, **(spec_overrides or {})),
        digest=digest,
        provenance=TaskTypeProvenance(
            source=source,  # type: ignore[arg-type]
            name=package,
            package=package,
            version=version,
            builtin=builtin or source == "builtin",
        ),
    )


def _registry(*records: TaskTypeRecord) -> TaskTypeRegistry:
    return TaskTypeRegistry(records=records, diagnostics=())


def test_committed_catalog_keeps_builtins_and_project_types() -> None:
    builtin = _record("bug", source="builtin", builtin=True)
    project = _record("incident", source="project", package="project")
    records = committed_task_type_records(
        _registry(builtin, project),
        required_packages=frozenset(),
    )
    assert [record.task_type for record in records] == ["bug", "incident"]


def test_committed_catalog_drops_optional_plugin_types() -> None:
    builtin = _record("bug", source="builtin", builtin=True)
    optional = _record(
        "incident",
        source="plugin",
        package="sase-linear",
        version="0.3.0",
    )
    required = _record(
        "github",
        source="plugin",
        package="sase-github",
        version="0.4.1",
    )
    records = committed_task_type_records(
        _registry(builtin, optional, required),
        required_packages=frozenset({"sase-github"}),
    )
    assert [record.task_type for record in records] == ["bug", "github"]


def test_committed_snapshot_entries_ignore_optional_plugins() -> None:
    optional = _record("incident", source="plugin", package="sase-linear")
    entries = build_committed_task_type_snapshot_entries(
        _registry(optional),
        required_packages=frozenset(),
    )
    assert entries == ()


def test_describe_snapshot_drift_names_digest_and_package() -> None:
    original_spec = _spec("github", summary="A GitHub issue mirrored into a task.")
    updated_spec = _spec("github", summary="A mirrored GitHub issue, digest changed.")
    original = _record(
        "github",
        source="plugin",
        package="sase-github",
        version="0.4.1",
        digest=validate_task_type_spec(original_spec),
        spec_overrides={"summary": original_spec["summary"]},
    )
    updated = _record(
        "github",
        source="plugin",
        package="sase-github",
        version="0.4.1",
        digest=validate_task_type_spec(updated_spec),
        spec_overrides={"summary": updated_spec["summary"]},
    )
    committed = render_task_type_snapshot_json([task_type_snapshot_entry(original)])
    live = render_task_type_snapshot_json([task_type_snapshot_entry(updated)])

    detail = describe_task_type_snapshot_drift(
        committed, live, registry=_registry(updated)
    )

    assert "`github` spec digest changed (sase-github 0.4.1 installed)" in detail
    assert "run `sase memory init`" in detail


def test_describe_snapshot_drift_names_new_live_type() -> None:
    spec = _spec("incident")
    live_record = _record(
        "incident",
        source="plugin",
        package="sase-linear",
        version="0.3.0",
        digest=validate_task_type_spec(spec),
    )
    committed = render_task_type_snapshot_json([])
    live = render_task_type_snapshot_json([task_type_snapshot_entry(live_record)])

    detail = describe_task_type_snapshot_drift(
        committed, live, registry=_registry(live_record)
    )

    assert "`incident` is not in the committed snapshot" in detail
    assert "sase-linear 0.3.0 installed" in detail
