"""Tests for kind -> provider dispatch and catalog-backed candidates."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.completion.candidates.protocol import Candidate
from sase.completion.candidates.providers import candidates_for


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    monkeypatch.delenv("SASE_SDD_BEADS_DIR", raising=False)
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)


def test_artifact_relation_candidates_include_cli_slugs() -> None:
    values = {
        candidate.value
        for candidate in candidates_for(
            "artifact_relation", "", project=None, limit=200
        )
    }
    assert {"related", "implements", "supersedes", "derives-from"} <= values


def test_directive_candidates_use_shared_contract_and_expose_final() -> None:
    result = candidates_for("directive", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"model", "effort", "id", "wait", "auto", "final"} <= values
    model = next(candidate for candidate in result if candidate.value == "model")
    assert "Override the LLM model" in model.description
    assert "alias %m" in model.description


def test_candidates_for_unknown_kind_returns_empty_list() -> None:
    assert candidates_for("bogus", "", project=None, limit=200) == []


def test_candidates_for_kind_without_shipped_provider_returns_empty_list() -> None:
    # path/dir are declared ValueKinds but stay shell-native, with no provider.
    assert candidates_for("path", "", project=None, limit=200) == []
    assert candidates_for("dir", "", project=None, limit=200) == []


def test_flag_candidates_come_from_the_in_process_registry() -> None:
    result = candidates_for("flag", "", project=None, limit=200)

    keys = {candidate.value for candidate in result}
    assert "ref_sync_gesture" in keys
    assert "coder_inherits_planner_chat" not in keys
    assert "completion_refresh_on_update" not in keys
    ref_sync = next(
        candidate for candidate in result if candidate.value == "ref_sync_gesture"
    )
    assert ref_sync.description.startswith("sunset:")


def test_model_candidates_are_the_builtin_size_aliases() -> None:
    result = candidates_for("model", "", project=None, limit=200)

    assert [candidate.value for candidate in result] == [
        "xsmall",
        "small",
        "medium",
        "large",
        "xlarge",
    ]


def test_provider_candidates_come_from_sase_llm_entry_points(monkeypatch) -> None:
    from sase.completion.candidates import catalog_build

    monkeypatch.setattr(
        catalog_build.importlib_metadata,
        "entry_points",
        lambda *, group: (
            [
                SimpleNamespace(
                    name="grok", value="sase.llm_provider.grok:GrokProvider"
                ),
                SimpleNamespace(
                    name="codex", value="sase.llm_provider.codex:CodexProvider"
                ),
            ]
            if group == "sase_llm"
            else []
        ),
    )

    assert candidates_for("provider", "", project=None, limit=200) == [
        Candidate("codex", "sase.llm_provider.codex:CodexProvider"),
        Candidate("grok", "sase.llm_provider.grok:GrokProvider"),
    ]


def test_snippet_candidates_use_rust_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase").mkdir()
    calls: list[tuple[str | None, str]] = []

    def fake_loader(project: str | None, root_dir: str) -> dict[str, object]:
        calls.append((project, root_dir))
        return {
            "entries": [
                {
                    "trigger": "todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {
                    "trigger": "Todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {"trigger": "fixit", "source": "xprompt", "xprompt_name": "fix"},
                {"trigger": "", "source": "ignored"},
            ]
        }

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            fake_loader
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    result = candidates_for("snippet", "", project="demo", limit=200)

    assert result == [
        Candidate("todo", "user_config · ace.snippets"),
        Candidate("Todo", "user_config · ace.snippets"),
        Candidate("fixit", "xprompt · fix"),
    ]
    assert calls == [("demo", str(tmp_path))]


@pytest.mark.parametrize("payload", [{"entries": "bad"}, ["bad"]])
def test_snippet_candidates_degrade_on_malformed_payload(
    payload: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            (lambda _project, _root_dir: payload)
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_snippet_candidates_degrade_on_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    def raise_native_error(_project: str | None, _root_dir: str) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            raise_native_error
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_tag_candidates_come_from_the_xprompt_tag_enum() -> None:
    result = candidates_for("tag", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"vcs", "commit", "land_epic"} <= values


def test_xprompt_and_skill_candidates_include_packaged_names() -> None:
    xprompts = candidates_for("xprompt", "", project=None, limit=200)
    skills = candidates_for("skill", "", project=None, limit=200)

    assert any(candidate.value == "coder" for candidate in xprompts)
    assert any(candidate.value == "sase_repo" for candidate in skills)


def test_provider_errors_return_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.feature_flags.registry as flag_registry

    monkeypatch.setattr(
        flag_registry,
        "feature_flag_definitions",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert candidates_for("flag", "", project=None, limit=200) == []


# --- pending_plan -----------------------------------------------------------

_SEPT_2026 = datetime(2026, 9, 24, 12, 0, 0)
_OCT_2026 = datetime(2026, 10, 5, 12, 0, 0)


def _pending_plan_file(
    name: str, *, ts: datetime | None = None, title: str, tier: str = "tale"
) -> Path:
    from sase.core.paths import sharded_path

    path = Path(sharded_path("plans", name, ts=ts or _SEPT_2026))
    path.write_text(
        f"---\ntier: {tier}\ntitle: {title}\ngoal: G\n---\n# {path.stem}\n",
        encoding="utf-8",
    )
    return path


def _append_pending_plan_notification(
    notification_id: str,
    plan_file: Path,
    *,
    agent_name: str = "0qw",
    request_id: str | None = None,
    minutes_ago: int = 4,
    dismissed: bool = False,
    action: str = "PlanApproval",
    plan_tier: str = "tale",
) -> Path:
    from datetime import timedelta

    from sase.core.time import get_timezone
    from sase.notifications.models import Notification
    from sase.notifications.store import append_notification

    response_dir = plan_file.parent / f"{notification_id}.resp"
    response_dir.mkdir(parents=True, exist_ok=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    action_data = {
        "agent_name": agent_name,
        "agent_cl_name": "demo-cl",
        "original_plan_file": str(plan_file),
        "response_dir": str(response_dir),
        "plan_tier": plan_tier,
    }
    if request_id:
        action_data["request_id"] = request_id
    append_notification(
        Notification(
            id=notification_id,
            timestamp=(
                datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)
            ).isoformat(),
            sender="plan",
            files=[str(plan_file)],
            action=action,
            action_data=action_data,
            dismissed=dismissed,
        )
    )
    return response_dir


def _mock_gate_shells(
    monkeypatch: pytest.MonkeyPatch, states: dict[str, str] | None
) -> None:
    """Route the fast-path gate lookup to per-gate wire states.

    ``None`` means no gate-shell record exists (a legacy gate).
    """
    import sase.core.agent_scan_facade as facade

    def _find(index_path: object, project: object, gate_id: str) -> object:
        if states is None or gate_id not in states:
            return None
        return SimpleNamespace(
            agent_meta=SimpleNamespace(
                agent_session_shell=SimpleNamespace(state=states[gate_id])
            )
        )

    monkeypatch.setattr(facade, "find_gate_shell_by_gate_id", _find)


def test_pending_plan_candidates_offer_display_names_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _pending_plan_file("older_plan.md", title="Older Plan")
    newer = _pending_plan_file("newer_plan.md", title="Newer Plan")
    _append_pending_plan_notification(
        "id-older", older, request_id="gate-older", minutes_ago=10
    )
    _append_pending_plan_notification(
        "id-newer", newer, request_id="gate-newer", minutes_ago=2
    )
    _mock_gate_shells(monkeypatch, {"gate-older": "pending", "gate-newer": "pending"})

    result = candidates_for("pending_plan", "", project=None, limit=200)

    assert [candidate.value for candidate in result] == [
        "newer_plan",
        "older_plan",
    ]
    assert result[0].description == "tale · Newer Plan · @0qw · 2m"
    assert result[1].description == "tale · Older Plan · @0qw · 10m"


def test_pending_plan_candidates_show_colliding_shard_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _pending_plan_file("same_name.md", ts=_SEPT_2026, title="First")
    second = _pending_plan_file("same_name.md", ts=_OCT_2026, title="Second")
    _append_pending_plan_notification("id-first", first, request_id="gate-first")
    _append_pending_plan_notification("id-second", second, request_id="gate-second")
    _mock_gate_shells(monkeypatch, {"gate-first": "pending", "gate-second": "pending"})

    result = candidates_for("pending_plan", "", project=None, limit=200)

    assert {candidate.value for candidate in result} == {
        "202609/same_name",
        "202610/same_name",
    }


def test_pending_plan_candidates_exclude_settled_stale_and_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = _pending_plan_file("live_plan.md", title="Live Plan")
    answered = _pending_plan_file("answered_plan.md", title="Answered Plan")
    stale = _pending_plan_file("stale_plan.md", title="Stale Plan")
    cancelled = _pending_plan_file("cancelled_plan.md", title="Cancelled Plan")
    _append_pending_plan_notification("id-live", live, request_id="gate-live")
    _append_pending_plan_notification(
        "id-answered", answered, request_id="gate-answered"
    )
    _append_pending_plan_notification(
        "id-stale", stale, request_id="gate-stale", minutes_ago=60 * 25
    )
    cancelled_dir = _append_pending_plan_notification(
        "id-cancelled", cancelled, request_id="gate-cancelled"
    )
    (cancelled_dir / "cancellation.json").write_text("{}", encoding="utf-8")
    # Age out the pending-action store entries so staleness falls back to
    # the notification timestamp, as for store-less legacy rows.
    from sase.core.paths import sase_subdir

    store_path = sase_subdir("pending_actions") / "actions.json"
    if store_path.exists():
        store_path.unlink()
    _mock_gate_shells(
        monkeypatch,
        {
            "gate-live": "pending",
            "gate-answered": "answered",
            "gate-stale": "pending",
            "gate-cancelled": "pending",
        },
    )

    result = candidates_for("pending_plan", "", project=None, limit=200)

    assert [candidate.value for candidate in result] == ["live_plan"]


def test_pending_plan_candidates_hide_dismissed_legacy_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismissed = _pending_plan_file("dismissed_plan.md", title="Dismissed Plan")
    kept = _pending_plan_file("kept_plan.md", title="Kept Plan")
    _append_pending_plan_notification("id-dismissed", dismissed, dismissed=True)
    _append_pending_plan_notification("id-kept", kept)
    _mock_gate_shells(monkeypatch, None)

    result = candidates_for("pending_plan", "", project=None, limit=200)

    # No gate-shell record exists, so the fast path keeps non-dismissed
    # rows visible; the resolver additionally requires a live planner row.
    assert [candidate.value for candidate in result] == ["kept_plan"]


def test_pending_plan_candidates_are_empty_without_notifications() -> None:
    assert candidates_for("pending_plan", "", project=None, limit=200) == []


def test_pending_plan_catalog_stays_off_the_forbidden_imports() -> None:
    """The plans catalog module imports cleanly without UI-heavy packages."""
    script = (
        "import sys; "
        "import sase.completion.candidates.catalog_plans; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "{'textual', 'rich'} or m == 'sase.ace' or "
        "m.startswith(('sase.ace.', 'sase.sdd.', 'sase.bead.', "
        "'sase.workspace_provider.', 'sase.xprompt.', 'sase.llm_provider.', "
        "'sase.notifications.', 'sase.gate_shell.')) "
        "or m in ('sase.notifications', 'sase.gate_shell', 'sase.main.parser')]; "
        "sys.exit('forbidden imports: ' + ','.join(bad) if bad else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_pending_plan_terminal_gate_states_match_gate_shell() -> None:
    """The pinned terminal-state set fails loudly if the source drifts."""
    from sase.completion.candidates.catalog_plans import (
        PENDING_PLAN_TERMINAL_GATE_STATES,
    )
    from sase.gate_shell.state import TERMINAL_GATE_STATES

    assert PENDING_PLAN_TERMINAL_GATE_STATES == set(TERMINAL_GATE_STATES)


def test_pending_plan_uses_volatile_disk_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.completion.candidates.providers as providers
    from sase.completion.kinds import VOLATILE_KIND_TTL_SECONDS, ValueKind

    assert VOLATILE_KIND_TTL_SECONDS[ValueKind.PENDING_PLAN] == 5

    seen: dict[str, float] = {}
    real_load = providers.load_cached_candidates

    def _spy(
        cache_key: object, *, source_mtime: float | None, ttl_seconds: float = 30.0
    ) -> list[Candidate] | None:
        seen[str(cache_key)] = ttl_seconds
        return real_load(cache_key, source_mtime=source_mtime, ttl_seconds=ttl_seconds)

    monkeypatch.setattr(providers, "load_cached_candidates", _spy)
    candidates_for("pending_plan", "", project=None, limit=200)
    candidates_for("project", "", project=None, limit=200)

    assert seen[str(ValueKind.PENDING_PLAN)] == 5
    assert seen[str(ValueKind.PROJECT)] == 30.0


def test_pending_plan_matches_resolver_name_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fast path and ``pending_plans()`` agree on one fixture state."""
    from sase.main.plan_pending import pending_plans

    live = _pending_plan_file("parity_live.md", title="Parity Live")
    other = _pending_plan_file("parity_other.md", title="Parity Other")
    done = _pending_plan_file("parity_done.md", title="Parity Done")
    _append_pending_plan_notification("id-live", live, request_id="gate-live")
    _append_pending_plan_notification(
        "id-other", other, request_id="gate-other", minutes_ago=9
    )
    _append_pending_plan_notification("id-done", done, request_id="gate-done")
    states = {"gate-live": "pending", "gate-other": "pending", "gate-done": "answered"}
    _mock_gate_shells(monkeypatch, states)
    monkeypatch.setattr(
        "sase.gate_shell.store.find_gate_shell_by_gate_id",
        lambda project, gate_id: SimpleNamespace(
            is_terminal=(states.get(gate_id, "pending") != "pending")
        ),
    )

    fast_path = {
        candidate.value
        for candidate in candidates_for("pending_plan", "", project=None, limit=200)
    }
    resolver = {plan.display_name for plan in pending_plans()}

    assert fast_path == resolver == {"parity_live", "parity_other"}
