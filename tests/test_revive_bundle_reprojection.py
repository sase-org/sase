"""Revive marks dismissed bundles visible so projection stops re-hiding agents.

Regression coverage for the bug where reviving an agent left its dismissed
bundle contributing to the hidden projection. The artifact-index dismissed
projection is the in-memory dismissed set unioned with hidden bundle summaries,
so a revived bundle must stay historically present while no longer projecting
as hidden (``sase agent index gc`` / cold-start maintenance /
drift-triggered sync).
"""

from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    load_dismissed_agents,
    load_dismissed_bundle_summaries,
    mark_bundles_revived_by_suffixes,
    purge_revived_dismissed_bundles,
    save_dismissed_bundle,
    verify_dismissed_bundle_index,
)
from sase.ace.dismissed_bundle_index import query_summaries
from sase.core.agent_artifact_index_lifecycle import (
    build_dismissed_agent_projection_inputs,
)
from sase.main.parser import create_parser

from sase.ace.tui.models.agent import Agent

from tests._agent_revive_helpers import FakeReviveApp
from tests._agent_revive_helpers import make_agent as make_revive_agent
from tests._dismissed_agents_helpers import make_agent as make_dismiss_agent


def _patch_archive(tmp_path: Path) -> ExitStack:
    """Point dismissed-bundle + dismissed-identity storage at *tmp_path*."""
    stack = ExitStack()
    stack.enter_context(
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path / "bundles")
    )
    stack.enter_context(
        patch(
            "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
            tmp_path / "dismissed_agents.json",
        )
    )
    stack.enter_context(
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json")
    )
    return stack


def _projection_suffixes() -> set[str]:
    projection = build_dismissed_agent_projection_inputs()
    return {row.raw_suffix for row in projection.identities if row.raw_suffix}


def test_mark_bundles_revived_marks_visibility_projection(
    tmp_path: Path,
) -> None:
    """Revive hides the bundle from dismissed views without mutating bytes."""
    with _patch_archive(tmp_path):
        agent = make_dismiss_agent(cl_name="revived", raw_suffix="20260101120000")
        assert save_dismissed_bundle(agent)

        # Precondition: bundle is indexed and feeds the dismissed projection.
        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"})
        assert "20260101120000" in _projection_suffixes()

        removed = mark_bundles_revived_by_suffixes({"20260101120000"})

        assert removed == 1
        bundles_dir = tmp_path / "bundles"
        assert list(bundles_dir.rglob("*.json"))
        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"}) == []
        [summary] = (
            query_summaries(
                bundles_dir,
                suffixes={"20260101120000"},
                visibility=None,
            )
            or []
        )
        assert summary.archive_visibility == "visible"
        assert summary.times_revived == 1
        report = verify_dismissed_bundle_index()
        assert report["ok"] is True
        assert "20260101120000" not in _projection_suffixes()


def test_mark_bundles_revived_is_noop_for_empty_suffixes(tmp_path: Path) -> None:
    """An empty suffix set removes nothing and leaves the index untouched."""
    with _patch_archive(tmp_path):
        agent = make_dismiss_agent(cl_name="keep", raw_suffix="20260101120000")
        assert save_dismissed_bundle(agent)

        assert mark_bundles_revived_by_suffixes(set()) == 0
        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"})


def test_revive_flow_marks_bundle_visible_so_projection_rebuild_keeps_agent_visible(
    tmp_path: Path,
) -> None:
    """End-to-end: after revive a projection rebuild does not re-hide the agent."""
    with _patch_archive(tmp_path), ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.actions.agents._revive."
                "sync_dismissed_agent_artifact_index"
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.actions.agents._revive."
                "upsert_agent_artifact_index_artifacts"
            )
        )

        agent = make_revive_agent(cl_name="revived", raw_suffix="20260101120000")
        # Dismiss: persist both the identity and the bundle, as the dismiss flow
        # does.
        assert save_dismissed_bundle(agent)
        _write_dismissed_json(tmp_path, [agent])
        assert agent.identity in load_dismissed_agents()

        app = FakeReviveApp()
        app._agents = [agent]
        app._dismissed_agent_objects = [agent]
        app._dismissed_agents = {agent.identity}

        app._do_revive_agent(agent)

        # The dismissed identity is gone and the bundle summary is visible, so
        # the rebuilt projection (what gc / cold start derive) no longer
        # contains the revived agent.
        assert load_dismissed_agents() == set()
        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"}) == []
        [summary] = (
            query_summaries(
                tmp_path / "bundles",
                suffixes={"20260101120000"},
                visibility=None,
            )
            or []
        )
        assert summary.archive_visibility == "visible"
        assert verify_dismissed_bundle_index()["ok"] is True
        assert "20260101120000" not in _projection_suffixes()


