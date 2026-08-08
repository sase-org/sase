from __future__ import annotations

from dataclasses import replace

import pytest

from sase.agent_clis import operations
from sase.agent_clis.latest import LatestQuery, LatestVersion
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdatesReady,
    InstallMethod,
    UpdateResultStatus,
    UpdateStrategy,
    UpdateTrigger,
    VersionCompare,
)
from sase.agent_clis.operations import (
    detect_agent_cli_statuses_for_names,
    execute_agent_cli_updates,
    plan_agent_cli_updates,
)
from sase.agent_clis.runner import CommandResult
from sase.plugins.latest import is_newer


def _status(
    name: str,
    *,
    method: InstallMethod,
    executable: str | None = "/bin/tool",
    installed: str | None = "1.0.0",
    latest: str | None = "2.0.0",
    package: str | None = None,
    self_update: tuple[str, ...] = (),
    writable: bool | None = None,
) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name=name.title(),
        binary=name,
        executable=executable,
        installed_version=installed,
        latest_version=latest,
        install_method=method,
        update_available=bool(installed and latest and installed != latest),
        docs_url=f"https://example.test/{name}",
        install_hint=f"install {name}",
        package=package,
        self_update_argv=self_update,
        npm_root_writable=writable,
    )


def _planner(*statuses: AgentCliStatus):
    def load(**_kwargs: object) -> tuple[AgentCliStatus, ...]:
        return statuses

    return load


def test_channel_versions_compare_exactly_where_pep_440_gives_up() -> None:
    """``is_newer`` answers ``False`` for every channel release id."""
    channel = replace(
        _status("muse", method=InstallMethod.SELF_MANAGED),
        installed_version="0.1.0-R708.1",
        version_compare=VersionCompare.EXACT,
    )

    assert is_newer("0.1.0-R709", "0.1.0-R708.1") is False
    assert operations._update_available(channel, "0.1.0-R709") is True
    assert operations._update_available(channel, "0.1.0-R708.1") is False
    assert operations._update_available(channel, None) is False


def test_pep_440_comparator_remains_the_default() -> None:
    npm_cli = replace(
        _status("codex", method=InstallMethod.NPM), installed_version="1.9.0"
    )

    assert npm_cli.version_compare is VersionCompare.PEP440
    assert operations._update_available(npm_cli, "1.10.0") is True
    assert operations._update_available(npm_cli, "1.8.0") is False


def test_collect_queries_channel_endpoints_and_npm_packages_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_url = "https://api.example.test/channels/stable"
    detected = (
        replace(
            _status("muse", method=InstallMethod.SELF_MANAGED, latest=None),
            installed_version="0.1.0-R708.1",
            latest_version_url=channel_url,
            version_compare=VersionCompare.EXACT,
        ),
        replace(
            _status("codex", method=InstallMethod.NPM, latest=None),
            installed_version="1.0.0",
            latest_version_package="@openai/codex",
        ),
    )
    monkeypatch.setattr(
        operations, "detect_agent_cli_statuses", lambda *_args, **_kwargs: detected
    )
    seen: list[tuple[LatestQuery, ...]] = []

    def latest(queries: tuple[LatestQuery, ...], **_kwargs: object):
        seen.append(queries)
        return {
            f"url:{channel_url}": LatestVersion("0.1.0-R709"),
            "npm:@openai/codex": LatestVersion("2.0.0"),
        }

    statuses = {
        status.name: status
        for status in operations.collect_agent_cli_statuses(
            metadata_payload={"providers": {}}, latest_fn=latest
        )
    }

    assert seen == [
        (LatestQuery.for_url(channel_url), LatestQuery.for_npm("@openai/codex"))
    ]
    assert statuses["muse"].latest_version == "0.1.0-R709"
    assert statuses["muse"].update_available is True
    assert statuses["codex"].latest_version == "2.0.0"
    assert statuses["codex"].update_available is True


def test_declared_channel_endpoint_wins_over_an_npm_mirror() -> None:
    status = replace(
        _status("muse", method=InstallMethod.SELF_MANAGED),
        latest_version_url="https://api.example.test/channels/stable",
        latest_version_package="muse-mirror",
    )

    assert operations._latest_query(status) == LatestQuery.for_url(
        "https://api.example.test/channels/stable"
    )
    assert operations._latest_query(
        replace(status, latest_version_url=None)
    ) == LatestQuery.for_npm("muse-mirror")
    assert (
        operations._latest_query(
            replace(status, latest_version_url=None, latest_version_package=None)
        )
        is None
    )


def test_declared_json_field_reaches_the_latest_query() -> None:
    status = replace(
        _status("muse", method=InstallMethod.SELF_MANAGED),
        latest_version_url="https://api.example.test/channels/stable",
        latest_version_json_field="release",
    )

    query = operations._latest_query(status)

    assert query is not None
    assert query.field == "release"


