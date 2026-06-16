---
create_time: 2026-06-15 19:41:39
status: done
prompt: sdd/prompts/202606/remove_memory_episodes.md
---
# Remove Memory Episodes Command

## Objective

Revert the memory episodes feature so SASE no longer exposes or runs the `sase memory episodes` command family. The user
called this `sase memory episode`; the active command in the tree is plural, so this plan removes the plural command and
any singular/episode-specific active references discovered during implementation.

## Scope

- Remove the public CLI surface: parser registration, dispatcher branch, help examples, and all
  `src/sase/memory/cli_episodes*.py` handlers.
- Remove the episode implementation package under `src/sase/memory/episodes/` and its Python wire/facade layer under
  `src/sase/core/episode_*.py`.
- Remove the Rust-core episode API from the matching `sase-core_11` workspace: `crates/sase_core/src/episode/`, public
  re-exports, PyO3 bindings, and Rust parity tests.
- Remove automation hooks: `sase_chop_memory_episodes` console script, `src/sase/scripts/sase_chop_memory_episodes.py`,
  the wrapper in `src/sase/scripts/__init__.py`, and the chezmoi `memory_episodes` chop block in
  `home/dot_config/sase/sase_athena.yml`.
- Remove hidden runtime integration that depends on episodes: opt-in prompt recall via `SASE_MEMORY_EPISODES_RECALL` and
  the episode-specific `episode_trace.json` marker writer/call sites if they are still used only by episode collection.
- Remove the ACE Episode Explorer: modal files, modal exports, TCSS block, `open_episode_explorer` action, default
  binding, configurable keymap field, command-palette entry, and help-modal rows.
- Remove the deep `sase doctor` memory episode check and unregister it from the doctor registry.
- Update user-facing documentation and navigation: README, MkDocs nav, `docs/episodes.md`,
  memory/configuration/CLI/init/ACE/architecture pages, and blog mentions that currently present episodes as an active
  feature.
- Delete episode-specific tests and fixtures, then adjust shared tests that currently assert the command, explorer,
  doctor check, chop script, core wire API, prompt recall, or episode trace marker exist.

## Out Of Scope

- Do not delete existing user data under `~/.sase/projects/<project>/episodes/`. Removing code and docs is enough;
  persisted local episode records can remain inert.
- Do not rewrite historical SDD design files, bead event streams, or changelog history unless the user explicitly wants
  history scrubbed. Final reference scans should classify any remaining matches as historical-only.
- Do not edit generated chezmoi skill files directly. The long-memory guidance says those are generated and should be
  updated through their source pipeline only if a source skill changes; this removal does not require that.
- Do not modify canonical memory files.

## Implementation Plan

1. Re-run targeted `rg` scans for active episode references across the SASE repo, `sase-core_11`, and the chezmoi source
   repo to catch anything added since this plan was written.
2. Remove CLI wiring in `src/sase/main/parser_memory.py`, `src/sase/main/memory_handler.py`, and delete
   `src/sase/main/parser_memory_episodes.py` plus the `src/sase/memory/cli_episodes*.py` modules. Update memory help
   text so subcommands remain sorted and no episode examples remain.
3. Delete the episode implementation package and Python core wire facade. Fix imports exposed by deletion, including
   prompt recall and storage/render helpers.
4. Remove the Rust-core episode module and PyO3 functions from `sase-core_11`. Update public exports and delete the Rust
   episode parity test. Reinstall or rebuild the local Python extension before running SASE checks.
5. Remove automatic builder/chop integration: delete the chop script, remove the project script entry, remove the
   wrapper function, and delete the `memory_episodes` chop block plus its `SASE_MEMORY_EPISODES_*` env vars from
   chezmoi.
6. Remove runtime episode recall and episode trace markers from agent runner setup/finalization/helpers. Preserve
   ordinary artifact, plan, retry, question, and handoff metadata behavior.
7. Remove ACE Episode Explorer TUI code and all launch paths: action, binding, keymap metadata/dataclass field, command
   catalog entry, modal exports, TCSS, help bindings, and explorer tests.
8. Remove the `sase doctor` episode check and its registry entry. Adjust doctor registry tests to expect the remaining
   deep checks only.
9. Update docs and MkDocs nav so memory docs describe only active memory commands (`init`, `list`, `read`, `write`,
   `review`, `log`) and no active page links to episodes remain.
10. Delete episode-specific tests and fixtures. Adjust shared parser, command catalog, command-palette, agent artifact
    audit, and runner setup tests to reflect the removed feature.
11. Run final active-reference scans in all three repos. Treat matches under historical SDD/bead/changelog files as
    acceptable only if they are clearly historical and not product docs, code, config, tests, or active examples.

## Verification

- In `sase-core_11`: run `cargo test --workspace`.
- In the SASE repo: run `just install`, then reinstall the local Rust binding from `sase-core_11` if needed, then run
  `just check`.
- Run targeted smoke checks before the full check if useful:
  `pytest tests/main/test_memory_parser_handler.py tests/main/test_parser_help.py` and command/TUI catalog tests touched
  by the removal.
- In chezmoi: run `git diff --check` from `/home/bryan/.local/share/chezmoi` after editing the config.

## Risks

- The broadest risk is removing `episode_trace.json` too aggressively. It should be removed only after confirming no
  non-episode workflow depends on it.
- The Rust binding and Python facade must be removed together; leaving either side behind would create dead API surface
  or broken imports.
- Docs have both product pages and historical SDD/bead records. The final scans need to distinguish active user guidance
  from history instead of blindly rewriting project records.
