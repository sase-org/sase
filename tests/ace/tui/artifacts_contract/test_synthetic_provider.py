"""No-code schema-v1 provider fixture participates in contract compilation."""

from __future__ import annotations

from pathlib import Path

import yaml

from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui._artifact_tab_descriptors import provider_descriptors
from sase.ace.tui._artifact_tab_model import PaneCapability, ProjectProviderRecord
from sase.sidecar_ref_config import SidecarRefPolicy

from .harness import PANE_CONFORMANCE_CHECKS


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "notes"


def _load_fixture_spec() -> dict[str, object]:
    raw = yaml.safe_load((FIXTURE_DIR / "provider.yml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_synthetic_fixture_is_declarative_data_only() -> None:
    python_files = list(FIXTURE_DIR.glob("*.py"))
    assert python_files == []
    assert (FIXTURE_DIR / "provider.yml").is_file()
    assert (FIXTURE_DIR / "hello.md").is_file()
    spec = _load_fixture_spec()
    assert spec["schema_version"] == 1
    assert "class" not in spec
    assert callable(spec.get("resolve_ref")) is False


def test_synthetic_provider_earns_generic_document_capabilities() -> None:
    spec = _load_fixture_spec()
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=spec,
        provider_spec_digest="fixture",
    )
    contract = result.contract
    assert result.error is None
    assert contract.has(PaneCapability.FILTER_SESSION)
    assert contract.has(PaneCapability.QUERY_HISTORY)
    assert contract.has(PaneCapability.SAVED_QUERIES)
    assert contract.has(PaneCapability.ENTRY_NAVIGATION)
    assert contract.has(PaneCapability.REFRESH)
    assert contract.has(PaneCapability.STABLE_MARKS)
    assert contract.has(PaneCapability.DETAIL_SCROLL)
    assert contract.has(PaneCapability.PROJECT_SCOPE)
    assert contract.has(PaneCapability.STABLE_REFERENCE_COPY)
    assert contract.copy_targets == (
        "reference",
        "link",
        "path",
        "title",
        "body",
        "json",
        "handoff",
        "snapshot",
    )
    assert not contract.has(PaneCapability.MUTATION)
    assert not contract.has(PaneCapability.VERSIONS)
    assert not contract.has(PaneCapability.PLAN_APPROVE)
    assert not contract.has(PaneCapability.PLAN_REJECT)
    assert not contract.has(PaneCapability.PLAN_OPEN_BEAD)
    assert contract.has(PaneCapability.RELATIONS)
    assert [item.name for item in contract.relations] == ["bundle"]
    assert not contract.has(PaneCapability.GROUPING)


def test_synthetic_provider_compiles_through_descriptor_path() -> None:
    spec = _load_fixture_spec()
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="fixture",
                display_name="Fixture",
                workspace_dir=str(FIXTURE_DIR),
                role="notes",
                root=FIXTURE_DIR,
                policy=SidecarRefPolicy(
                    role="notes",
                    ref_kind="notes",
                    is_document=True,
                    spec=spec,
                ),
            ),
        )
    )
    assert descriptors[0].id == "ref:notes"
    assert descriptors[0].is_degraded is False
    assert descriptors[0].contract is not None
    assert descriptors[0].contract.has(PaneCapability.STABLE_REFERENCE_COPY)
    for _name, check in PANE_CONFORMANCE_CHECKS:
        check(descriptors[0])
