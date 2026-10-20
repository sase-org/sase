"""release watch health issues tests."""

from __future__ import annotations

from typing import Any

from _release_watch_health_test_helpers import (
    CORE_REPO,
    REPO,
    ReleaseHealthReader,
    ScriptedGithub,
    make_facts,
    make_health,
    flat,
    transport_error,
)


def issue_row(
    number: int = 3,
    *,
    title: str = "release-steward: install_broken (linux)",
    state: str = "open",
    body: str = "<!-- release-steward:family=install_broken identity=linux -->",
    labels: list[str] | None = None,
    opened: str = "2026-10-18T10:00:00Z",
    updated: str = "2026-10-19T10:00:00Z",
    closed: str | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": body,
        "labels": [{"name": name} for name in (labels or ["release-steward"])],
        "created_at": opened,
        "updated_at": updated,
        "closed_at": closed,
    }


def issues_world(
    issues: list[dict[str, Any]],
    comments: dict[int, list[dict[str, Any]]] | None = None,
) -> ScriptedGithub:
    listings: dict[str, Any] = {f"repos/{REPO}/issues": flat(issues)}
    for issue in issues:
        number = issue["number"]
        listings[f"repos/{REPO}/issues/{number}/comments"] = flat(
            (comments or {}).get(number, [])
        )
    return ScriptedGithub(REPO, reads={}, listings=listings)


def comment_row(body: str, created: str) -> dict[str, Any]:
    return {"body": body, "created_at": created}


def test_issues_parse_markers_comments_and_closed_history() -> None:
    body = "<!-- release-steward:family=install_broken identity=linux sha=abc -->"
    world = issues_world(
        [
            issue_row(3, body=body),
            issue_row(
                4,
                title="release-steward: install_broken (linux)",
                state="closed",
                body="no marker here",
                closed="2026-10-17T10:00:00Z",
            ),
        ],
        comments={
            3: [
                comment_row(
                    "<!-- release-steward:tick=run-1/1 --> +1", "2026-10-18T11:00:00Z"
                )
            ]
        },
    )
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    issues = health.read_issues()
    assert [issue["number"] for issue in issues] == [3, 4]
    assert issues[0]["identity_marker"] == "release-steward:install_broken:linux"
    assert issues[0]["sha"] == "abc"
    assert issues[0]["comments"] == [
        {"tick_identity": "run-1/1", "created_at": "2026-10-18T11:00:00Z"}
    ]
    assert issues[1]["family"] == "install_broken"
    assert issues[1]["identity_marker"] == "release-steward:install_broken:linux"
    assert issues[1]["closed_at"] == "2026-10-17T10:00:00Z"


def test_issues_without_markers_are_unknown() -> None:
    world = issues_world(
        [issue_row(5, title="Some random bug report", body="nothing machine-readable")]
    )
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    issues = health.read_issues()
    assert issues[0]["family"] == "unknown"
    assert issues[0]["identity_marker"] == ""


def test_issues_skip_pull_requests() -> None:
    row = issue_row(6)
    row["pull_request"] = {"url": "https://example.test/pr/6"}
    world = issues_world([row])
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    assert health.read_issues() == []


def test_lineage_names_oldest_open_marker() -> None:
    issues = [
        {
            "state": "open",
            "family": "core_lag",
            "identity_marker": "m:core_lag:x",
            "opened_at": "2026-10-17T10:00:00Z",
            "number": 8,
        },
        {
            "state": "open",
            "family": "install_broken",
            "identity_marker": "release-steward:install_broken:linux",
            "opened_at": "2026-10-16T10:00:00Z",
            "number": 7,
        },
        {
            "state": "closed",
            "family": "gate_red",
            "identity_marker": "release-steward:gate_red:y",
            "opened_at": "2026-10-10T10:00:00Z",
            "number": 2,
        },
    ]
    lineage = ReleaseHealthReader.derive_blocker_lineage(issues)
    assert lineage == {
        "family": "install_broken",
        "identity": "linux",
        "started_at": "2026-10-16T10:00:00Z",
        "continuous": True,
        "identity_changed": False,
    }
    assert ReleaseHealthReader.derive_blocker_lineage([]) is None


def test_access_probe_reports_read_only_scope() -> None:
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/actions/runs": {"total_count": 1, "workflow_runs": []}
        },
    )
    sase = ScriptedGithub(REPO, reads={})
    access = make_health(make_facts(sase), core).read_core_actions_access()
    assert access["readable"] is True
    assert "dispatch" in access["detail"]
    assert "write" not in access["detail"].lower().replace("workflow-dispatch", "")


def test_access_probe_failure_is_denied_not_unreadable() -> None:
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/actions/runs": transport_error(
                "actions/runs", "HTTP 403"
            )
        },
    )
    sase = ScriptedGithub(REPO, reads={})
    access = make_health(make_facts(sase), core).read_core_actions_access()
    assert access == {"readable": False, "detail": access["detail"]}
    assert access["detail"]