def test_self_update_env_reaches_the_runner_without_leaking_into_the_reprobe() -> None:
    status = replace(
        _status("muse", method=InstallMethod.SELF_MANAGED, latest=None),
        executable="/bin/muse",
        installed_version="0.1.0-R708.1",
        self_update_argv=("--version",),
        self_update_env=(("MUSE_SYNC_UPDATE", "1"),),
        version_regex=r"\((?P<version>[^)]+)\)",
    )
    plan = plan_agent_cli_updates(["muse"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliUpdatesReady)
    assert plan.entries[0].env_overlay == (("MUSE_SYNC_UPDATE", "1"),)
    calls: list[tuple[tuple[str, ...], object]] = []

    def run(argv: tuple[str, ...], **kwargs: object) -> CommandResult:
        calls.append((argv, kwargs.get("env_overlay")))
        return CommandResult(argv, 0, stdout="Muse Code 0.1.0 (0.1.0-R709)")

    result = execute_agent_cli_updates(plan, run_fn=run, record_fn=None)[0]

    assert calls == [
        (("/bin/muse", "--version"), {"MUSE_SYNC_UPDATE": "1"}),
        (("/bin/muse", "--version"), None),
    ]
    assert result.status is UpdateResultStatus.UPDATED
    assert result.new_version == "0.1.0-R709"
    assert result.env_overlay == (("MUSE_SYNC_UPDATE", "1"),)


def test_named_local_detection_zero_names_skips_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operations.llm_registry,
        "get_llm_metadata_payload",
        lambda: pytest.fail("empty candidate sets must not inspect the registry"),
    )

    assert detect_agent_cli_statuses_for_names(()) == ()


def test_full_collection_filters_hidden_management_providers_before_probing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[dict[str, object], object]] = []
    payload = {
        "providers": {
            "visible": {"autodetect_cli_name": "visible"},
            "hidden": {
                "autodetect_cli_name": "hidden",
                "hidden_from_agent_cli_management": True,
            },
            "legacy": {"autodetect_cli_name": "legacy"},
            "truthy": {
                "autodetect_cli_name": "truthy",
                "hidden_from_agent_cli_management": "yes",
            },
        }
    }

    def _detect(
        providers: dict[str, object],
        *,
        env: object,
        run_fn: object,
    ) -> tuple[AgentCliStatus, ...]:
        del run_fn
        seen.append((providers, env))
        return ()

    monkeypatch.setattr(operations, "detect_agent_cli_statuses", _detect)

    assert (
        operations.collect_agent_cli_statuses(
            metadata_payload=payload,
            env={"PATH": "/bin"},
            latest_fn=lambda _packages, **_kwargs: {},
        )
        == ()
    )
    assert seen == [
        (
            {
                "visible": payload["providers"]["visible"],
                "legacy": payload["providers"]["legacy"],
                "truthy": payload["providers"]["truthy"],
            },
            {"PATH": "/bin"},
        )
    ]


def test_named_local_detection_filters_metadata_before_probing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[dict[str, object], object]] = []

    def _detect(
        providers: dict[str, object],
        *,
        env: object,
        run_fn: object,
    ) -> tuple[AgentCliStatus, ...]:
        del run_fn
        seen.append((providers, env))
        return ()

    monkeypatch.setattr(operations, "detect_agent_cli_statuses", _detect)
    payload = {
        "providers": {
            "claude": {"autodetect_cli_name": "claude"},
            "codex": {"autodetect_cli_name": "codex"},
            "fakey": {
                "autodetect_cli_name": "fakey",
                "hidden_from_agent_cli_management": True,
            },
            "legacy": {"autodetect_cli_name": "legacy"},
        }
    }
    env = {"PATH": "/bin"}

    assert (
        detect_agent_cli_statuses_for_names(
            ("codex", "fakey", "legacy"),
            metadata_payload=payload,
            env=env,
        )
        == ()
    )
    assert seen == [
        (
            {
                "codex": payload["providers"]["codex"],
                "legacy": payload["providers"]["legacy"],
            },
            env,
        )
    ]


def test_plan_includes_docs_for_not_installed_bundled_and_manual_skips() -> None:
    statuses = (
        _status(
            "missing",
            method=InstallMethod.NOT_INSTALLED,
            executable=None,
            installed=None,
            latest=None,
        ),
        _status("fakey", method=InstallMethod.BUNDLED, latest=None),
        _status("unknown", method=InstallMethod.UNKNOWN),
    )

    plan = plan_agent_cli_updates(all_clis=True, status_fn=_planner(*statuses))

    assert isinstance(plan, AgentCliNothingToUpdate)
    entries = {entry.name: entry for entry in plan.entries}
    assert "https://example.test/missing" in entries["missing"].skip_reason
    assert "sase update" in entries["fakey"].skip_reason
    assert "https://example.test/unknown" in entries["unknown"].skip_reason
    assert all(entry.argv is None for entry in plan.entries)


def test_npm_writability_guard_returns_exact_manual_command() -> None:
    status = _status(
        "codex",
        method=InstallMethod.NPM,
        package="@openai/codex",
        writable=False,
    )

    plan = plan_agent_cli_updates(["codex"], status_fn=_planner(status))

    assert isinstance(plan, AgentCliNothingToUpdate)
    entry = plan.entries[0]
    assert entry.strategy is UpdateStrategy.MANUAL
    assert entry.manual_argv == (
        "npm",
        "install",
        "-g",
        "@openai/codex@latest",
    )
    assert "npm install -g @openai/codex@latest" in entry.skip_reason
    assert "never uses sudo" in entry.skip_reason
    assert status.docs_url in entry.skip_reason


