---
create_time: 2026-06-03 01:31:36
status: done
prompt: sdd/prompts/202606/agents_var_namespace_1.md
---
# Plan: Expose `sase var` Output Variables Under a Single `agents` Jinja Dictionary

## Problem & Product Context

The recently-added `/sase_var` command lets one agent in a multi-agent xprompt publish small string values
(`sase var set KEY=VALUE`) that a later agent can read in its prompt via Jinja. Today each producing agent is injected
as its **own top-level Jinja variable** named after the agent's stable namespace:

```jinja2
{{ build.result_path }}
{{ research.final.report_path }}
{{ _0n.cld.status }}
```

This has two problems:

1. **Collision surface.** Every producer namespace is spread directly into the workflow's top-level named args
   (`_build_named_args`), so any agent name can shadow or collide with a built-in arg (`cl_name`, `workspace_num`, `n`,
   `N`, etc.). The code already has to guard each key against collisions.
2. **Identifier gymnastics.** Because each namespace becomes a top-level _attribute_, every component must be coerced
   into a valid Jinja identifier: hyphens become underscores and digit-leading components get an `_` prefix (`0n` →
   `_0n`). This is surprising to authors and leaks naming rules into the template contract.

The request: store **all** agent variables for a multi-agent xprompt under a single Jinja variable named `agents` — a
dictionary keyed by agent name — to simplify injection and remove the top-level collision/identifier problems.

New authoring contract:

```jinja2
{{ agents["build"].result_path }}
{{ agents["research.final"].report_path }}
{{ agents["0n.cld"].status }}
```

## Recommended Semantics

- Expose exactly **one** top-level Jinja variable, `agents`, which is a **flat** dictionary. Keys are agent names;
  values are that agent's `{KEY: VALUE}` output-variable map.
- Key derivation (the "agent key") stays consistent with today's _stable_ reference, so xprompts remain authorable and
  repeatable across runs:
  - Concrete `%name:foo` → key `foo`.
  - Indexed template `%name:build-@` → key `build` (the template base, **not** the launch-time `build-1`). The launch
    index is allocated at runtime and would make prompts fragile.
  - Dotted names/templates keep the dot in the key: `%name:research.final-@` → key `research.final`. Accessed with
    bracket syntax `agents["research.final"]`.
- **Drop the Jinja-identifier normalization** (`-`→`_`, digit-prefix `_`). Because `agents` is a dict accessed by string
  subscript, raw keys like `0n.cld` or `build-agent` are valid keys. This removes the `_0n`-style names entirely. Plain
  attribute access (`agents.build`) still works for identifier-safe keys; bracket access covers the rest.
- Later producers override earlier ones for the same key (unchanged merge precedence).
- When no producer wrote any variable, `agents` is simply absent from the context (no empty dict injected), preserving
  today's "nothing to render" behavior.

### Trade-off: flat keys vs. nested dicts

Flat keys (`agents["research.final"]`) are recommended over nested dicts (`agents.research.final`) because the request
explicitly asks for "keys for each agent name," and flat keys make the dictionary a faithful 1:1 map of agent-name →
variables. Nested dicts would re-introduce the per-component identifier concerns we are trying to delete. This is the
main design decision and is called out for review.

### Backward compatibility

I recommend **not** keeping the old top-level aliases. The feature is new (introduced on this branch), retaining aliases
preserves the exact collision surface we are removing, and dual exposure defeats the simplification. If compatibility is
later required, it can be added as a short-lived opt-in. Surfacing this as a deliberate breaking change to the (new,
unreleased) authoring contract.

## High-Level Technical Design

The storage model does **not** change: `sase var set` keeps writing `agent_meta.json.output_variables`, and ACE keeps
rendering each agent's own variables. Only the **cross-agent Jinja context assembly** changes.

