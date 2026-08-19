"""Tests for the ``llm_interactive_cli`` hook and vendor install metadata."""

from __future__ import annotations

from typing import Any

import pytest

from sase.llm_provider._registry_metadata import provider_metadata
from sase.llm_provider.registry import (
    get_llm_metadata_payload,
    model_picker_hidden_provider_names,
    provider_interactive_cli_map,
    provider_vendor_map,
    registered_provider_names,
)

_INTERACTIVE_CLI_KEYS = (
    "argv",
    "args",
    "bypass_args",
    "model_args",
    "env",
    "menu_key",
    "supported",
)

_BUILT_IN_INTERACTIVE = {
    "claude": {
        "menu_key": "c",
        "bypass_args": ("--dangerously-skip-permissions",),
        "vendor": "Anthropic",
    },
    "codex": {
        "menu_key": "x",
        "bypass_args": ("--dangerously-bypass-approvals-and-sandbox",),
        "vendor": "OpenAI",
    },
    "agy": {
        "menu_key": "a",
        "bypass_args": ("--dangerously-skip-permissions",),
        "vendor": "Antigravity",
    },
    "qwen": {
        "menu_key": "q",
        "bypass_args": ("--yolo",),
        "vendor": "Alibaba",
    },
    "opencode": {
        "menu_key": "o",
        "bypass_args": (),
        "vendor": "SST",
    },
    "grok": {
        "menu_key": "g",
        "bypass_args": ("--always-approve",),
        "vendor": "xAI",
    },
    "muse": {
        "menu_key": "m",
        "bypass_args": ("--yolo",),
        "vendor": "Meta",
    },
}

_MODEL_ARGS = ("--model", "{model}")


class _Plugin:
    """Minimal stand-in for a provider plugin instance."""

    def __init__(
        self,
        *,
        interactive: Any = None,
        cli_name: str | None = "bare-cli",
        raise_interactive: bool = False,
        vendor: str | None = None,
    ) -> None:
        self._interactive = interactive
        self._cli_name = cli_name
        self._raise_interactive = raise_interactive
        self._vendor = vendor

    def llm_provider_name(self) -> str:
        return "fake"

    def llm_autodetect_cli_name(self) -> str | None:
        return self._cli_name

    def llm_install_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {"display_name": "Fake CLI"}
        if self._vendor is not None:
            metadata["vendor"] = self._vendor
        return metadata

    def llm_interactive_cli(self) -> Any:
        if self._raise_interactive:
            raise RuntimeError("third-party plugin exploded")
        return self._interactive


def _descriptor_for(plugin: object, name: str = "fake") -> dict[str, Any]:
    return provider_metadata(name, plugin)["interactive_cli"]


def test_every_registered_provider_descriptor_normalizes() -> None:
    names = registered_provider_names()
    descriptors = provider_interactive_cli_map()
    payload = get_llm_metadata_payload()["providers"]

    assert set(descriptors) == set(names)
    for name in names:
        descriptor = descriptors[name]
        assert set(descriptor) == set(_INTERACTIVE_CLI_KEYS)
        assert isinstance(descriptor["argv"], tuple)
        assert all(isinstance(item, str) for item in descriptor["argv"])
        assert isinstance(descriptor["args"], tuple)
        assert isinstance(descriptor["bypass_args"], tuple)
        assert isinstance(descriptor["model_args"], tuple)
        assert isinstance(descriptor["env"], dict)
        assert isinstance(descriptor["menu_key"], str)
        assert isinstance(descriptor["supported"], bool)
        assert payload[name]["interactive_cli"] == descriptor


def test_built_in_interactive_cli_matches_the_shell_script() -> None:
    descriptors = provider_interactive_cli_map()
    vendors = provider_vendor_map()

    for name, expected in _BUILT_IN_INTERACTIVE.items():
        descriptor = descriptors[name]
        assert descriptor["menu_key"] == expected["menu_key"]
        assert descriptor["bypass_args"] == expected["bypass_args"]
        assert descriptor["model_args"] == _MODEL_ARGS
        assert descriptor["supported"] is True
        assert descriptor["argv"] == (name,)
        assert vendors[name] == expected["vendor"]

    muse = descriptors["muse"]
    assert muse["env"] == {"MUSE_NO_AUTO_UPDATE": "1"}
    assert descriptors["opencode"]["bypass_args"] == ()


def test_fakey_is_not_an_interactive_cli() -> None:
    descriptor = provider_interactive_cli_map()["fakey"]

    assert descriptor["supported"] is False
    assert "fakey" in model_picker_hidden_provider_names()


