"""Tests for local daemon read client wire contracts."""

from __future__ import annotations

from sase.daemon.client import LocalDaemonClient

from tests._daemon_read_facade_helpers import (
    FakeDaemonTransport,
    _notification_page,
)


def test_all_phase_5a_read_client_methods_emit_contract_surfaces() -> None:
    calls = [
        ("changespec_list", lambda client: client.changespec_list()),
        ("changespec_search", lambda client: client.changespec_search(query="demo")),
        (
            "changespec_detail",
            lambda client: client.changespec_detail("changespec:demo:one"),
        ),
        ("agent_active", lambda client: client.agent_active(project_id="demo")),
        ("agent_recent", lambda client: client.agent_recent(project_id="demo")),
        ("agent_archive", lambda client: client.agent_archive(project_id="demo")),
        (
            "agent_search",
            lambda client: client.agent_search(project_id="demo", query="run"),
        ),
        (
            "agent_detail",
            lambda client: client.agent_detail(project_id="demo", agent_id="run-1"),
        ),
        ("notification_list", lambda client: client.notification_list()),
        ("notification_detail", lambda client: client.notification_detail("notif-1")),
        ("notification_counts", lambda client: client.notification_counts()),
        (
            "notification_pending_actions",
            lambda client: client.notification_pending_actions(),
        ),
        ("bead_list", lambda client: client.bead_list(project_id="demo")),
        ("bead_ready", lambda client: client.bead_ready(project_id="demo")),
        ("bead_blocked", lambda client: client.bead_blocked(project_id="demo")),
        (
            "bead_show",
            lambda client: client.bead_show(project_id="demo", bead_id="demo-1"),
        ),
        ("bead_stats", lambda client: client.bead_stats(project_id="demo")),
        ("xprompt_catalog", lambda client: client.xprompt_catalog(project_id="demo")),
        ("editor_catalog", lambda client: client.editor_catalog(project_id="demo")),
        ("snippet_catalog", lambda client: client.snippet_catalog(project_id="demo")),
        ("file_history", lambda client: client.file_history(project_id="demo")),
    ]
    reads = {surface: [{}] for surface, _call in calls}
    transport = FakeDaemonTransport(reads=reads)
    client = LocalDaemonClient(transport=transport)

    for expected_surface, call in calls:
        assert call(client) == {}
        payload = transport.requests[-1]
        assert payload["type"] == "read"
        assert payload["data"]["surface"] == expected_surface


def test_unit_read_client_methods_omit_data_field_for_rust_wire_contract() -> None:
    """Unit enum read surfaces must not send an empty content payload."""

    transport = FakeDaemonTransport(
        reads={
            "notification_counts": [{}],
            "notification_pending_actions": [{}],
        }
    )
    client = LocalDaemonClient(transport=transport)

    assert client.notification_counts() == {}
    assert client.notification_pending_actions() == {}

    assert transport.requests[-2]["data"] == {"surface": "notification_counts"}
    assert transport.requests[-1]["data"] == {"surface": "notification_pending_actions"}


def test_notification_list_request_matches_contract_shape() -> None:
    transport = FakeDaemonTransport(
        reads={"notification_list": [_notification_page([])]}
    )
    client = LocalDaemonClient(transport=transport)

    client.notification_list(
        include_dismissed=True,
        query="plan",
        sender="mentor",
        unread=False,
        limit=7,
        cursor="cur-1",
    )

    assert transport.requests[-1] == {
        "type": "read",
        "data": {
            "surface": "notification_list",
            "data": {
                "schema_version": 1,
                "page": {"schema_version": 1, "limit": 7, "cursor": "cur-1"},
                "include_dismissed": True,
                "query": "plan",
                "sender": "mentor",
                "unread": False,
            },
        },
    }


def test_iter_read_items_follows_next_cursor() -> None:
    transport = FakeDaemonTransport(
        reads={
            "notification_list": [
                _notification_page([{"id": "one"}], next_cursor="cur-2"),
                _notification_page([{"id": "two"}]),
            ]
        }
    )
    client = LocalDaemonClient(transport=transport)

    items = list(
        client.iter_read_items(
            "notification_list",
            lambda cursor: {
                "schema_version": 1,
                "page": {"schema_version": 1, "limit": 1, "cursor": cursor},
            },
            items_key="notifications",
        )
    )

    assert [item["id"] for item in items] == ["one", "two"]
    cursors = [
        request["data"]["data"]["page"]["cursor"] for request in transport.requests
    ]
    assert cursors == [None, "cur-2"]
