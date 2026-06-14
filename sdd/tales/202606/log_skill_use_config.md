---
create_time: 2026-06-14 12:48:26
status: done
prompt: sdd/prompts/202606/log_skill_use_config.md
---
# Plan: Configurable Generated Skill-Use Audit Directive

## Objective

Add a `log_skill_use` boolean xprompt config/frontmatter field that controls whether `sase skills init` injects the
generated first-step `sase skills log <name> --reason ...` directive into a generated `SKILL.md`.

The default must be `true` so existing xprompt skills keep current behavior. Set `log_skill_use: false` for the packaged
`/sase_plan` and `/sase_memory_read` skill sources so those two generated skills no longer instruct agents to log their
own use.

## Current Shape

- Generated skill files are rendered from xprompt sources, primarily `src/sase/xprompts/skills/*.md`, by
  `src/sase/main/init_skills_handler.py`.
- The audit directive is currently injected unconditionally in `_build_output()`, which only receives `name`, rendered
  description, and rendered body.
- Xprompt metadata is represented by `sase.xprompt.models.XPrompt` and populated from Markdown frontmatter in
  `loader_sources.py`, from config entries in `loader_parsing.py`, and copied through helper paths such as
  `namespace_xprompt()`.
- `config/sase.schema.json` uses `additionalProperties: false` for structured `xprompts` entries, so config-defined
  xprompt skills need the new field added to the public schema.
- Generated `SKILL.md` files must be refreshed from source with `sase skills init`; deployed chezmoi/live files should
  not be hand-edited.

## Implementation Steps

1. Extend the xprompt model.
   - Add `log_skill_use: bool = True` to `XPrompt`.
   - Preserve this field when copying/namespacing xprompts, especially `namespace_xprompt()`.
   - Leave non-skill xprompts with the same default; the flag only affects generation when `skill` is truthy.

2. Parse the new field from both supported xprompt source shapes.
   - Markdown/frontmatter sources: read `log_skill_use` from frontmatter with default `True`.
   - Plugin Markdown sources: same behavior as packaged/user Markdown files.
   - Config structured xprompts: read `log_skill_use` from the entry dict with default `True`.
   - Simple string config entries keep the default `True`.
   - Keep parsing conservative: only real YAML/JSON booleans should be documented and tested. If existing parser
     conventions do not validate field types, avoid introducing broad validation churn in this change.

3. Make directive injection conditional.
   - Change `_build_output()` to accept `log_skill_use: bool = True`.
   - In `_render_skill_targets()`, pass `xprompt.log_skill_use`.
   - Build output as frontmatter + blank line + optional directive + rendered body.
   - Keep existing formatting behavior and Prettier batching unchanged.

4. Update packaged skill sources.
   - Add `log_skill_use: false` to `src/sase/xprompts/skills/sase_plan.md`.
   - Add `log_skill_use: false` to `src/sase/xprompts/skills/sase_memory_read.md`.
   - Do not add or remove audit text manually in the source bodies; the generator remains the source of that behavior.

5. Update schema and docs.
   - Add `log_skill_use` to `config/sase.schema.json` structured `xprompts` properties as a boolean with default `true`.
   - Add schema regression coverage for config-defined xprompts using `log_skill_use: false`.
   - Update `docs/xprompt.md` Skill Field docs to explain that generated skills include the audit directive by default
     and `log_skill_use: false` disables it.
   - Update `docs/configuration.md` and `docs/init.md` wording from unconditional to default/conditional behavior.

6. Add focused tests.
   - Loader tests:
     - Markdown frontmatter preserves `log_skill_use: false`.
     - Markdown/frontmatter and config entries default to `True` when absent.
     - Structured config entries parse `log_skill_use: false`.
   - Generator tests:
     - Existing default case still includes the audit directive for all target providers.
     - A skill xprompt with `log_skill_use=False` omits the directive and still includes the rendered body.
     - Packaged `/sase_plan` and `/sase_memory_read` sources render without the directive, while a representative
       default packaged skill still renders with it.
   - Schema tests:
     - `config/sase.schema.json` accepts `log_skill_use: false` on structured xprompt config.

7. Regenerate generated skill files after code/tests/docs are updated.
   - Use the local build command from this workspace, likely `.venv/bin/sase skills init --force --no-commit`,
     respecting the repo's configured `use_chezmoi` mode.
   - If `use_chezmoi` is active, run `chezmoi apply` after source generation so live provider skill files match
     generated source.
   - Verify the generated inventory reports current targets, not stale/missing files.

8. Validate.
   - Run focused tests first:
     - `.venv/bin/pytest tests/test_xprompt_loader_parsing.py tests/test_xprompt_loader_config.py tests/test_config_schema.py tests/main/test_init_skills_handler.py tests/main/test_init_skills_sources.py tests/main/test_init_skills_plan.py tests/main/test_init_skills_formatting.py`
   - Run formatting/lint through the repo standard path.
   - Run `just check` before final handoff if feasible.

## Risks And Mitigations

- Risk: treating this as a generator-only change would miss config-defined skill sources. Mitigation: carry
  `log_skill_use` on `XPrompt` and parse it from both frontmatter and structured config.
- Risk: stale generated `SKILL.md` files would continue showing old directives for `/sase_plan` and `/sase_memory_read`.
  Mitigation: regenerate and apply generated skill files after implementation.
- Risk: schema users could not set the new field in `sase.yml`. Mitigation: update `config/sase.schema.json` and add
  schema coverage.
- Risk: broader validation churn could reject existing loose configs. Mitigation: document the field as boolean, test
  booleans, and avoid unrelated parser strictness changes.
