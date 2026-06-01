---
create_time: 2026-06-01 10:04:16
status: done
prompt: sdd/prompts/202606/sdd_init_config.md
---
# Plan: `sase sdd init` Enables Version-Controlled SDD

## Context

`sase sdd init` currently creates or refreshes generated SDD guide files only:

- `sdd/README.md`
- tier README files under `sdd/{tales,epics,legends,myths,research}/`
- `sdd/assets/sdd-directory-map.png`

The command is implemented in `src/sase/main/sdd_handler.py`; its read-only planner is also used by
`sase sdd init --check`, `sase init sdd --check`, and the shared onboarding check flow.

The lower-level `sase.sdd.files.ensure_sdd_initialized()` helper is used by internal bare-git/workspace flows, so the
config-writing behavior should live at the CLI init boundary rather than being added to that lower-level helper.

## Desired Behavior

`sase sdd init` and its `sase init sdd` alias should ensure the project-local `sase.yml` contains:

```yaml
sdd:
  version_controlled: true
```

Specific cases:

- If no project-local `sase.yml` exists, create one with the `sdd.version_controlled` setting.
- If `sase.yml` exists but lacks `sdd`, append the `sdd` section.
- If `sase.yml` has `sdd` but lacks `version_controlled`, insert the field under `sdd`.
- If `sase.yml` has `sdd.version_controlled: false`, update that value to `true`.
- If it is already true, do nothing.
- If the config is invalid YAML, not a mapping, or has a non-mapping `sdd` value, report a blocker/error rather than
  clobbering user config.

The default config should remain `sdd.version_controlled: false`; this command is an explicit per-project opt-in.

## Implementation Approach

1. Add a focused SDD init config helper.
   - Compute the project-local `sase.yml` path using the same `-p/--path` semantics as SDD init: project-root paths map
     to `<project>/sase.yml`; `sdd` root paths map to their project root; `.sase/sdd` maps back to the containing
     project root.
   - Parse existing YAML with PyYAML for semantic validation and current-value detection.
   - Preserve existing config formatting as much as practical by doing a narrow text update/insert for only the
     `sdd.version_controlled` field instead of dumping the entire config and losing comments/order.

2. Wire the helper into `src/sase/main/sdd_handler.py`.
   - `plan_sdd_init()` should include a config `InitAction` when `sase.yml` needs creation or update, and include
     blockers for invalid config.
   - `run_sdd_init()` should refuse to write when config blockers exist, then apply the config change and refresh the
     generated SDD files.
   - Keep `ensure_sdd_initialized()` behavior unchanged for internal auto-init callers.

3. Update user-facing text.
   - Adjust SDD init summaries/help/docs where they currently say the command only refreshes README files and the
     directory map.
   - Keep the existing short command output stable unless tests or UX require printing the config path too.

4. Add focused tests.
   - Missing `sase.yml`: command creates it with `sdd.version_controlled: true` and creates generated SDD files.
   - Existing `sase.yml` without `sdd`: command preserves existing content and adds the section.
   - Existing `sase.yml` with `sdd.version_controlled: false`: command updates it to true.
   - Existing `sase.yml` already true: planner reports no config action.
   - `--check`: reports missing/stale config without writing it.
   - Invalid/non-mapping config: planner/check reports a blocker and run exits non-zero without overwriting.
   - Alias coverage remains valid through `sase init sdd`.

5. Verification.
   - Run the focused SDD init tests first.
   - Run `just install` if needed, then `just check` after file changes as required by repo instructions.
