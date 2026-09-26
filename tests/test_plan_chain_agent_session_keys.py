"""Canonical agent-session metadata keys and the shared accessor.

Covers the canonical-keys cutover: ``sase.plan_chain`` owns the
``agent_session*`` keys, the ``--`` separator, and the
``LEGACY_AGENT_FAMILY_*`` constants, every ``agent_meta.json`` / ``done.json``
reader resolves through one accessor, and writers emit only new spellings.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sase.agents_sync.v2_validation import V2_METADATA_FIELDS
from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
from sase.core.agent_scan_wire_agent_session_turn import (
    agent_session_shell_from_mapping,
    agent_session_turn_from_mapping,
)
from sase.core.agent_scan_wire_markers import AgentMetaWire, DoneMarkerWire
from sase.core.wire import known_field_kwargs, with_agent_session_keys
from sase.plan_chain import (
    AGENT_SESSION_KEY,
    AGENT_SESSION_PARALLEL_KEY,
    AGENT_SESSION_ROLE_KEY,
    AGENT_SESSION_SEPARATOR,
    AGENT_SESSION_TURN_KEY,
    LEGACY_AGENT_FAMILY_KEY,
    LEGACY_AGENT_FAMILY_PARALLEL_KEY,
    LEGACY_AGENT_FAMILY_ROLE_KEY,
    LEGACY_AGENT_FAMILY_SHELL_KEY,
    LEGACY_AGENT_SESSION_SHELL_KEY,
    TURN_KIND_KEY,
    agent_session_base,
    agent_session_parallel_value,
    agent_session_phase_name,
    agent_session_role_for_suffix,
    agent_session_role_value,
    agent_session_shell_value,
    agent_session_turn_value,
    agent_session_suffix_token,
    agent_session_value,
    is_agent_session_member,
    set_agent_session_fields,
    strip_legacy_agent_family_keys,
    turn_kind_value,
)

LEGACY_KEYS = (
    "agent_family",
    "agent_family_role",
    "agent_family_parallel",
    "family_shell",
    "agent_session_shell",
    "shell_kind",
)


def test_canonical_constants_match_wire_spellings() -> None:
    assert AGENT_SESSION_KEY == "agent_session"
    assert AGENT_SESSION_ROLE_KEY == "agent_session_role"
    assert AGENT_SESSION_PARALLEL_KEY == "agent_session_parallel"
    assert AGENT_SESSION_TURN_KEY == "agent_session_turn"
    assert TURN_KIND_KEY == "turn_kind"
    assert LEGACY_AGENT_SESSION_SHELL_KEY == "agent_session_shell"
    assert AGENT_SESSION_SEPARATOR == "--"
    assert LEGACY_AGENT_FAMILY_KEY == "agent_family"
    assert LEGACY_AGENT_FAMILY_ROLE_KEY == "agent_family_role"
    assert LEGACY_AGENT_FAMILY_PARALLEL_KEY == "agent_family_parallel"
    assert LEGACY_AGENT_FAMILY_SHELL_KEY == "family_shell"


def test_accessors_read_new_keys() -> None:
    meta = {
        "agent_session": "acme",
        "agent_session_role": "code",
        "agent_session_parallel": True,
        "agent_session_turn": {"kind": "monitor"},
        "turn_kind": "monitor",
    }
    assert agent_session_value(meta) == "acme"
    assert agent_session_role_value(meta) == "code"
    assert agent_session_parallel_value(meta) is True
    assert agent_session_shell_value(meta) == {"kind": "monitor"}
    assert agent_session_turn_value(meta) == {"kind": "monitor"}
    assert turn_kind_value(meta) == "monitor"


def test_accessors_fall_back_to_legacy_keys() -> None:
    meta = {
        "agent_family": "acme",
        "agent_family_role": "code",
        "agent_family_parallel": True,
        "family_shell": {"kind": "gate"},
    }
    assert agent_session_value(meta) == "acme"
    assert agent_session_role_value(meta) == "code"
    assert agent_session_parallel_value(meta) is True
    assert agent_session_shell_value(meta) == {"kind": "gate"}
    assert agent_session_turn_value(meta) == {"kind": "gate"}
    # legacy sase-shell spelling: ``agent_session_shell`` and ``shell_kind``.
    shell_meta = {
        "agent_session_shell": {"kind": "monitor", "id": "m"},
        "shell_kind": "proc",
    }
    assert agent_session_turn_value(shell_meta) == {"kind": "monitor", "id": "m"}
    assert turn_kind_value(shell_meta) == "monitor"
    assert turn_kind_value({"turn_kind": "gate"}) == "gate"
    assert turn_kind_value({"shell_kind": "gate"}) == "gate"


def test_accessors_prefer_new_spelling_for_mixed_files() -> None:
    # legacy agent-family spelling: ``agent_family*`` keys sit beside the new ones.
    meta = {
        "agent_session": "new",
        "agent_family": "old",
        "agent_session_role": "code",
        "agent_family_role": "plan",
    }
    assert agent_session_value(meta) == "new"
    assert agent_session_role_value(meta) == "code"


def test_accessors_return_none_when_absent() -> None:
    assert agent_session_value({}) is None
    assert agent_session_role_value({}) is None
    assert agent_session_parallel_value({}) is None
    assert agent_session_shell_value({}) is None
    assert agent_session_turn_value({}) is None
    assert turn_kind_value({}) is None


def test_accessors_read_object_attributes_either_spelling() -> None:
    assert agent_session_value(SimpleNamespace(agent_session="new")) == "new"
    assert agent_session_value(SimpleNamespace(agent_session="old")) == "old"
    assert (
        agent_session_role_value(SimpleNamespace(agent_session_role="code")) == "code"
    )
    assert (
        agent_session_role_value(SimpleNamespace(agent_session_role="plan")) == "plan"
    )
    assert agent_session_value(SimpleNamespace()) is None


def test_set_agent_session_fields_writes_new_and_drops_legacy() -> None:
    meta: dict[str, object] = {
        "name": "acme--code",
        "agent_family": "acme",
        "agent_family_role": "plan",
        "agent_family_parallel": True,
        "family_shell": {"kind": "monitor"},
    }
    set_agent_session_fields(meta, session="acme", role="code")
    assert meta["agent_session"] == "acme"
    assert meta["agent_session_role"] == "code"
    for key in LEGACY_KEYS:
        assert key not in meta


def test_set_agent_session_fields_none_clears_and_strips() -> None:
    meta: dict[str, object] = {
        "agent_session": "acme",
        "agent_session_role": "code",
        "agent_family": "acme",
    }
    set_agent_session_fields(meta, role=None)
    assert "agent_session_role" not in meta
    assert meta["agent_session"] == "acme"
    assert "agent_family" not in meta


def test_strip_legacy_agent_family_keys() -> None:
    meta: dict[str, object] = {
        "agent_session": "acme",
        "agent_family": "acme",
        "agent_family_role": "code",
        "agent_family_parallel": True,
        "family_shell": {"kind": "monitor"},
    }
    assert strip_legacy_agent_family_keys(meta) is meta
    assert meta == {"agent_session": "acme"}


def test_legacy_agent_meta_resolves_through_accessors(tmp_path: Path) -> None:
    """A realistic pre-rename agent_meta.json still resolves."""
    meta = {
        "name": "acme--code",
        "workflow_name": "acme",
        "role_suffix": "--code",
        "agent_family": "acme",
        "agent_family_role": "code",
        "agent_family_parallel": True,
        "family_shell": {
            "kind": "monitor",
            "id": "mon-1",
            "state": "running",
        },
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    loaded = json.loads((tmp_path / "agent_meta.json").read_text(encoding="utf-8"))
    assert agent_session_value(loaded) == "acme"
    assert agent_session_role_value(loaded) == "code"
    assert agent_session_parallel_value(loaded) is True
    shell = agent_session_shell_from_mapping(loaded)
    assert shell is not None and shell.kind == "monitor" and shell.id == "mon-1"


def test_done_json_nested_shell_reads_either_spelling() -> None:
    legacy = {"outcome": "MONITOR", "family_shell": {"kind": "monitor", "id": "m"}}
    shell_legacy = {
        "outcome": "MONITOR",
        "agent_session_shell": {"kind": "monitor", "id": "m"},
    }
    new = {"outcome": "MONITOR", "agent_session_turn": {"kind": "monitor", "id": "m"}}
    for done_data in (legacy, shell_legacy, new):
        turn = agent_session_turn_from_mapping(done_data)
        assert turn is not None and turn.kind == "monitor" and turn.id == "m"
        # legacy alias still hydrates
        shell = agent_session_shell_from_mapping(done_data)
        assert shell is not None and shell.kind == "monitor" and shell.id == "m"
    assert agent_session_shell_value(legacy) == {"kind": "monitor", "id": "m"}
    assert agent_session_shell_value(shell_legacy) == {"kind": "monitor", "id": "m"}
    assert agent_session_turn_value(new) == {"kind": "monitor", "id": "m"}


def test_v2_manifest_allows_both_spellings() -> None:
    assert not ({"agent_session", "agent_session_role"} - V2_METADATA_FIELDS)
    # legacy agent-family spelling: pre-rename manifests stay valid.
    assert not ({"agent_family", "agent_family_role"} - V2_METADATA_FIELDS)


def test_preserved_metadata_upgrades_legacy_parallel_keys(tmp_path: Path) -> None:
    """A pre-rename parallel member keeps its identity under new keys."""
    existing = {
        "name": "acme--1",
        "agent_family": "acme",
        "agent_family_role": "code",
        "agent_family_parallel": True,
        "parent_timestamp": "20260812120000",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(existing), encoding="utf-8")
    preserved = preserved_agent_metadata(str(tmp_path))
    assert preserved["agent_session"] == "acme"
    assert preserved["agent_session_role"] == "code"
    assert preserved["agent_session_parallel"] is True
    assert preserved["parent_timestamp"] == "20260812120000"
    for key in LEGACY_KEYS:
        assert key not in preserved


def test_wire_bridge_backfills_new_spellings_for_legacy_fields() -> None:
    """Legacy-keyed markers still hydrate the renamed wire fields (bridge)."""
    legacy_meta = {
        "name": "acme--mon",
        "agent_family": "acme",
        "agent_family_role": "monitor",
        "agent_family_parallel": True,
        "family_shell": {"kind": "monitor", "id": "m"},
    }
    bridged = with_agent_session_keys(legacy_meta)
    assert bridged["agent_session"] == "acme"
    assert bridged["agent_session_role"] == "monitor"
    assert bridged["agent_session_parallel"] is True
    assert bridged["agent_session_turn"] == {"kind": "monitor", "id": "m"}
    kwargs = known_field_kwargs(AgentMetaWire, bridged)
    kwargs["agent_session_turn"] = agent_session_turn_from_mapping(bridged)
    wire = AgentMetaWire(**kwargs)
    assert wire.agent_session == "acme"
    assert wire.agent_session_role == "monitor"
    assert (
        wire.agent_session_turn is not None
        and wire.agent_session_turn.kind == "monitor"
    )
    # legacy shell spelling also bridges
    shell_bridged = with_agent_session_keys(
        {"agent_session_shell": {"kind": "gate", "id": "g"}}
    )
    assert shell_bridged["agent_session_turn"] == {"kind": "gate", "id": "g"}
    done = DoneMarkerWire(
        **known_field_kwargs(DoneMarkerWire, with_agent_session_keys({"outcome": "x"}))
    )
    assert done.outcome == "x"


def test_wire_bridge_keeps_new_spelling_authoritative() -> None:
    # legacy agent-family spelling: ``agent_family`` sits beside the new key.
    mixed = {"agent_session": "new", "agent_family": "old"}
    assert with_agent_session_keys(mixed)["agent_session"] == "new"
    new = {"agent_session": "new"}
    assert with_agent_session_keys(new) == new


def test_renamed_agent_session_helpers() -> None:
    assert agent_session_base("acme--plan") == "acme"
    assert agent_session_phase_name("acme", "--plan") == "acme--plan"
    assert agent_session_suffix_token("--plan") == "plan"
    assert is_agent_session_member("acme--plan") is True
    assert agent_session_role_for_suffix("--plan") == "plan"
