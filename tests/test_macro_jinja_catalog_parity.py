"""Runtime/catalog parity for the Rust Jinja engine.

The static catalog behind :mod:`sase.macro.jinja_assist` is the single
source of truth for completion, lint, and input inference. These tests tie
it to the live Jinja environments and to every name agent runs can inject,
so a new filter or a new injected name fails loudly here instead of
drifting.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from sase.axe.run_agent_exec import _build_named_args
from sase.macro._jinja import get_jinja_env
from sase.macro.jinja_assist import jinja_catalog
from sase.macro.runtime_context import (
    bind_runtime_template_vars,
    get_runtime_template_vars,
)
from sase.macro.workflow_executor_utils import create_jinja_env
from tests._agent_output_variable_context_fixtures import make_consumer_context


def _identifiers(mapping: Any) -> set[str]:
    return {key for key in mapping if isinstance(key, str) and key.isidentifier()}


def test_catalog_filters_match_prompt_environment() -> None:
    catalog = jinja_catalog()
    assert {item.name for item in catalog.filters} == _identifiers(
        get_jinja_env().filters
    )


def test_catalog_tests_match_prompt_environment() -> None:
    catalog = jinja_catalog()
    assert {item.name for item in catalog.tests} == _identifiers(get_jinja_env().tests)


def test_catalog_globals_match_prompt_environment() -> None:
    catalog = jinja_catalog()
    assert {item.name for item in catalog.jinja_globals} == _identifiers(
        get_jinja_env().globals
    )


def test_workflow_environment_filters_stay_within_catalog() -> None:
    catalog_names = {item.name for item in jinja_catalog().filters}
    assert _identifiers(create_jinja_env().filters) <= catalog_names


def test_catalog_statements_need_no_jinja_extensions() -> None:
    statements = {item.name for item in jinja_catalog().statements}
    assert statements.isdisjoint({"do", "break", "continue"})
    get_jinja_env().parse(
        "{% for x in y %}{% if x %}{% set z = 1 %}"
        "{% macro m(a) %}{{ a }}{% endmacro %}"
        "{% call m(1) %}{% endcall %}"
        "{% filter upper %}hi{% endfilter %}"
        "{% with a=1 %}{{ a }}{% endwith %}"
        "{% block b %}body{% endblock %}"
        "{% raw %}{{ x }}{% endraw %}"
        "{% endif %}{% endfor %}"
    )


def test_named_args_are_catalog_variables(monkeypatch) -> None:
    monkeypatch.delenv("SASE_REPEAT_ITERATION", raising=False)
    monkeypatch.delenv("SASE_REPEAT_TOTAL", raising=False)
    ctx = make_consumer_context({"agents": {"build": {"path": "b.md"}}})
    names = set(_build_named_args(ctx))
    names.update(_build_named_args(dataclasses.replace(ctx, wait_chats=["a.md"])))
    assert names == {"patch_name", "cl_name", "workspace_num", "agents", "wait_chats"}
    catalog_names = {variable.name for variable in jinja_catalog().variables}
    assert names <= catalog_names


def test_repeat_env_names_are_catalog_variables(monkeypatch) -> None:
    monkeypatch.setenv("SASE_REPEAT_ITERATION", "2")
    monkeypatch.setenv("SASE_REPEAT_TOTAL", "5")
    names = set(_build_named_args(make_consumer_context({})))
    assert {"n", "N"} <= names
    catalog_names = {variable.name for variable in jinja_catalog().variables}
    assert {"n", "N"} <= catalog_names


def test_internal_workflow_args_are_never_catalog_variables() -> None:
    ctx = dataclasses.replace(make_consumer_context({}), vcs_tag="vcs:tag")
    names = set(_build_named_args(ctx))
    internal = {name for name in names if name.startswith("__")}
    assert internal, "expected an internal workflow arg fixture"
    catalog_names = {variable.name for variable in jinja_catalog().variables}
    assert internal.isdisjoint(catalog_names)


def test_every_run_catalog_variable_is_emitted(monkeypatch, tmp_path) -> None:
    catalog = jinja_catalog()
    run_names = {
        variable.name
        for variable in catalog.variables
        if variable.availability_rule == "run"
    }
    assert run_names == {"wait", "patch_name", "workspace_num", "cl_name"}

    emitted = set(_build_named_args(make_consumer_context({})))
    with bind_runtime_template_vars({"wait": object()}):
        emitted.update(get_runtime_template_vars())
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace", lambda: tmp_path
    )
    from sase.macro._jinja import get_global_template_vars

    emitted.update(get_global_template_vars())
    assert get_global_template_vars()["root"] == str(tmp_path)
    assert run_names <= emitted
