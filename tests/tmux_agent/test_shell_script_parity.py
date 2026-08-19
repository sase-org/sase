"""Pin tmux Agent launch argv, keys, and window names against the shell script.

The script this epic replaces lives in the chezmoi linked repo at
``home/bin/executable_tmux_ai_window``, with a companion
``home/bin/executable_tm-renumber-ai-windows``. Flag *order* is not part of
the contract: ``launch_spec.py`` composes in descriptor order, which differs
from the script's hand-written order for ``agy``, ``qwen``, ``grok``, and
``muse``. The test compares the leading binary plus the flag *set*.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.config.tmux_agent import TmuxAgentConfig, TmuxAgentProviderConfig
from sase.tmux_agent import catalog as catalog_module
from sase.tmux_agent.catalog import build_tmux_agent_catalog
from sase.tmux_agent.models import TmuxAgentCatalog
from sase.tmux_agent.window import next_window_name, renumber_plan

_PROVIDERS = ("claude", "codex", "agy", "qwen", "opencode", "grok", "muse")

# Documented parity recipe from the epic plan / docs/configuration.md.
_PARITY_CONFIG = TmuxAgentConfig(
    effort="max",
    providers={
        "claude": TmuxAgentProviderConfig(env={"EDITOR": "nvim"}),
        "codex": TmuxAgentProviderConfig(effort="xhigh"),
        "grok": TmuxAgentProviderConfig(effort="xhigh"),
        "opencode": TmuxAgentProviderConfig(effort="off"),
        "agy": TmuxAgentProviderConfig(model="gemini-3.7-flash-high"),
        "qwen": TmuxAgentProviderConfig(model="qwen3.6-plus"),
        "muse": TmuxAgentProviderConfig(model="muse-spark-1.2"),
    },
)

_EXPECTED_KEYS = {
    "claude": "c",
    "codex": "x",
    "agy": "a",
    "qwen": "q",
    "opencode": "o",
    "grok": "g",
    "muse": "m",
}

# Leading binary plus remaining tokens as a set. Order is not the contract.
_EXPECTED_ARGV: dict[str, tuple[str, frozenset[str]]] = {
    "claude": (
        "claude",
        frozenset({"--dangerously-skip-permissions", "--effort", "max"}),
    ),
    "codex": (
        "codex",
        frozenset(
            {
                "--dangerously-bypass-approvals-and-sandbox",
                "-c",
                'model_reasoning_effort="xhigh"',
            }
        ),
    ),
    "agy": (
        "agy",
        frozenset(
            {
                "--dangerously-skip-permissions",
                "--model",
                "gemini-3.7-flash-high",
            }
        ),
    ),
    "qwen": ("qwen", frozenset({"--yolo", "--model", "qwen3.6-plus"})),
    "opencode": ("opencode", frozenset()),
    "grok": ("grok", frozenset({"--always-approve", "--effort", "xhigh"})),
    "muse": (
        "muse",
        frozenset(
            {
                "--yolo",
                "--model",
                "muse-spark-1.2",
                "--reasoning-effort",
                "ultra",
            }
        ),
    ),
}


def _status(name: str) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name=name,
        binary=name,
        executable=f"/usr/bin/{name}",
        installed_version="1.0.0",
        latest_version=None,
        install_method=InstallMethod.NPM,
        update_available=False,
        docs_url=None,
        install_hint=f"install {name} first",
    )


def _binary_and_flags(argv: tuple[str, ...]) -> tuple[str, frozenset[str]]:
    binary, *rest = argv
    return binary, frozenset(rest)


@pytest.fixture
def parity_catalog(monkeypatch: pytest.MonkeyPatch) -> TmuxAgentCatalog:
    monkeypatch.setattr(catalog_module, "get_tmux_agent_config", lambda: _PARITY_CONFIG)
    monkeypatch.setattr(catalog_module, "get_llm_provider_config", lambda: {})
    monkeypatch.setattr(
        catalog_module,
        "effective_default_effort_snapshot",
        lambda now=None: SimpleNamespace(effective_effort=lambda now=None: None),
    )
    monkeypatch.setattr(
        catalog_module, "get_active_provider_disables", lambda now=None: {}
    )
    statuses = tuple(_status(name) for name in _PROVIDERS)
    return build_tmux_agent_catalog(directory="/tmp/project", statuses=statuses)


def test_parity_argv_matches_shell_script_flag_set(
    parity_catalog: TmuxAgentCatalog,
) -> None:
    by_name = {entry.provider: entry for entry in parity_catalog.entries}
    assert set(by_name) >= set(_PROVIDERS)
    for name in _PROVIDERS:
        expected_binary, expected_flags = _EXPECTED_ARGV[name]
        binary, flags = _binary_and_flags(by_name[name].argv)
        assert binary == expected_binary, name
        assert flags == expected_flags, name


def test_parity_menu_keys_match_shell_script(
    parity_catalog: TmuxAgentCatalog,
) -> None:
    by_name = {entry.provider: entry for entry in parity_catalog.entries}
    keys = {name: by_name[name].key for name in _PROVIDERS}
    assert keys == _EXPECTED_KEYS
    assert "".join(_EXPECTED_KEYS[name] for name in _PROVIDERS) == "cxaqogm"


def test_parity_claude_env_pins_editor_nvim(parity_catalog: TmuxAgentCatalog) -> None:
    by_name = {entry.provider: entry for entry in parity_catalog.entries}
    assert dict(by_name["claude"].env)["EDITOR"] == "nvim"


def test_parity_muse_env_disables_auto_update(
    parity_catalog: TmuxAgentCatalog,
) -> None:
    by_name = {entry.provider: entry for entry in parity_catalog.entries}
    assert dict(by_name["muse"].env)["MUSE_NO_AUTO_UPDATE"] == "1"


def test_window_naming_sequence_matches_shell_script() -> None:
    assert next_window_name("ai", []) == "ai"
    assert next_window_name("ai", ["ai"]) == "ai2"
    assert next_window_name("ai", ["ai", "ai2"]) == "ai3"


def test_renumber_plan_matches_tm_renumber_ai_windows() -> None:
    # Ports ``tm-renumber-ai-windows``: matching windows, in index order,
    # become ai, ai2, ai3, ... and a window already carrying its target
    # name is omitted from the rename list.
    assert renumber_plan("ai", ((1, "ai"), (2, "ai2"), (3, "ai3"))) == ()
    assert renumber_plan("ai", ((1, "ai"), (2, "ai3"), (3, "ai5"))) == (
        (2, "ai2"),
        (3, "ai3"),
    )
    assert renumber_plan("ai", ((9, "ai"), (4, "ai2"), (1, "ai3"))) == (
        (1, "ai"),
        (9, "ai3"),
    )
    assert renumber_plan("ai", ((1, "shell"), (2, "logs"))) == ()
