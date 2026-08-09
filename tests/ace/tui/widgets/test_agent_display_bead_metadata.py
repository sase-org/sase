"""Tests for agent display bead metadata.

The TUI shows ``Bead:`` only when a candidate bead id has been *confirmed* to
exist in a bead store (cached as a display string). Cold (unchecked) and
missing candidates render nothing; confirmation happens off the event loop via
``resolve_bead_display``.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_bead as agent_bead_model
from sase.ace.tui.models.agent_bead import (
    BEAD_DISPLAY_CACHE_MISS,
    _BEAD_DISPLAY_CACHE,
    _BeadDisplayCache,
    _bead_display_cache_key,
    agent_has_confirmed_bead,
    cached_bead_display,
    resolve_bead_display,
    should_resolve_bead_display,
)
from sase.agent.bead_display import derive_agent_bead_id_from_name
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
)
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_metadata_prefix,
)


@pytest.fixture(autouse=True)
def _clear_bead_display_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    # This module exercises the generic confirmed-bead compatibility path.
    # Keep role-aware plan association out of scope so ambient project beads
    # cannot reclassify a dotted compatibility candidate as a phase worker.
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda *_args, **_kwargs: None,
    )
    _BEAD_DISPLAY_CACHE.clear()
    yield
    _BEAD_DISPLAY_CACHE.clear()


def _confirm(agent, issue: Issue, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warm the confirmation cache with *issue* for *agent*."""
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: issue,
    )
    resolve_bead_display(agent)


def _full_header(agent):
    return build_header_text(
        agent,
        cheap=False,
        summary=build_detail_header_summary(agent),
    )


