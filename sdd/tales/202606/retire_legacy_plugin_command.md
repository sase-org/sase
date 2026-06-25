---
create_time: 2026-06-25 14:39:09
status: done
prompt: sdd/prompts/202606/retire_legacy_plugin_command.md
---
# Retire the Legacy `sase plugin` Command

## Context

The current `sase plugin` command is a mixed diagnostic surface. It inventories Python entry points, installed package
distributions, configured AXE chops, available unconfigured chop scripts, resource entry-point import errors, GitHub CLI
readiness, and Telegram chop prerequisites. That makes the command name misleading: it does not focus on SASE pluggy
provider plugins, and a future rewrite should be free to make `sase plugin` mean "inspect and operate on pluggy plugins"
without preserving this mixed behavior.

Static inspection found the current behavior in:

- `src/sase/main/parser_plugin.py` and `src/sase/main/plugin_handler.py`: public `sase plugin list|doctor` command.
- `src/sase/plugins/inventory.py`: SASE entry-point metadata and resource entry-point load status.
- `src/sase/plugins/chops.py`: configured AXE chop resolution plus executable `sase_chop_*` discovery.
- `src/sase/plugins/doctor.py`: aggregated checks for resource load failures, missing/unconfigured chops, GitHub CLI,
  and Telegram prerequisites.
- `src/sase/plugins/render.py`: Rich output tailored to the legacy command.
- `src/sase/doctor/checks_plugins.py`: an existing top-level `sase doctor` adapter around the legacy plugin doctor.
- `src/sase/version/*`: existing runtime/package inventory that already reports installed plugin packages and plugin
  signals without loading plugin code.
- `src/sase/axe/cli.py` and `src/sase/main/parser_ace.py`: existing `sase axe chop list|run` surface, currently too
  sparse for chop diagnostics.

`uv run` is currently blocked in this workspace by a lockfile parse error for `sase-core-rs`, so implementation should
use the repo's documented `just install` / `just check` flow after edits rather than assuming `uv run` works.

## Goals

- Remove the current `sase plugin` CLI registration and handler so a future agent can reintroduce the command with a
  pluggy-focused design.
- Preserve only the legacy command behavior that is practically useful and has a clearer home elsewhere.
- Move chop inventory and chop setup diagnostics to `sase axe chop`, because chops are AXE automation, not pluggy
  plugins.
- Keep installed package/plugin package inventory under `sase version`, because that command already owns runtime
  inventory.
- Keep resource plugin loading diagnostics and provider integration prerequisite checks under `sase doctor`, because
  they are support diagnostics.
- Update tests and docs so there is no user-facing `sase plugin` command until the planned rewrite.

## Non-Goals

- Do not design the future pluggy-focused `sase plugin` command.
- Do not add plugin install/update/enable/disable workflows.
- Do not preserve full legacy JSON compatibility for `sase plugin list|doctor`; the command is intentionally retired.
- Do not modify memory files.

## Migration Decisions

| Legacy behavior                                                   | Keep?     | New home                                                                                                         |
| ----------------------------------------------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------- |
| Installed plugin package inventory                                | Yes       | Existing `sase version` / `sase version -v` / `sase version -j`                                                  |
| Raw SASE entry-point listing                                      | Mostly no | Keep only support-oriented data in `sase doctor`; future `sase plugin` rewrite can define the proper pluggy view |
| Resource entry-point load failures and disabled resource env vars | Yes       | `sase doctor`, likely a dedicated `plugins.resources` check                                                      |
| GitHub plugin `gh` CLI/auth probe                                 | Yes       | `sase doctor`, as a provider/plugin prerequisite check                                                           |
| Configured chop status and script path resolution                 | Yes       | `sase axe chop list` and `sase axe chop doctor`                                                                  |
| Available unconfigured chop script discovery                      | Yes       | `sase axe chop list --available` and `sase axe chop doctor`                                                      |
| Telegram chop env/pass prerequisites                              | Yes       | `sase axe chop doctor`, because Telegram is currently chop-script based                                          |
| Legacy Rich panels titled "SASE Plugins" / "Plugin Doctor"        | No        | Delete with the legacy command-specific renderer                                                                 |

## Proposed CLI Shape

1. `sase plugin`
   - Remove from the top-level parser and entry dispatcher.
   - Remove default-list behavior for `sase plugin`.
   - Leave no compatibility alias; this keeps the namespace clean for the upcoming rewrite.

2. `sase version`
   - Keep existing behavior as the package inventory destination.
   - Update docs to point users from old package/plugin-inventory use cases to `sase version -v` or `sase version -j`.
   - Avoid expanding `sase version` into entry-point health diagnostics.

3. `sase doctor`
   - Replace the current monolithic legacy adapter with clearer checks:
     - `plugins.resources`: resource entry-point load failures and resource-plugin disable environment variables.
     - A provider prerequisite check for GitHub CLI/auth when GitHub VCS/workspace entry points are installed.
     - `axe.chops`: missing configured script chops, available unconfigured scripts, and Telegram chop prerequisites.
   - Keep default doctor behavior read-only and bounded.
   - Keep JSON data useful enough for support reports, but do not attempt to recreate the full legacy `sase plugin` JSON
     payload.