def test_npm_beats_declared_self_update_in_plan() -> None:
    status = _status(
        "claude",
        method=InstallMethod.NPM,
        package="@anthropic-ai/claude-code",
        self_update=("update",),
        writable=True,
    )

    plan = plan_agent_cli_updates(["Claude"], status_fn=_planner(status))

    assert isinstance(plan, AgentCliUpdatesReady)
    assert plan.entries[0].strategy is UpdateStrategy.NPM
    assert plan.entries[0].argv == (
        "npm",
        "install",
        "-g",
        "@anthropic-ai/claude-code@latest",
    )


def test_self_managed_claude_plans_native_update_command() -> None:
    status = _status(
        "claude",
        method=InstallMethod.SELF_MANAGED,
        executable="/bin/claude",
        package="@anthropic-ai/claude-code",
        self_update=("update",),
    )

    plan = plan_agent_cli_updates(["claude"], status_fn=_planner(status))

    assert isinstance(plan, AgentCliUpdatesReady)
    assert plan.entries[0].strategy is UpdateStrategy.SELF_UPDATE
    assert plan.entries[0].argv == ("/bin/claude", "update")


def test_unknown_name_is_typed_and_does_not_execute() -> None:
    plan = plan_agent_cli_updates(
        ["codez"],
        status_fn=_planner(_status("codex", method=InstallMethod.SELF_MANAGED)),
    )

    assert isinstance(plan, AgentCliUnknownName)
    assert plan.query == "codez"
    assert plan.suggestions == ("codex",)


def test_execute_runs_sequentially_and_reports_reprobed_versions() -> None:
    status = _status(
        "agy",
        method=InstallMethod.SELF_MANAGED,
        self_update=("update",),
        latest=None,
    )
    plan = plan_agent_cli_updates(["agy"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliUpdatesReady)
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        calls.append(argv)
        if argv[-1] == "--version":
            return CommandResult(argv, 0, stdout="agy 1.1.0")
        return CommandResult(argv, 0, stdout="updated", elapsed=2.5)

    results = execute_agent_cli_updates(plan, run_fn=run)

    assert calls == [("/bin/tool", "update"), ("/bin/tool", "--version")]
    assert len(results) == 1
    assert results[0].status is UpdateResultStatus.UPDATED
    assert results[0].old_version == "1.0.0"
    assert results[0].new_version == "1.1.0"
    assert results[0].output_tail == "updated"


def test_execute_reports_successful_idempotent_self_update_as_current() -> None:
    status = _status(
        "agy",
        method=InstallMethod.SELF_MANAGED,
        self_update=("update",),
        latest=None,
    )
    plan = plan_agent_cli_updates(["agy"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliUpdatesReady)

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        stdout = "agy 1.0.0" if argv[-1] == "--version" else "already current"
        return CommandResult(argv, 0, stdout=stdout)

    result = execute_agent_cli_updates(plan, run_fn=run)[0]

    assert result.status is UpdateResultStatus.ALREADY_CURRENT


def test_already_current_entry_is_not_executed() -> None:
    status = replace(
        _status("qwen", method=InstallMethod.NPM, package="qwen"),
        latest_version="1.0.0",
        update_available=False,
    )
    plan = plan_agent_cli_updates(["qwen"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliNothingToUpdate)

    results = execute_agent_cli_updates(
        plan,
        run_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )

    assert results[0].status is UpdateResultStatus.ALREADY_CURRENT


def test_execute_records_results_trigger_and_elapsed_once() -> None:
    status = _status(
        "agy",
        method=InstallMethod.SELF_MANAGED,
        self_update=("update",),
        latest=None,
    )
    plan = plan_agent_cli_updates(["agy"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliUpdatesReady)
    recorded: list[tuple[object, UpdateTrigger, float]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        stdout = "agy 1.1.0" if argv[-1] == "--version" else "updated"
        return CommandResult(argv, 0, stdout=stdout)

    def record(results: object, *, trigger: UpdateTrigger, elapsed: float) -> None:
        recorded.append((results, trigger, elapsed))

    results = execute_agent_cli_updates(
        plan,
        run_fn=run,
        trigger=UpdateTrigger.ADMIN_CENTER,
        record_fn=record,
    )

    assert len(recorded) == 1
    assert recorded[0][0] == results
    assert recorded[0][1] is UpdateTrigger.ADMIN_CENTER
    assert recorded[0][2] >= 0


def test_execute_record_fn_none_suppresses_journaling() -> None:
    status = replace(
        _status("qwen", method=InstallMethod.NPM, package="qwen"),
        latest_version="1.0.0",
        update_available=False,
    )
    plan = plan_agent_cli_updates(["qwen"], status_fn=_planner(status))
    assert isinstance(plan, AgentCliNothingToUpdate)

    results = execute_agent_cli_updates(plan, record_fn=None)

    assert results[0].status is UpdateResultStatus.ALREADY_CURRENT