def test_revive_marks_nested_child_bundles_visible(tmp_path: Path) -> None:
    """Reviving a parent marks its restored children's bundles visible too."""
    with _patch_archive(tmp_path), ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.actions.agents._revive."
                "sync_dismissed_agent_artifact_index"
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.actions.agents._revive."
                "upsert_agent_artifact_index_artifacts"
            )
        )

        parent = make_revive_agent(
            cl_name="feature",
            raw_suffix="20260101120000",
            workflow=None,
        )
        # Follow-up child: distinct suffix, linked via parent_timestamp.
        child = make_revive_agent(
            cl_name="feature.code",
            raw_suffix="20260101130000",
            workflow=None,
            parent_workflow=None,
            parent_timestamp="20260101120000",
            step_index=0,
        )
        assert save_dismissed_bundle(parent)
        assert save_dismissed_bundle(child)
        _write_dismissed_json(tmp_path, [parent, child])

        app = FakeReviveApp()
        app._agents = [parent]
        app._dismissed_agent_objects = [parent, child]
        app._dismissed_agents = {parent.identity, child.identity}

        app._do_revive_agent(parent)

        assert (
            load_dismissed_bundle_summaries(
                suffixes={"20260101120000", "20260101130000"}
            )
            == []
        )
        summaries = (
            query_summaries(
                tmp_path / "bundles",
                suffixes={"20260101120000", "20260101130000"},
                visibility=None,
            )
            or []
        )
        assert {summary.raw_suffix for summary in summaries} == {
            "20260101120000",
            "20260101130000",
        }
        assert {summary.archive_visibility for summary in summaries} == {"visible"}
        assert verify_dismissed_bundle_index()["ok"] is True
        rebuilt = _projection_suffixes()
        assert "20260101120000" not in rebuilt
        assert "20260101130000" not in rebuilt


def test_purge_revived_dismissed_bundles_marks_only_orphans_visible(
    tmp_path: Path,
) -> None:
    """Reconciliation marks bundles absent from the dismissed identity file."""
    with _patch_archive(tmp_path):
        kept = make_dismiss_agent(cl_name="kept", raw_suffix="20260101130000")
        orphan = make_dismiss_agent(cl_name="orphan", raw_suffix="20260101120000")
        assert save_dismissed_bundle(kept)
        assert save_dismissed_bundle(orphan)
        # Only ``kept`` is still dismissed; ``orphan`` was revived earlier and
        # its bundle lingered.
        _write_dismissed_json(tmp_path, [kept])

        purged = purge_revived_dismissed_bundles()

        assert purged == 1
        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"}) == []
        assert load_dismissed_bundle_summaries(suffixes={"20260101130000"})
        [orphan_summary] = (
            query_summaries(
                tmp_path / "bundles",
                suffixes={"20260101120000"},
                visibility=None,
            )
            or []
        )
        assert orphan_summary.archive_visibility == "visible"
        assert verify_dismissed_bundle_index()["ok"] is True
        rebuilt = _projection_suffixes()
        assert "20260101120000" not in rebuilt
        assert "20260101130000" in rebuilt


def test_index_gc_parser_accepts_purge_revived_bundles_flag() -> None:
    """`sase agent index gc -r` toggles the revived-bundle purge."""
    args = create_parser().parse_args(
        ["agent", "index", "gc", "--purge-revived-bundles"]
    )
    assert args.index_subcommand == "gc"
    assert args.purge_revived_bundles is True

    short = create_parser().parse_args(["agent", "index", "gc", "-r"])
    assert short.purge_revived_bundles is True

    default = create_parser().parse_args(["agent", "index", "gc"])
    assert default.purge_revived_bundles is False


def test_index_gc_purges_revived_bundles_before_rebuild(
    tmp_path: Path,
) -> None:
    """`gc --purge-revived-bundles` marks orphan bundles visible before rebuild."""
    from sase.agents.cli_index import handle_agents_index
    from sase.core.agent_scan_wire import (
        AgentArtifactIndexUpdateWire,
        AgentArtifactIndexVerifyWire,
    )

    with _patch_archive(tmp_path):
        orphan = make_dismiss_agent(cl_name="orphan", raw_suffix="20260101120000")
        assert save_dismissed_bundle(orphan)
        _write_dismissed_json(tmp_path, [])

        args = argparse.Namespace(
            index_subcommand="gc",
            index_path=str(tmp_path / "index.sqlite"),
            projects_root=str(tmp_path / "projects"),
            json=True,
            purge_revived_bundles=True,
        )

        verify_wire = AgentArtifactIndexVerifyWire(
            ok=True,
            schema_version=1,
            index_path=str(tmp_path / "index.sqlite"),
            projects_root=str(tmp_path / "projects"),
            indexed_rows=0,
            source_rows=0,
        )
        update_wire = AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(tmp_path / "index.sqlite"),
            projects_root=str(tmp_path / "projects"),
            rows_indexed=0,
        )
        with (
            patch(
                "sase.agents.cli_index.verify_agent_artifact_index",
                return_value=verify_wire,
            ),
            patch(
                "sase.agents.cli_index.rebuild_agent_artifact_index",
                return_value=update_wire,
            ),
            patch(
                "sase.agents.cli_index._load_dismissed_identities_for_gc",
                return_value=([], 0),
            ),
            patch(
                "sase.agents.cli_index.replace_agent_artifact_index_dismissed_agents",
                return_value=update_wire,
            ),
        ):
            handle_agents_index(args)

        assert load_dismissed_bundle_summaries(suffixes={"20260101120000"}) == []


def _write_dismissed_json(tmp_path: Path, agents: list[Agent]) -> None:
    """Write the legacy ``dismissed_agents.json`` for *agents*' identities."""
    entries = [
        [agent.identity[0].value, agent.identity[1], agent.identity[2]]
        for agent in agents
    ]
    (tmp_path / "dismissed_agents.json").write_text(json.dumps(entries))