def test_built_in_menu_keys_are_unique() -> None:
    keys = [
        descriptor["menu_key"]
        for name, descriptor in provider_interactive_cli_map().items()
        if name in _BUILT_IN_INTERACTIVE
    ]

    assert keys
    assert len(keys) == len(set(keys))
    assert set(keys) == {"a", "c", "g", "m", "o", "q", "x"}


def test_provider_that_omits_the_hook_falls_back_to_cli_name() -> None:
    class _Bare:
        def llm_provider_name(self) -> str:
            return "bare"

        def llm_autodetect_cli_name(self) -> str:
            return "bare-cli"

    descriptor = _descriptor_for(_Bare(), "bare")

    assert descriptor == {
        "argv": ("bare-cli",),
        "args": (),
        "bypass_args": (),
        "model_args": (),
        "env": {},
        "menu_key": "",
        "supported": True,
    }


def test_provider_without_cli_name_keeps_empty_argv() -> None:
    class _Nameless:
        def llm_provider_name(self) -> str:
            return "nameless"

    descriptor = _descriptor_for(_Nameless(), "nameless")

    assert descriptor["argv"] == ()
    assert descriptor["supported"] is True


def test_raising_hook_degrades_to_cli_name() -> None:
    descriptor = _descriptor_for(_Plugin(raise_interactive=True))

    assert descriptor["argv"] == ("bare-cli",)
    assert descriptor["supported"] is True
    assert descriptor["menu_key"] == ""


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-a-dict",
        [("argv", ["bare-cli"])],
        7,
    ],
)
def test_wrong_hook_type_degrades_to_defaults(value: Any) -> None:
    descriptor = _descriptor_for(_Plugin(interactive=value))

    assert descriptor["argv"] == ("bare-cli",)
    assert descriptor["args"] == ()
    assert descriptor["bypass_args"] == ()
    assert descriptor["model_args"] == ()
    assert descriptor["env"] == {}
    assert descriptor["menu_key"] == ""
    assert descriptor["supported"] is True


def test_non_string_argv_members_degrade_to_cli_name() -> None:
    descriptor = _descriptor_for(_Plugin(interactive={"argv": ["ok", 1]}))

    assert descriptor["argv"] == ("bare-cli",)


def test_non_string_args_members_degrade_to_empty() -> None:
    descriptor = _descriptor_for(_Plugin(interactive={"args": ["--ok", 1]}))

    assert descriptor["args"] == ()
    assert descriptor["argv"] == ("bare-cli",)


def test_multi_character_menu_key_is_truncated() -> None:
    descriptor = _descriptor_for(_Plugin(interactive={"menu_key": " cx "}))

    assert descriptor["menu_key"] == "c"


def test_non_string_menu_key_degrades_to_empty() -> None:
    descriptor = _descriptor_for(_Plugin(interactive={"menu_key": ["c"]}))

    assert descriptor["menu_key"] == ""


def test_unknown_keys_are_dropped() -> None:
    descriptor = _descriptor_for(
        _Plugin(interactive={"menu_key": "z", "future": True, "argv": ["custom"]})
    )

    assert set(descriptor) == set(_INTERACTIVE_CLI_KEYS)
    assert descriptor["menu_key"] == "z"
    assert descriptor["argv"] == ("custom",)
    assert "future" not in descriptor


def test_supported_false_is_the_only_opt_out() -> None:
    opted_out = _descriptor_for(_Plugin(interactive={"supported": False}))
    opted_in = _descriptor_for(_Plugin(interactive={"supported": True}))
    coerced = _descriptor_for(_Plugin(interactive={"supported": 0}))
    omitted = _descriptor_for(_Plugin(interactive={}))

    assert opted_out["supported"] is False
    assert opted_in["supported"] is True
    assert coerced["supported"] is True
    assert omitted["supported"] is True


def test_vendor_is_pulled_from_install_metadata() -> None:
    metadata = provider_metadata("fake", _Plugin(vendor="  Acme  "))

    assert metadata["install"]["vendor"] == "Acme"
    assert "vendor" not in provider_metadata("fake", _Plugin())["install"]


def test_registry_maps_read_the_memoized_payload() -> None:
    descriptors = provider_interactive_cli_map()
    vendors = provider_vendor_map()

    assert descriptors["claude"]["menu_key"] == "c"
    assert vendors["claude"] == "Anthropic"
    assert vendors["fakey"] == ""
