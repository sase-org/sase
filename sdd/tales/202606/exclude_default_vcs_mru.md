---
create_time: 2026-06-21 09:00:16
status: done
prompt: sdd/prompts/202606/exclude_default_vcs_mru.md
---
# Exclude Default VCS XPrompt From Prompt Cycling

## Context

The prompt input widget handles `ctrl+n` / `ctrl+p` through `src/sase/ace/tui/widgets/_vcs_mru_cycling.py`, which loads
its candidate prefixes from `sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru()`. Launching a bare prompt in
home mode is normalized to `#git:home`, and the launch path can record that resolved prefix into the same MRU file. Once
recorded, `#git:home` becomes one of the cycle candidates even though it is the implicit default.

## Goal

Make `ctrl+n` / `ctrl+p` cycle only explicit, non-default VCS xprompt prefixes. The default `#git:home` should not
appear as a cyclable choice, including when it already exists in the persisted MRU from earlier launches.

## Plan

1. Treat the default prefix as non-MRU data in `src/sase/history/vcs_xprompt_mru.py`.
   - Add a small helper that compares prefixes after normalizing underscore refs, so `#git:home` and legacy-equivalent
     spellings are handled consistently.
   - Use the existing `DEFAULT_VCS_WORKFLOW_PREFIX` constant instead of duplicating the literal.

2. Filter default entries at the MRU boundary.
   - Update `load_launchable_vcs_xprompt_mru()` to exclude default-equivalent entries before returning the launchable
     list. With pruning enabled, this also cleans old `#git:home` entries out of the stored MRU.
   - Update `record_vcs_xprompt_usage()` so future launches of the implicit default do not re-add `#git:home`; if a
     default entry is already present, remove it instead.

3. Keep widget behavior unchanged except for its candidate set.
   - No keymap or `default_config.yml` changes are needed.
   - The prompt widget will still cycle by MRU order, preserve cursor behavior, and give file completion precedence.
   - When the filtered MRU is empty, `ctrl+n` / `ctrl+p` should no-op as it already does for an empty MRU.

4. Add focused regression coverage.
   - Extend `tests/test_vcs_xprompt_mru.py` to assert that launchable MRU loading prunes `#git:home` and that recording
     `#git:home` does not persist it.
   - Extend `tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py` to assert cycling skips `#git:home` between two
     non-default entries and does nothing when the only MRU entry is the default.
   - If launch-path coverage is straightforward, assert that a bare prompt normalized to default does not record a VCS
     MRU entry.

## Validation

Run focused tests first:

```bash
pytest tests/test_vcs_xprompt_mru.py tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py tests/ace/tui/test_agent_launch_vcs.py
```

Because this repo requires it after source changes, run:

```bash
just install
just check
```
