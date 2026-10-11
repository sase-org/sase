"""Tests for the suggest human and JSON renderers."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sase.project_onboarding.render import print_suggest, render_suggest_json


def _row(display: str, group: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identity_key": f"k/{display}",
        "ref": display,
        "display": display,
        "group": group,
        "description": "",
        "visibility": "",
        "linked_by": [],
    }
    payload.update(overrides)
    return payload


def _provider(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow_type": "gh",
        "display": "GitHub",
        "account": "bbugyi200",
        "owners": [],
        "groups": [],
        "hidden": [],
    }
    payload.update(overrides)
    return payload


def _rendered(
    payload: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    *,
    include_hidden: bool = False,
) -> str:
    print_suggest(payload, include_hidden=include_hidden)
    return capsys.readouterr().out


class TestHumanRendering:
    def test_group_sections_use_tui_glyphs_in_order(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    groups=[
                        {"id": "disabled", "rows": [_row("o/old", "disabled")]},
                        {"id": "suggested", "rows": [_row("o/new", "suggested")]},
                        {"id": "local", "rows": [_row("o/clone", "local")]},
                    ]
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert text.index("ON THIS MACHINE") < text.index("SUGGESTED")
        assert text.index("SUGGESTED") < text.index("DISABLED PROJECTS")
        assert "⌂ o/clone" in text
        assert "○ o/new" in text
        assert "◐ o/old" in text
        assert "Add one with: sase project add REF" in text

    def test_hidden_footer_counts_and_labels(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    hidden=[
                        {"reason": "sidecar", "count": 26},
                        {"reason": "fork", "count": 1},
                    ]
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert "┄ 26 sidecars · 1 fork hidden — use --all" in text

    def test_include_hidden_shows_search_only_without_footer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    hidden=[{"reason": "fork", "count": 1}],
                    search_only=[
                        {**_row("o/forked", "suggested"), "hidden_reason": "fork"}
                    ],
                )
            ],
        }

        text = _rendered(payload, capsys, include_hidden=True)

        assert "HIDDEN" in text
        assert "o/forked — fork" in text
        assert "use --all" not in text

    def test_owner_error_carries_remedy_and_stale_note(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    account="",
                    owners=[
                        {
                            "name": "sase-org",
                            "kind_label": "org",
                            "status": "error",
                            "error_kind": "auth",
                            "message": "gh auth expired",
                            "stale": True,
                            "host": "",
                            "truncated": False,
                            "entry_count": 2,
                            "remedy_argv": ["gh", "auth", "login"],
                        }
                    ],
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert "⚠ sase-org: gh auth expired" in text
        assert "run: gh auth login" in text
        assert "(showing cached rows)" in text

    def test_truncation_note_names_owner(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    owners=[
                        {
                            "name": "sase-org",
                            "kind_label": "org",
                            "status": "ok",
                            "error_kind": "",
                            "message": "",
                            "stale": False,
                            "host": "",
                            "truncated": True,
                            "entry_count": 200,
                            "remedy_argv": [],
                        }
                    ],
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert "showing 200 · results truncated — narrow with --owner sase-org" in text

    def test_empty_provider_names_config_center(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"schema_version": 1, "providers": [_provider()]}

        text = _rendered(payload, capsys)

        assert "○ no owners yet" in text
        assert "github_orgs" in text
        assert "Add one with:" not in text

    def test_no_providers_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        text = _rendered({"schema_version": 1, "providers": []}, capsys)

        assert text.strip() == "No workspace providers available."

    def test_untrusted_text_renders_literally(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    groups=[
                        {
                            "id": "suggested",
                            "rows": [
                                _row(
                                    "o/new",
                                    "suggested",
                                    description="nice\x01 [red]not markup[/red]",
                                )
                            ],
                        }
                    ]
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert "\x01" not in text
        assert "[red]not markup[/red]" in text

    def test_row_meta_joins_facts(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload = {
            "schema_version": 1,
            "providers": [
                _provider(
                    groups=[
                        {
                            "id": "suggested",
                            "rows": [
                                _row(
                                    "o/new",
                                    "suggested",
                                    visibility="private",
                                    description="Plugins Monorepo",
                                    viewer_permission="WRITE",
                                )
                            ],
                        }
                    ]
                )
            ],
        }

        text = _rendered(payload, capsys)

        assert "private · Plugins Monorepo · you can push" in text


class TestJsonRendering:
    def test_json_round_trip(self) -> None:
        payload = {
            "schema_version": 1,
            "providers": [_provider(owners=[{"name": "sase-org"}])],
        }

        assert json.loads(render_suggest_json(payload)) == payload