def _install_expired_cache(
    agent,
    value: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _BeadDisplayCache(ttl_seconds=60.0, max_entries=16)
    key = _bead_display_cache_key(agent)
    assert key is not None
    cache._entries[key] = (-1.0, value)
    monkeypatch.setattr(agent_bead_model, "_BEAD_DISPLAY_CACHE", cache)


class TestConfirmedBeadMetadata:
    """Confirmed candidates render ``Bead:`` with id/description/title."""

    def test_bead_rows_are_first_metadata_rows_in_cheap_and_full_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        # Cold cache: cheap header omits the Bead row entirely.
        cheap_header, _ = build_header_text(agent, cheap=True)
        assert cheap_header.plain.splitlines()[0] == "Name: sase-x.3"
        assert "Bead:" not in cheap_header.plain

        _confirm(
            agent,
            Issue(id="sase-x.3", title="Phase title", description="First line"),
            monkeypatch,
        )
        full_header, _ = _full_header(agent)
        assert_metadata_prefix(
            full_header,
            "Name: sase-x.3",
            "Bead: sase-x.3 - First line",
        )

    def test_phase_agent_name_renders_confirmed_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        assert derive_agent_bead_id_from_name(agent.agent_name) == "sase-x.3"

        _confirm(agent, Issue(id="sase-x.3", title="", description=""), monkeypatch)
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_confirmed_issue_without_description_or_title_renders_just_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        _confirm(
            agent,
            Issue(id="sase-x.3", title=" \n\t ", description=" \n\t "),
            monkeypatch,
        )
        assert cached_bead_display(agent) == "sase-x.3"
        header, _ = _full_header(agent)

        assert "Name: sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_land_agent_name_renders_confirmed_epic_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")
        assert derive_agent_bead_id_from_name(agent.agent_name) == "sase-x"

        _confirm(agent, Issue(id="sase-x", title="", description=""), monkeypatch)
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: sase-x.land\nBead: sase-x\n" in header.plain

    def test_exact_epic_agent_name_renders_confirmed_epic_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x")
        assert derive_agent_bead_id_from_name(agent.agent_name) == "sase-x"

        _confirm(agent, Issue(id="sase-x", title="", description=""), monkeypatch)
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: sase-x\nBead: sase-x\n" in header.plain

    def test_dismissed_phase_agent_name_uses_underlying_confirmed_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")
        assert derive_agent_bead_id_from_name(agent.agent_name) == "sase-x.3"

        _confirm(agent, Issue(id="sase-x.3", title="", description=""), monkeypatch)
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: 260428.sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_full_header_renders_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        _confirm(
            agent,
            Issue(
                id="sase-x.3",
                title="Phase title",
                description="First line\n\n second\tline ",
            ),
            monkeypatch,
        )
        header, _ = _full_header(agent)

        assert "Name: sase-x.3\nBead: sase-x.3 - First line second line\n" in (
            header.plain
        )

    def test_full_header_uses_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        _confirm(
            agent,
            Issue(id="sase-x.3", title="Phase title", description=" \n\t "),
            monkeypatch,
        )
        header, _ = _full_header(agent)

        assert "Name: sase-x.3\nBead: sase-x.3 - Phase title\n" in header.plain

    def test_full_land_header_uses_plan_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")

        _confirm(
            agent,
            Issue(
                id="sase-x",
                title=" Make `sase bead` Fast With `sase-core` ",
                description=" \n\t ",
            ),
            monkeypatch,
        )
        header, _ = _full_header(agent)

        assert (
            "Name: sase-x.land\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_exact_land_header_uses_epic_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x")

        _confirm(
            agent,
            Issue(
                id="sase-x",
                title=" Make `sase bead` Fast With `sase-core` ",
                issue_type=IssueType.PLAN,
                tier=BeadTier.EPIC,
                description=" \n\t ",
            ),
            monkeypatch,
        )
        header, _ = _full_header(agent)

        assert (
            "Name: sase-x\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_land_header_prefers_explicit_plan_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")

        _confirm(
            agent,
            Issue(
                id="sase-x",
                title="Plan title",
                description="Use the explicit plan description",
            ),
            monkeypatch,
        )
        header, _ = _full_header(agent)

        assert (
            "Name: sase-x.land\nBead: sase-x - Use the explicit plan description\n"
        ) in header.plain

    def test_full_header_passes_agent_project_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(
            agent_name="zorg-4.3.6",
            project_file="/home/me/.sase/projects/zorg/zorg.sase",
        )
        seen_project_names: list[str | None] = []

        def lookup(
            bead_id: str,
            *,
            project_name: str | None = None,
            workspace_dir: str | None = None,
            **_: object,
        ) -> Issue | None:
            del workspace_dir
            seen_project_names.append(project_name)
            return Issue(
                id=bead_id,
                title="Phase 6: count() MVP And Final Epic Hardening",
                description="",
            )

        monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", lookup)

        resolve_bead_display(agent)
        header, _ = _full_header(agent)

        assert seen_project_names == ["zorg"]
        assert (
            "Name: zorg-4.3.6\n"
            "Bead: zorg-4.3.6 - Phase 6: count() MVP And Final Epic Hardening\n"
        ) in header.plain

    def test_full_header_uses_agent_workspace_before_project_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = tmp_path / "sase"
        agent_workspace = tmp_path / "bob-cli"
        project_dir = tmp_path / ".sase" / "projects" / "home"
        (current / "sdd/beads").mkdir(parents=True)
        (agent_workspace / "sdd/beads").mkdir(parents=True)
        project_dir.mkdir(parents=True)
        _write_issues(
            current / "sdd/beads",
            [
                _issue(
                    "bob-cli-1.4",
                    "Wrong current project title",
                    "2026-06-01T00:00:00Z",
                )
            ],
        )
        _write_issues(
            agent_workspace / "sdd/beads",
            [
                _issue(
                    "bob-cli-1.4",
                    "Workspace phase title",
                    "2026-06-01T00:00:01Z",
                )
            ],
        )
        monkeypatch.chdir(current)
        agent = make_agent(
            agent_name="bob-cli-1.4",
            project_file=str(project_dir / "home.sase"),
            workspace_dir=str(agent_workspace),
        )

        resolve_bead_display(agent)
        header, _ = _full_header(agent)

        assert (
            "Name: bob-cli-1.4\nBead: bob-cli-1.4 - Workspace phase title\n"
        ) in header.plain

    def test_expired_confirmed_bead_stays_visible_and_requests_revalidation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _install_expired_cache(agent, "sase-x.3 - stale description", monkeypatch)

        assert cached_bead_display(agent) == "sase-x.3 - stale description"
        assert agent_has_confirmed_bead(agent) is True
        assert should_resolve_bead_display(agent) is True

        cheap_header, _ = build_header_text(agent, cheap=True)
        full_header, _ = _full_header(agent)

        assert_metadata_prefix(
            cheap_header,
            "Name: sase-x.3",
            "Bead: sase-x.3 - stale description",
        )
        assert_metadata_prefix(
            full_header,
            "Name: sase-x.3",
            "Bead: sase-x.3 - stale description",
        )

    def test_reresolve_same_confirmed_bead_refreshes_expired_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _install_expired_cache(agent, "sase-x.3 - First line", monkeypatch)
        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description="First line",
            ),
        )

        assert should_resolve_bead_display(agent) is True
        assert resolve_bead_display(agent) == "sase-x.3 - First line"

        assert cached_bead_display(agent) == "sase-x.3 - First line"
        assert should_resolve_bead_display(agent) is False

    def test_reresolve_deleted_bead_removes_confirmed_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _install_expired_cache(agent, "sase-x.3 - stale description", monkeypatch)
        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda bead_id, **_: None,
        )

        assert agent_has_confirmed_bead(agent) is True
        assert resolve_bead_display(agent) is None

        assert cached_bead_display(agent) is None
        assert agent_has_confirmed_bead(agent) is False
        assert should_resolve_bead_display(agent) is False
        cheap_header, _ = build_header_text(agent, cheap=True)
        full_header, _ = _full_header(agent)
        assert "Bead:" not in cheap_header.plain
        assert "Bead:" not in full_header.plain


