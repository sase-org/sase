---
create_time: 2026-05-14 13:15:41
status: done
prompt: sdd/prompts/202605/config_schema_coverage.md
---
# Config Schema Coverage Plan

## Context

`src/sase/default_config.yml` is the bundled baseline for user configuration, while `config/sase.schema.json` is the
editor/validation contract for `sase.yml`. The schema currently rejects the bundled default config because several
runtime-supported defaults are missing from the schema:

- Top-level `mobile_gateway`.
- `ace.repro_output_dir`.
- `axe.lumberjack_log_max_bytes` and `axe.verbose_lumberjack_diagnostics`.
- Daemon lifecycle fields: `command`, `sase_home`, `run_root`, `socket_path`, `disable_mobile_http`, and
  `startup_timeout_seconds`.
- Daemon rollout/scheduler fields: `rollout.milestones.*`, `scheduler.launch_mode`, `scheduler.lifecycle_mode`, and
  `scheduler.axe_mode`.
- Newer daemon read surfaces: `ace_changespecs`, `ace_notifications`, `ace_artifacts`, and `ace_archive_search`.

## Approach

1. Update `config/sase.schema.json` to define the missing fields with types and defaults that match runtime loaders and
   documentation, keeping `additionalProperties: false` for closed sections.
2. Model scheduler modes with the canonical config values used by docs and defaults: `direct`, `shadow`, and `daemon`
   for launch/lifecycle; `direct` and `daemon` for axe.
3. Model provider and gateway path/command override fields as strings, matching the current YAML defaults and loader
   normalization behavior.
4. Add a focused regression test that loads `src/sase/default_config.yml`, loads `config/sase.schema.json`, checks the
   schema itself, and asserts that the default config has no validation errors.
5. Verify with the targeted test, then run the repository-required `just install` and `just check` because source files
   changed.

## Non-Goals

- Do not change runtime config loading behavior.
- Do not broaden schema sections to accept arbitrary unknown fields.
- Do not modify memory files or unrelated documentation.
