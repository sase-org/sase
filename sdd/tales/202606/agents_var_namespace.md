---
create_time: 2026-06-03 01:22:32
status: wip
prompt: sdd/prompts/202606/agents_var_namespace.md
---
# Plan: Move `sase var` Jinja Exposure Under `agents`

## Context

`sase var set` currently persists each agent's string variables in that agent's `agent_meta.json` under
`output_variables`. The TUI and artifact index already read that field directly, so the storage model does not need to
change.

The part to change is the cross-agent Jinja context:

- Multi-agent launches pass prior named agents through `SASE_AGENT_VAR_UPSTREAMS_JSON`.
- `build_agent_output_variable_context()` reads those upstream artifacts, plus explicitly waited agents, and currently
  returns top-level Jinja namespaces such as `build`, `research.final`, or `_0n.cld`.
- `_build_named_args()` merges those namespaces directly into workflow named args, which risks top-level collisions and
  requires every agent-derived namespace component to be a valid Jinja identifier.

The new desired shape is one top-level Jinja variable named `agents`.

## Recommended Semantics

Expose agent output variables as:

```jinja2
{{ agents["build"].result_path }}
{{ agents["research.final"].report_path }}
{{ agents["0n.cld"].status }}
```

Use a flat dictionary under `agents`, not nested dictionaries. The key should be the stable agent variable key:

- For a concrete `%name:foo`, key `foo`.
- For an indexed template `%name:build-@`, key `build`, preserving the current author-facing stable reference. Using the
  concrete runtime name such as `build-1` would make xprompts hard to write because the number is allocated at launch
  time and may vary across runs.
- For dotted names/templates, keep the dot in the key, such as `research.final`, and document bracket access.
- Do not normalize hyphens or digit-leading components just for Jinja identifier safety; bracket access allows raw
  string keys. This removes the need for `_0n`-style Jinja-safe names.

This deliberately changes the authoring contract from old top-level variables:

```jinja2
{{ build.result_path }}
```

to:

```jinja2
{{ agents["build"].result_path }}
```

I would not keep the old top-level aliases by default. They preserve the old collision surface and defeat the
simplification. If compatibility is needed, add a short-lived opt-in compatibility mode later, but make the default
contract the single `agents` object.

## Implementation Steps

1. Refactor `src/sase/agent/output_variable_context.py`.
   - Replace namespace-path terminology with agent-key terminology.
   - Add a helper that derives the stable key from `agent_name` and `agent_name_template`.
   - For indexed templates, use `indexed_agent_name_base(template)`.
   - For non-indexed agents, use the concrete agent name as-is.
   - Keep rejecting empty/missing keys, but stop requiring Jinja identifier components.
   - Build and return `{"agents": {agent_key: variables}}` when variables exist, or `{}` when no producers wrote
     variables.
   - Preserve current behavior where later upstreams override earlier values for the same stable key.

2. Update upstream record shape without breaking old env payloads abruptly.
   - Include a new field such as `agent_key` in `build_agent_var_upstream_record()`.
   - Continue accepting older records that only have `namespace`, `name`, and `agent_name_template`, deriving the key
     from the best available fields.
   - Tests can stop asserting that new records expose `namespace`, but the decoder should tolerate it for in-flight or
     older spawned agents.

3. Update `_build_named_args()` in `src/sase/axe/run_agent_exec.py`.
   - Treat the output-variable context as a normal named-arg fragment.
   - Add only the top-level `agents` key instead of spreading each producer namespace into named args.
   - Check for a collision with existing built-ins and fail clearly if another context source already tries to provide
     `agents`.

4. Keep persistence and TUI rendering unchanged.
   - `sase var set` should still write `agent_meta.json.output_variables`.
   - ACE should still render the selected agent's own output variables in the existing output-variable section.
   - The artifact index refresh remains necessary after mutation.

5. Update generated skill source and tests.
   - Edit `src/sase/xprompts/skills/sase_var.md`, not the generated live skill file.
   - Teach `agents["build"].result_path` and bracket access for dotted, hyphenated, and digit-leading names.
   - Update `tests/main/test_init_skills_sources.py` expected phrases.
   - After implementation, run `sase init-skills --force` only if the task is to refresh generated skill files in the
     workspace; otherwise leave generated chezmoi outputs alone per the generated-skills memory.

## Test Plan

Add or rewrite focused tests in `tests/test_agent_output_variable_context.py`:

- A named producer with variables renders as `{"agents": {"build": {"report_path": "reports/final.md"}}}`.
- `%name:build-@` still exposes the stable key `build`.
- Dotted indexed templates expose a flat key such as `research.final`.
- Digit-leading and dotted fan-out names expose raw keys such as `0n.cld`.
- Waited-agent fallback also contributes to `agents`.
- Later upstreams for the same key override earlier values.
- Empty or unreadable producers do not create empty entries.

Update launcher env tests in `tests/test_multi_prompt_launcher_launch_env.py`:

- Assert new upstream records include `agent_key`.
- Stop expecting Jinja-normalized `namespace` values for new records.
- Preserve the guarantee that later segments receive only prior named producers.

Update workflow rendering coverage:

- Change the existing rendered prompt assertion from `{{ build.report_path }}` to `{{ agents["build"].report_path }}`.
- Add a bracket-access case for a raw key that cannot be used as an attribute, such as `agents["0n.cld"].report_path`.

## Verification

After code changes in a later implementation turn:

```bash
just install
.venv/bin/python -m pytest -q \
  tests/test_agent_output_variable_context.py \
  tests/test_multi_prompt_launcher_launch_env.py \
  tests/main/test_var_handler.py \
  tests/main/test_init_skills_sources.py
just check
```

## Risks And Decisions

- The main behavior decision is indexed-template keys. The plan preserves the current stable key (`build`) instead of
  switching to concrete runtime keys (`build-1`). This keeps xprompts authorable and repeatable.
- Removing old top-level aliases is a breaking prompt-authoring change, but it is the cleanest way to get the requested
  single Jinja root and avoid namespace collisions.
- A workflow input named `agents` will now collide with this reserved runtime context name. Document `agents` as
  reserved in agent-run Jinja context.

## Non-Goals

- Do not change `sase var set` CLI syntax.
- Do not change `agent_meta.json.output_variables` persistence.
- Do not change ACE output-variable display behavior.
- Do not modify memory files.
- Do not hand-edit generated live skill files.
