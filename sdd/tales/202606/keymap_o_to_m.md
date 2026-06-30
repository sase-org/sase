---
create_time: 2026-06-30 07:46:10
status: done
---
# Plan: Move Model Overrides from `,o` to `,m`

## Goal

Update ACE leader-mode defaults so:

- `,m` opens Model Overrides globally from PRs, Agents, and AXE.
- The existing PRs-tab Mentor Review action moves from `,m` to `,C`.
- No default leader-mode subkey is duplicated or shadowed.

## Current Findings

Leader-mode defaults have two source-of-truth locations that must stay aligned:

- `src/sase/default_config.yml`
- `src/sase/ace/tui/keymaps/types.py` (`LeaderModeKeymaps`)

Current relevant defaults:

- `temporary_llm_override: "o"`
- `review_mentors: "m"`
- `capture_agents_repro: "C"`

The requested `,C` target is already occupied by the Agents-tab repro bundle action. This cannot be left as a contextual
duplicate: the leader dispatcher compares only the raw subkey, and command-palette execution also dispatches only that
subkey. If mentor review and repro capture both use `C`, the earlier dispatcher branch would shadow the later one and
make repro capture unreachable in normal keyboard flow.

Most UI surfaces are already registry-driven:

- Leader dispatch reads `self._keymap_registry.leader_mode.keys[...]`.
- Help modal sections render keys from the loaded registry.
- The leader footer renders keys from the loaded registry.
- The command catalog builds `leader.*` command key displays from the loaded registry.

The main implementation risk is therefore stale defaults, stale exact-key tests, and stale product documentation rather
than large dispatch rewrites.

## Decisions

Move `temporary_llm_override` from `,o` to `,m`.

Move `review_mentors` from `,m` to `,C`, as requested. It remains PRs-tab-only.

Move `capture_agents_repro` from `,C` to `,B`, using `B` as the mnemonic for "bundle". It remains Agents-tab-only.

Do not keep aliases for the old default chords in code. Users who need compatibility can override
`ace.keymaps.modes.leader_mode.keys` in config, and avoiding aliases keeps command-palette and repeat-last behavior
unambiguous.

Do not edit historical `sdd/` prompt/tale/epic records for this migration. Those are prior-work records, not current
product docs.

## Implementation Steps

1. Update default keymap sources:
   - Change `temporary_llm_override` to `"m"` in `src/sase/default_config.yml`.
   - Change `review_mentors` to `"C"` in `src/sase/default_config.yml`.
   - Change `capture_agents_repro` to `"B"` in `src/sase/default_config.yml`.
   - Make the same three changes in `LeaderModeKeymaps` in `src/sase/ace/tui/keymaps/types.py`.

2. Keep dispatch logic data-driven:
   - Confirm `_leader_mode.py` continues to compare against registry values and does not need hardcoded key branches.
   - Update nearby comments/docstrings that still say Model Overrides is `,o` by default.
   - Add or adjust focused dispatch tests if exact raw subkeys are currently missing for model overrides, mentor review,
     or repro capture.

3. Update command catalog and help/footer tests:
   - Assert `leader.temporary_llm_override` displays `,m` and executes subkey `m`.
   - Assert `leader.review_mentors` displays `,C`, remains scoped to PRs, and executes subkey `C`.
   - Assert `leader.capture_agents_repro` displays `,B`, remains scoped to Agents, and executes subkey `B`.
   - Keep or strengthen the existing guard that default leader-mode subkeys are unique.
   - Update temporary-override help/footer expectations from `,o` to `,m`.
   - Update Agents help expectations from `,C` to `,B` for repro capture.
   - Add PRs help coverage for `,C` Mentor Review if existing coverage does not pin it.

4. Update current documentation:
   - `docs/ace.md`: PRs leader table, Agents leader table, AXE leader table, Mentor Review section, Model Overrides
     section, repro-capture instructions, and any prose saying global entries include `,o`.
   - `docs/llms.md`: Model Overrides usage examples and any scenario bullets that say ACE chord `,o`.
   - `docs/configuration.md`: keymap examples and prose for model override, mentor review, and in-TUI repro capture.
   - `docs/mentors.md`: Mentor Review launcher from `,m` to `,C`.
   - `docs/blog/posts/changespecs-in-practice.md`: current mentor-review shortcut reference.
   - `tests/ace/tui/repro/README.md`: in-TUI repro capture instruction from `,C` to `,B`.

5. Verify stale references deliberately:
   - Search current docs/tests/source for product-facing `,o`, `,m`, and `,C` references after edits.
   - Leave historical SDD references unchanged unless they are part of active docs or tests.
   - Confirm no default config sample advertises conflicting leader subkeys.

## Verification

Run focused checks first:

```bash
python -m pytest \
  tests/test_keymaps_defaults.py \
  tests/test_temporary_llm_override_modal.py \
  tests/test_temporary_llm_override_keymaps.py \
  tests/test_temporary_llm_override_leader_mode.py \
  tests/test_command_catalog.py \
  tests/test_command_catalog_guards.py \
  tests/ace/tui/test_leader_keymap_dispatch.py \
  tests/ace/tui/test_leader_keybinding_footer.py \
  tests/ace/tui/repro/test_in_tui_capture.py
```

Run repository-required validation after implementation:

```bash
just install
just check
```

If visual snapshot tests fail only because leader-mode footer/help key labels changed, inspect the generated visual
artifacts before accepting or updating any snapshot.

## Expected Result

After implementation, `,m` opens Model Overrides from any ACE tab, `,C` opens Mentor Review on the PRs tab, and `,B`
captures an Agents-tab repro bundle. Help, footer, command palette, docs, and tests all agree with the new defaults, and
the default leader-mode subkey set remains unique.