class TestUnconfirmedBeadMetadata:
    """Cold and missing candidates render no ``Bead:`` row."""

    def test_cheap_cold_header_omits_bead_and_does_not_touch_storage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        def fail_lookup(bead_id: str, **_: object) -> Issue | None:
            raise AssertionError("cheap header must not touch bead storage")

        monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", fail_lookup)

        header, _ = build_header_text(agent, cheap=True)

        assert "Name: sase-x.3\n" in header.plain
        assert "Bead:" not in header.plain

    def test_cold_full_header_omits_bead_and_does_not_touch_storage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        def fail_lookup(bead_id: str, **_: object) -> Issue | None:
            raise AssertionError("cold full header must not touch bead storage")

        monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", fail_lookup)

        header, _ = _full_header(agent)

        assert "Name: sase-x.3\n" in header.plain
        assert "Bead:" not in header.plain

    def test_missing_bead_caches_none_and_headers_omit_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda bead_id, **_: None,
        )

        assert resolve_bead_display(agent) is None
        assert cached_bead_display(agent) is None

        cheap_header, _ = build_header_text(agent, cheap=True)
        full_header, _ = _full_header(agent)

        assert "Bead:" not in cheap_header.plain
        assert "Bead:" not in full_header.plain

    def test_unconfirmed_candidate_in_other_project_omits_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        alpha = make_agent(
            agent_name="shared-1.2",
            project_file="/home/me/.sase/projects/alpha/alpha.sase",
        )
        beta = make_agent(
            agent_name="shared-1.2",
            project_file="/home/me/.sase/projects/beta/beta.sase",
        )
        seen_project_names: list[str | None] = []

        def lookup(
            bead_id: str,
            *,
            project_name: str | None = None,
            workspace_dir: str | None = None,
            **_: object,
        ) -> Issue | None:
            del workspace_dir
            seen_project_names.append(project_name)
            return Issue(
                id=bead_id,
                title=f"{project_name} title",
                description=f"{project_name} description",
            )

        monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", lookup)

        assert resolve_bead_display(alpha) == "shared-1.2 - alpha description"
        assert cached_bead_display(beta) is BEAD_DISPLAY_CACHE_MISS
        assert should_resolve_bead_display(beta) is True

        header, _ = _full_header(beta)

        # beta's candidate is unconfirmed (its project cache key is a miss); the
        # cold full header reads cache only, so it neither looks up nor renders.
        assert "Bead:" not in header.plain
        assert "alpha description" not in header.plain
        assert seen_project_names == ["alpha"]

    def test_ordinary_agent_name_omits_bead(self) -> None:
        agent = make_agent(agent_name="reviewer")

        assert derive_agent_bead_id_from_name(agent.agent_name) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: reviewer\n" in header.plain
        assert "Bead:" not in header.plain

    def test_dotted_ordinary_agent_name_omits_bead(self) -> None:
        agent = make_agent(agent_name="aij.2")

        assert derive_agent_bead_id_from_name(agent.agent_name) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: aij.2\n" in header.plain
        assert "Bead:" not in header.plain


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _issue(issue_id: str, title: str, updated_at: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": updated_at,
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "patch_name": "",
        "patch_bug_id": "",
        "dependencies": [],
    }
