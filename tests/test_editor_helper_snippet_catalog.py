from __future__ import annotations

import argparse
import io
import json

import pytest

from sase.integrations.editor_helpers import handle_editor_helper_bridge
from sase.main.parser import create_parser
from sase.snippet.models import SnippetSourceContribution
from sase.macro.models import UNSET, InputArg, Macro


def _install_snippet_sources(
    monkeypatch: pytest.MonkeyPatch,
    macros: dict[str, Macro],
    snippets: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "sase.macro.loader.get_all_macros",
        lambda project=None: macros,
    )
    contributions = tuple(
        SnippetSourceContribution(
            trigger=trigger,
            template=template,
            kind="user",
            path="ace.snippets",
            display_path="ace.snippets",
            writable=True,
            layer="user",
        )
        for trigger, template in snippets.items()
    )
    monkeypatch.setattr(
        "sase.snippet.catalog._config_layer_contributions",
        lambda *_a, **_k: (contributions, (), (("user", "ace.snippets"),)),
    )


def test_parser_accepts_editor_helper_bridge_snippet_catalog() -> None:
    args = create_parser().parse_args(["editor", "helper-bridge", "snippet-catalog"])

    assert args.command == "editor"
    assert args.editor_subcommand == "helper-bridge"
    assert args.editor_helper_bridge_subcommand == "snippet-catalog"


def test_editor_helper_bridge_snippet_catalog_merges_macro_and_user_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "helper": Macro(
            name="helper",
            content="Help with {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            source_path="xprompts/helper.md",
            snippet=True,
            description="Helper prompt",
        )
    }
    _install_snippet_sources(monkeypatch, macros, {"user_snip": "User $1$0"})

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1, "project": "sase"})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["context"] == {"project": "sase", "scope": "explicit"}
    assert data["stats"] == {"total_count": 4}
    assert list(entries) == ["Helper", "User_snip", "helper", "user_snip"]
    assert entries["Helper"] == {
        "trigger": "Helper",
        "template": "Help with $1$0",
        "source": "macro",
        "macro_name": "helper",
        "description": "Helper prompt",
        "source_path_display": "xprompts/helper.md",
    }
    assert entries["User_snip"] == {
        "trigger": "User_snip",
        "template": "User $1$0",
        "source": "user_config",
        "macro_name": None,
        "description": None,
        "source_path_display": "ace.snippets",
    }
    assert entries["helper"] == {
        "trigger": "helper",
        "template": "Help with $1$0",
        "source": "macro",
        "macro_name": "helper",
        "description": "Helper prompt",
        "source_path_display": "xprompts/helper.md",
    }
    assert entries["user_snip"] == {
        "trigger": "user_snip",
        "template": "User $1$0",
        "source": "user_config",
        "macro_name": None,
        "description": None,
        "source_path_display": "ace.snippets",
    }


def test_editor_helper_bridge_snippet_catalog_user_overrides_macro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "shared": Macro(
            name="shared",
            content="from xprompt",
            source_path="xprompts/shared.md",
            snippet=True,
        )
    }
    _install_snippet_sources(
        monkeypatch,
        macros,
        {
            "shared": "from user",
            "Shared": "authored capital",
            "bad-trigger": "no",
        },
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert list(entries) == ["Shared", "shared"]
    assert data["stats"] == {"total_count": 2}
    assert entries["Shared"]["template"] == "authored capital"
    assert entries["Shared"]["source"] == "user_config"
    assert entries["shared"]["template"] == "from user"
    assert entries["shared"]["source"] == "user_config"


def test_editor_helper_bridge_snippet_catalog_composes_nested_macros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "leaf": Macro(name="leaf", content="leaf text", snippet=None),
        "outer": Macro(name="outer", content="outer #leaf", snippet=True),
    }
    _install_snippet_sources(monkeypatch, macros, {})

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["entries"] == [
        {
            "trigger": "Outer",
            "template": "Outer leaf text$0",
            "source": "macro",
            "macro_name": "outer",
            "description": None,
            "source_path_display": None,
        },
        {
            "trigger": "outer",
            "template": "outer leaf text$0",
            "source": "macro",
            "macro_name": "outer",
            "description": None,
            "source_path_display": None,
        },
    ]


def test_editor_helper_bridge_snippet_catalog_resolves_snippet_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "helper": Macro(
            name="helper",
            content="Help {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            snippet=True,
        ),
        "outer": Macro(
            name="outer",
            content="#[user_snip] {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            snippet=True,
        ),
    }
    _install_snippet_sources(
        monkeypatch,
        macros,
        {"user_snip": "User $1$0", "wrap": "#[helper(World)] $1$0"},
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert code == 0
    assert stderr.getvalue() == ""
    assert entries["outer"]["template"] == "User $1 $2$0"
    assert entries["wrap"]["template"] == "Help World $1$0"


def test_editor_helper_bridge_snippet_aliases_keep_provenance_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "foo": Macro(
            name="foo",
            content="foo {{ topic }}",
            inputs=[InputArg(name="topic", default=UNSET)],
            source_path="xprompts/foo.md",
            snippet=True,
            description="Foo source",
        )
    }
    _install_snippet_sources(
        monkeypatch,
        macros,
        {
            "wrap": "#[Foo] tail $1$0",
            "bad-trigger": "filtered before composition",
        },
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_editor_helper_bridge(
        argparse.Namespace(editor_helper_bridge_subcommand="snippet-catalog"),
        stdin=io.StringIO(json.dumps({"schema_version": 1})),
        stdout=stdout,
        stderr=stderr,
    )

    data = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert data["result"]["message"] == "loaded 4 snippet(s)"
    assert data["stats"] == {"total_count": 4}
    assert [entry["trigger"] for entry in data["entries"]] == [
        "Foo",
        "Wrap",
        "foo",
        "wrap",
    ]
    entries = {entry["trigger"]: entry for entry in data["entries"]}
    assert entries["Foo"] == {
        "trigger": "Foo",
        "template": "Foo $1$0",
        "source": "macro",
        "macro_name": "foo",
        "description": "Foo source",
        "source_path_display": "xprompts/foo.md",
    }
    assert entries["Wrap"] == {
        "trigger": "Wrap",
        "template": "Foo $1 tail $2$0",
        "source": "user_config",
        "macro_name": None,
        "description": None,
        "source_path_display": "ace.snippets",
    }
    assert entries["foo"]["template"] == "foo $1$0"
    assert entries["wrap"]["template"] == "Foo $1 tail $2$0"
    assert "bad-trigger" not in entries