4. `sase axe chop`
   - Extend `list` with:
     - `-a, --available`: include discoverable executable chop scripts, especially unconfigured scripts.
     - `-j, --json`: emit stable schema-versioned JSON.
     - `-v, --verbose`: include descriptions, resolution paths, search dirs, and source detail.
   - Add `doctor` with:
     - `-j, --json`.
     - `-v, --verbose`.
     - exit code `1` for ERROR, `0` for OK/WARN/SKIP, matching existing `sase plugin doctor` warning semantics.
   - Keep `run` unchanged except for parser/help ordering around the new `doctor` child.

## Implementation Plan

1. Restructure the reusable diagnostics code.
   - Move chop inventory dataclasses and collection helpers from `sase.plugins.chops` to an AXE-owned module, for
     example `sase.axe.chop_inventory`.
   - Move chop check construction out of `sase.plugins.doctor` into AXE/doctor-owned helpers so top-level doctor and
     `sase axe chop doctor` share the same logic.
   - Move SASE entry-point group constants and resource-entry-point inventory helpers to a neutral diagnostics or plugin
     metadata module, avoiding command-specific `sase plugin` naming.
   - Delete the command-specific Rich renderer once no new command imports it.

2. Implement the new AXE chop surface.
   - Update `register_axe_parser()` so `sase axe chop` has sorted children `{doctor,list,run}`.
   - Add sorted public flags with short aliases for `list` and `doctor`.
   - Update `handle_axe_chop_list()` to render per-lumberjack configured chop rows with status/kind/resolution instead
     of only de-duplicated names.
   - Add `handle_axe_chop_doctor()` for missing configured scripts, unconfigured available scripts, and Telegram
     prerequisite checks.
   - Keep `sase axe chop run` behavior unchanged.

3. Split top-level doctor checks.
   - Replace `plugins.doctor` with more specific checks such as `plugins.resources` and `axe.chops`.
   - Keep GitHub CLI/auth probing in top-level doctor, but separate it from chop diagnostics.
   - Update doctor list/help/tests to use the new check IDs.
   - Keep selected-check behavior predictable: old `plugins.doctor` does not need to remain as a compatibility alias
     unless implementation finds other internal dependencies.

4. Remove the legacy command.
   - Delete parser registration and entry dispatch for `plugin`.
   - Delete `src/sase/main/parser_plugin.py` and `src/sase/main/plugin_handler.py`.
   - Delete or shrink `src/sase/plugins/*` once helpers have moved; keep only neutral reusable plugin metadata if still
     needed by `sase version` or doctor.
   - Update parser default-list tests so `sase plugin` is no longer expected.

5. Update documentation.
   - Remove `sase plugin` rows from `docs/cli.md` and `docs/configuration.md`.
   - Rewrite `docs/plugins.md` to describe the plugin system and route diagnostics to:
     - `sase version -v` for installed runtime/plugin packages.
     - `sase doctor -C plugins.resources` and provider checks for resource/provider diagnostics.
     - `sase axe chop list|doctor` for chop scripts and Telegram chop setup.
   - Update blog mentions that recommend `sase plugin doctor` to recommend the new diagnostics, or remove the old
     command from command tables.

6. Update tests.
   - Replace `tests/main/test_plugin_command.py` with targeted tests for:
     - AXE chop inventory collection.
     - `sase axe chop list --json`, `--available`, and verbose rendering.
     - `sase axe chop doctor` statuses and exit codes.
     - resource/plugin doctor checks under top-level `sase doctor`.
   - Update `tests/doctor/test_checks_plugins.py`, `tests/main/test_doctor_command.py`, and diagnostics model examples
     for the new check IDs.
   - Update parser tests for top-level command sorting, default-list groups, and `sase axe chop` child sorting.
   - Keep existing `sase version` plugin inventory tests as the package-inventory coverage.

7. Verify.
   - Run focused parser/doctor/AXE/version tests first:
     ```bash
     pytest tests/main/test_parser_command_defaults.py tests/main/test_doctor_command.py tests/doctor/test_checks_plugins.py tests/main/test_version_command.py tests/test_version_inventory_plugins.py
     pytest tests/test_axe_cli.py tests/test_axe_chop_runner_find.py tests/test_axe_chop_script_runner.py
     ```
   - Run `just install` if the workspace dependencies need refreshing, then `just check` because code and docs will have
     changed.
   - Finish with exact searches:
     ```bash
     rg -n "sase plugin|plugin_handler|parser_plugin|plugins\\.doctor|plugins\\.chops|Plugin Doctor|SASE Plugins" src tests docs README.md
     ```
     Remaining hits should be conceptual plugin-system docs only, not the retired command.

## Risks and Mitigations

- Risk: deleting `sase plugin` may surprise users who relied on `sase plugin doctor`. Mitigation: docs should point to
  `sase doctor` and `sase axe chop doctor`, and the future command rewrite can reclaim the namespace cleanly.
- Risk: top-level doctor may duplicate checks if the old monolithic adapter and new split checks coexist. Mitigation:
  replace the adapter instead of registering both by default.
- Risk: richer `sase axe chop list` output changes scripts that parse the old human output. Mitigation: provide `--json`
  for scripts and treat the old human output as non-contractual.
- Risk: moving modules can break `sase.version` plugin candidate discovery because it imports entry-point group
  constants from `sase.plugins.inventory`. Mitigation: move constants first and update version tests before deleting old
  modules.
- Risk: Telegram checks are integration-specific and may feel too bespoke. Mitigation: keep them only because they
  already exist and are tied to executable chop discovery; do not add broader integration logic.
