---
create_time: 2026-03-25 21:08:46
status: done
prompt: sdd/prompts/202603/hg_changespec_metadata.md
---

# Plan: Fix missing ChangeSpec metadata for hg provider in Agents panel

## Problem summary

On the Agents tab, hg runs (e.g. `#hg:... #commit`) often show `Project:` instead of `ChangeSpec:` in AGENT DETAILS,
while GitHub PR runs correctly show `ChangeSpec:`.

## Root-cause diagnosis

1. The `#hg` setup step sets either:
   - `meta_changespec` when ref resolves to a ChangeSpec, or
   - `meta_project` when ref resolves as project shorthand (`checkout_target=p4head`).
2. The metadata panel rendering prioritizes `meta_project` over `meta_changespec`.
3. The shared `#commit` xprompt `report` step emits `meta_new_commit` and `meta_commit_message`, but does **not** emit
   `meta_changespec` from `commit_result.json`.
4. Therefore for hg commit flows started via project shorthand, the panel never receives a `meta_changespec` override
   and remains stuck on `Project:`.

## Implementation steps

1. Update `src/sase/xprompts/commit.yml` `report` step to emit `meta_changespec` when `commit_result.json` has
   `changespec_name` or fallback `name`.
2. Update the `report` step output schema to include `meta_changespec`.
3. Update AGENT DETAILS rendering priority in `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` to prefer
   `meta_changespec` over `meta_project` when both are present (more specific identifier wins).
4. Add/adjust tests to lock behavior:
   - metadata panel prefers ChangeSpec when both meta keys exist;
   - commit workflow metadata extraction includes `meta_changespec` path.
5. Run targeted tests first, then broader lint/test checks if needed.

## Verification

- Reproduce with `sase ace --agent` snapshot path that embeds `#hg` + `#commit`.
- Confirm AGENT DETAILS shows `ChangeSpec: <name>` for hg runs when commit metadata includes name.
