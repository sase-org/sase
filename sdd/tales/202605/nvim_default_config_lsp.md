---
create_time: 2026-05-14 12:56:31
status: wip
prompt: sdd/prompts/202605/nvim_default_config_lsp.md
---
# Diagnose and fix Neovim LSP support for `src/sase/default_config.yml`

## Context

Opening `src/sase/default_config.yml` should get useful YAML LSP behavior from `yamlls`, including the SASE config
schema published by the main `sase` repo and configured by the `../sase-nvim` plugin. The user has `sase-nvim` installed
and the Neovim config lives in the chezmoi repo.

Initial inspection shows:

- The chezmoi Neovim config installs `sase-org/sase-nvim`, enables `yamlls`, and leaves SASE schema associations to
  `sase-nvim`.
- `../sase-nvim/plugin/sase_yamlls.lua` associates the config schema only with `**/sase.yml` and `**/sase_*.yml`.
- `src/sase/default_config.yml` is the canonical checked-in default config template, but it does not match either config
  schema glob.

## Plan

1. Verify the live Neovim state for `src/sase/default_config.yml`.
   - Open the file in headless Neovim with the user config.
   - Confirm the buffer filetype, attached LSP clients, and the effective `yamlls` schema settings.
   - Distinguish between "yamlls is not attaching" and "yamlls attaches but lacks the SASE schema for this file".

2. Patch the correct owner.
   - Prefer changing `../sase-nvim` because it owns automatic `yamlls` schema associations.
   - Add the canonical `**/src/sase/default_config.yml` path to the SASE config schema globs.
   - Avoid changes to user-specific Neovim config unless the live check shows the plugin is not loading or not using the
     maintained local source.

3. Add focused regression coverage in `../sase-nvim`.
   - Add or update a lightweight Lua test for the schema association list so future changes do not drop
     `default_config.yml`.
   - Keep the test independent of a running `yamlls` process where practical.

4. Verify.
   - Run the `sase-nvim` test/check command available in that repo.
   - Re-run the headless Neovim probe to confirm `src/sase/default_config.yml` is covered by the SASE config schema.
   - If any chezmoi files are edited, run `just check` in the chezmoi repo and apply the changes with
     `chezmoi apply --force`; otherwise leave chezmoi untouched.

## Expected outcome

The root cause should be a missing schema glob in `sase-nvim`, not a missing server binary. After the fix, `yamlls`
should still attach to YAML buffers as before, and `src/sase/default_config.yml` should receive the same SASE config
schema association as runtime `sase.yml` and `sase_*.yml` files.