1. **`src/sase/agent/output_variable_context.py`** — the heart of the change.
   - Replace "namespace path" terminology/logic with a single **agent-key** derivation helper that returns one string
     key from `agent_name` + `agent_name_template` (indexed-template base for `-@`, otherwise the concrete/dotted name
     as-is). Stop splitting on `.` and stop validating Jinja-identifier components.
   - `build_agent_output_variable_context()` returns `{"agents": {key: variables, ...}}` when any producer wrote
     variables, else `{}`. Merge upstream records and waited-agent fallbacks into the same flat `agents` map, preserving
     later-overrides-earlier precedence.
   - `build_agent_var_upstream_record()` includes a new `agent_key` field. The decoder should still tolerate older
     payloads that only carry `name`/`agent_name_template`/`namespace` (in-flight spawned agents), deriving the key from
     the best available fields.

2. **`src/sase/axe/run_agent_exec.py` (`_build_named_args`)**
   - Stop spreading each producer namespace into top-level named args. Instead inject the single `agents` key from the
     context, with one collision check: fail clearly if another context source already provides `agents`. Document
     `agents` as a reserved agent-run Jinja name.

3. **`src/sase/axe/run_agent_runner.py` / `run_agent_exec_types.py`**
   - Plumbing only. The `AgentExecContext.output_variable_namespaces` field can keep its name or be renamed (e.g.
     `output_variable_context`); it now carries the `{"agents": {...}}` fragment. Keep changes minimal and internal.

4. **Skill source `src/sase/xprompts/skills/sase_var.md`**
   - Rewrite the rendering examples to `{{ agents["build"].result_path }}`, show bracket access for dotted / hyphenated
     / digit-leading names, and drop the `_0n`/hyphen-normalization guidance.
   - Edit the **source** skill file only; do not hand-edit generated live skill outputs. Run `sase init-skills --force`
     only if the explicit task is to refresh generated skill files.

5. **Docs** — update any `docs/*.md` that demonstrate `{{ build.* }}` output-variable rendering to the `agents[...]`
   form, and note `agents` as a reserved name.

## Test Plan

Rewrite `tests/test_agent_output_variable_context.py`:

- Named producer → `{"agents": {"build": {"report_path": "reports/final.md"}}}`.
- `%name:build-@` exposes stable key `build`.
- Dotted indexed template exposes flat key `research.final`.
- Digit-leading / dotted fan-out exposes raw key `0n.cld` (no `_0n` munging).
- Waited-agent fallback contributes into `agents`.
- Later upstream overrides earlier value for same key.
- Empty/unreadable producers create no `agents` entry.
- `_build_named_args` injects a single `agents` arg and raises on `agents` collision.
- Workflow rendering: change the integration assertion from `{{ build.report_path }}` to
  `{{ agents["build"].report_path }}`, and add a bracket-access case for a raw key that cannot be an attribute
  (`agents["0n.cld"].report_path`).

Update `tests/test_multi_prompt_launcher_launch_env.py`:

- Assert new upstream records include `agent_key`; stop asserting Jinja-normalized `namespace`.
- Preserve the guarantee that later segments only receive prior named producers.

Update `tests/main/test_init_skills_sources.py` expected phrases to match the new skill copy.

## Verification

```bash
just install
.venv/bin/python -m pytest -q \
  tests/test_agent_output_variable_context.py \
  tests/test_multi_prompt_launcher_launch_env.py \
  tests/main/test_var_handler.py \
  tests/main/test_init_skills_sources.py
just check
```

## Risks & Decisions

- **Indexed-template key** stays the template base (`build`), not the runtime `build-1`, to keep prompts repeatable.
  (Primary behavior decision.)
- **Flat vs nested** `agents` dict — recommending flat keys keyed by full agent name.
- **Breaking change**: removing top-level aliases changes the authoring contract for this new feature; recommended for
  cleanliness, opt-in compat deferrable.
- **`agents` is now reserved** in agent-run Jinja context; a workflow input named `agents` will collide and fail
  clearly.

## Non-Goals

- No change to `sase var set` CLI syntax.
- No change to `agent_meta.json.output_variables` persistence.
- No change to ACE output-variable display.
- No memory-file edits.
- No hand-editing of generated live skill files.
