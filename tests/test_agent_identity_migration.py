from __future__ import annotations

import json
from pathlib import Path

from sase.agent.names import (
    AgentIdentityMigrationRequest,
    apply_historical_agent_identity_migration,
    preview_historical_agent_identity_migration,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


OLD_BEAD = "sase-ei.3"
NEW_BEAD = "sase-identity.3"
OLD_NAME = OLD_BEAD
NEW_NAME = NEW_BEAD
OLD_GLOBAL = f"alice.athena.{OLD_NAME}"
NEW_GLOBAL = f"alice.athena.{NEW_NAME}"


def test_historical_agent_identity_migration_rewrites_local_state(
    tmp_path: Path,
) -> None:
    state, artifact, old_chat = _seed_state(tmp_path)
    request = _request(state)

    preview = preview_historical_agent_identity_migration(request)

    assert preview.ok
    assert preview.changed
    assert dict(preview.local_name_map)[OLD_NAME] == NEW_NAME
    assert dict(preview.global_name_map)[OLD_GLOBAL] == NEW_GLOBAL
    assert any(action.kind == "rename" for action in preview.actions)

    result = apply_historical_agent_identity_migration(preview)

    new_chat = old_chat.with_name(old_chat.name.replace(OLD_NAME, NEW_NAME))
    meta = json.loads((artifact / "agent_meta.json").read_text())
    done = json.loads((artifact / "done.json").read_text())
    history = json.loads((state / "prompt_history" / "0001.json").read_text())
    registry = json.loads((state / "agent_name_registry.json").read_text())
    notifications = [
        json.loads(line)
        for line in (state / "notifications" / "notifications.jsonl")
        .read_text()
        .splitlines()
    ]

    assert result.idempotent
    assert meta["bead_id"] == NEW_BEAD
    assert meta["local_name"] == NEW_NAME
    assert meta["global_name"] == NEW_GLOBAL
    assert meta["chat_path"] == str(new_chat)
    assert meta["response_path"] == f"~/.sase/chats/202608/{new_chat.name}"
    assert done["agent_name"] == NEW_NAME
    assert NEW_NAME in (artifact / "raw_xprompt.md").read_text()
    assert OLD_NAME not in (artifact / "raw_xprompt.md").read_text()
    assert history["prompts"][0]["text"] == f"%id:{NEW_NAME}\n#resume:{NEW_NAME}"
    assert notifications == [{"agent_name": NEW_NAME, "bead_id": NEW_BEAD}]
    assert OLD_NAME not in registry
    assert registry[NEW_NAME]["global_name"] == NEW_GLOBAL
    assert not old_chat.exists()
    assert new_chat.read_text().startswith(f"# Chat History - workflow ({NEW_NAME})")


def test_historical_agent_identity_migration_blocks_chat_destination_collision(
    tmp_path: Path,
) -> None:
    state, _artifact, old_chat = _seed_state(tmp_path)
    new_chat = old_chat.with_name(old_chat.name.replace(OLD_NAME, NEW_NAME))
    new_chat.write_text("different existing chat\n", encoding="utf-8")

    preview = preview_historical_agent_identity_migration(_request(state))

    assert not preview.ok
    assert {blocker.code for blocker in preview.blockers} == {
        "chat_destination_collision"
    }


def _request(state: Path) -> AgentIdentityMigrationRequest:
    return AgentIdentityMigrationRequest(
        {OLD_BEAD: NEW_BEAD},
        state,
        identity=AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena")),
    )


def _seed_state(tmp_path: Path) -> tuple[Path, Path, Path]:
    state = tmp_path / "state"
    artifact = state / "projects" / "proj" / "artifacts" / "codex" / "20260803120000"
    artifact.mkdir(parents=True)
    chat_dir = state / "chats" / "202608"
    chat_dir.mkdir(parents=True)
    old_chat = chat_dir / f"20260803-120000-{OLD_NAME}.md"
    old_chat.write_text(
        "\n".join(
            [
                f"# Chat History - workflow ({OLD_NAME})",
                "",
                f"Agent {OLD_GLOBAL} used %id:{OLD_NAME}.",
            ]
        ),
        encoding="utf-8",
    )
    meta = {
        "bead_id": OLD_BEAD,
        "epic_bead_id": "epic-1",
        "phase_bead_id": "phase-1",
        "agent_name": OLD_NAME,
        "local_name": OLD_NAME,
        "global_name": OLD_GLOBAL,
        "agent_family": OLD_BEAD,
        "wait_for": OLD_NAME,
        "chat_path": str(old_chat),
        "response_path": f"~/.sase/chats/202608/{old_chat.name}",
    }
    done = {
        "bead_id": OLD_BEAD,
        "agent_name": OLD_NAME,
        "global_name": OLD_GLOBAL,
        "outcome": "completed",
    }
    (artifact / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (artifact / "done.json").write_text(json.dumps(done), encoding="utf-8")
    (artifact / "raw_xprompt.md").write_text(
        f"%id:{OLD_NAME}\n%wait:{OLD_NAME}\n#resume({OLD_NAME})\n",
        encoding="utf-8",
    )
    history_dir = state / "prompt_history"
    history_dir.mkdir()
    (history_dir / "0001.json").write_text(
        json.dumps({"prompts": [{"text": f"%id:{OLD_NAME}\n#resume:{OLD_NAME}"}]}),
        encoding="utf-8",
    )
    notifications_dir = state / "notifications"
    notifications_dir.mkdir()
    (notifications_dir / "notifications.jsonl").write_text(
        json.dumps({"agent_name": OLD_NAME, "bead_id": OLD_BEAD}) + "\n",
        encoding="utf-8",
    )
    (state / "agent_name_registry.json").write_text(
        json.dumps({OLD_NAME: {"global_name": OLD_GLOBAL}}),
        encoding="utf-8",
    )
    return state, artifact, old_chat
