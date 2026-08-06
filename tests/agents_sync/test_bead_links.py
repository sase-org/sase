from __future__ import annotations

import pytest

from sase.agents_sync.bead_links import (
    BeadPageLink,
    _resolve_links,
    _select_bead_source,
)
from sase.agents_sync.v2_models import V2HoodSnapshot, V2ProjectIdentity, V2RunRecord
from sase.core.agent_identity_facade import AgentOwnerIdentity


class _FakeResolver:
    """Duck-typed stand-in for ``HostedLinkResolver.bead_url``."""

    def __init__(self, urls: dict[str, str]) -> None:
        self._urls = urls

    def bead_url(self, bead_id: str) -> str | None:
        from sase.bead_pages.paths import bead_page_path

        try:
            bead_page_path(bead_id)
        except ValueError:
            return None
        return self._urls.get(bead_id)


def _snapshot(*runs: V2RunRecord) -> V2HoodSnapshot:
    owner = AgentOwnerIdentity("alice", "athena")
    return V2HoodSnapshot(
        owner,
        V2ProjectIdentity("proj", "Project"),
        "foo",
        "alice.athena.foo",
        ("alice.athena.foo",),
        runs,
    )


def _run(
    local_name: str,
    *,
    metadata: tuple[tuple[str, object], ...] = (),
) -> V2RunRecord:
    return V2RunRecord(
        f"run-{local_name}",
        local_name,
        f"alice.athena.{local_name}",
        "completed",
        metadata=metadata,
    )


def test_metadata_source_links() -> None:
    run = _run("foo", metadata=(("bead_id", "sase-ar.6"),))
    resolver = _FakeResolver({"sase-ar.6": "https://example/beads/sase-ar.6"})

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    assert links["alice.athena.foo"] == BeadPageLink(
        "sase-ar.6", "https://example/beads/sase-ar.6"
    )


def test_metadata_source_with_unresolvable_url_yields_unlinked_row() -> None:
    run = _run("foo", metadata=(("bead_id", "sase-ar.6"),))
    resolver = _FakeResolver({})

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    assert links["alice.athena.foo"] == BeadPageLink("sase-ar.6", None)


def test_metadata_bead_id_that_fails_page_path_yields_unlinked_row_not_raise() -> None:
    run = _run("foo", metadata=(("bead_id", "bad/id"),))
    resolver = _FakeResolver({"bad/id": "https://example/should-not-be-used"})

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    assert links["alice.athena.foo"] == BeadPageLink("bad/id", None)


def test_name_derived_candidate_confirmed_in_store_links() -> None:
    run = _run("sase-ar.6")
    resolver = _FakeResolver({"sase-ar.6": "https://example/beads/sase-ar.6"})

    links = _resolve_links(
        (_snapshot(run),),
        resolver=resolver,
        known_bead_ids=frozenset({"sase-ar.6"}),
    )

    assert links["alice.athena.sase-ar.6"] == BeadPageLink(
        "sase-ar.6", "https://example/beads/sase-ar.6"
    )


@pytest.mark.parametrize(
    "local_name",
    ["sase_fix_just-g", "gha-fix-sase-org-sase-28299141485-a1"],
)
def test_name_derived_candidate_not_in_store_yields_no_row(local_name: str) -> None:
    run = _run(local_name)
    resolver = _FakeResolver({})

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    assert links == {}


def test_unreadable_store_drops_name_derived_rows_but_keeps_metadata_rows() -> None:
    metadata_run = _run("foo", metadata=(("bead_id", "sase-ar.6"),))
    name_derived_run = _run("sase-ag.1")
    resolver = _FakeResolver(
        {
            "sase-ar.6": "https://example/beads/sase-ar.6",
            "sase-ag.1": "https://example/beads/sase-ag.1",
        }
    )

    links = _resolve_links(
        (_snapshot(metadata_run, name_derived_run),),
        resolver=resolver,
        known_bead_ids=None,
    )

    assert set(links) == {"alice.athena.foo"}


def test_epic_bead_id_equal_to_bead_id_renders_no_epic() -> None:
    run = _run(
        "sase-ar.land",
        metadata=(("bead_id", "sase-ar"), ("epic_bead_id", "sase-ar")),
    )
    resolver = _FakeResolver({"sase-ar": "https://example/beads/sase-ar"})

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    link = links["alice.athena.sase-ar.land"]
    assert link.epic_bead_id is None
    assert link.epic_url is None


def test_epic_bead_id_differing_from_bead_id_renders_epic() -> None:
    run = _run(
        "sase-ar.6--code",
        metadata=(("bead_id", "sase-ar.6"), ("epic_bead_id", "sase-ar")),
    )
    resolver = _FakeResolver(
        {
            "sase-ar.6": "https://example/beads/sase-ar.6",
            "sase-ar": "https://example/beads/sase-ar",
        }
    )

    links = _resolve_links(
        (_snapshot(run),), resolver=resolver, known_bead_ids=frozenset()
    )

    link = links["alice.athena.sase-ar.6--code"]
    assert link.epic_bead_id == "sase-ar"
    assert link.epic_url == "https://example/beads/sase-ar"


@pytest.mark.parametrize(
    ("local_name", "expected"),
    [
        ("sase-ar.6--code", "sase-ar.6"),
        ("000123.sase-ar.6", "sase-ar.6"),
        ("sase-ar.land", "sase-ar"),
    ],
)
def test_select_bead_source_derives_expected_id_from_name_shapes(
    local_name: str,
    expected: str,
) -> None:
    selection = _select_bead_source(local_name, {}, frozenset({expected}))

    assert selection == (expected, False)
