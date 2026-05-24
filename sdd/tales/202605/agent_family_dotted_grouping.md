---
create_time: 2026-05-24 11:25:57
status: done
prompt: sdd/prompts/202605/agent_family_dotted_grouping.md
---
# Plan: Fix Dotted Agent-Family Grouping In Agents Tab

## Problem

The Agents tab no longer groups the related `a9f` and `a9f.w1` rows under the same visible heading. A direct model-only
check with plain `agent_name="a9f"` and `agent_name="a9f.w1"` still groups correctly, so the regression is not the basic
dotted-name grouping rule.

The live rows show the actual failure mode:

- root family: `agent_name="a9f"`, `agent_family="a9f"`, `role_suffix="-plan"`
- wait-derived family: `agent_name="a9f.w1"`, `agent_family="a9f.w1"`, `role_suffix="-plan"`

`src/sase/ace/tui/models/agent_groups/_keys.py` currently gives `agent.agent_family` absolute priority in `_name_root()`
and returns it verbatim. That was fine while plan-family bases were dotless, but recent wait/fork-derived names can be
dotted (`<base>.w1`, `<base>.f1`). As a result, `a9f.w1` gets name-root `a9f.w1` instead of the normal dotted-name root
`a9f`, so it renders under a separate heading from `a9f`.

## Goal

Preserve plan-family metadata as the authoritative grouping name source while applying the same dotted root/prefix
semantics to that source that ordinary `agent_name` values already get.

For example:

- `agent_family="a9f"` -> root `a9f`, no prefix
- `agent_family="a9f.w1"` -> root `a9f`, prefix `a9f.w1`
- `agent_family="a9f.w1"` plus `agent_family="a9f"` should share the `a9f` heading
- plan-chain phase children such as `a9f.w1-plan` should inherit the same family grouping through their parent

## Implementation Plan

1. Refactor grouping-name selection in `agent_groups/_keys.py`.
   - Add a small helper that returns the effective grouping name for a row, preferring `agent.agent_family`, then an
     inferred family base for known plan-chain role suffixes, then `agent.agent_name`, then `display_name`.
   - Keep `agent.agent_family` authoritative, but do not treat it as an already-final root key.

2. Apply existing dotted-name semantics to the effective grouping name.
   - `_name_root()` should split the effective grouping name at the first dot when present, otherwise return the full
     effective grouping name.
   - `_name_prefix()` should compute the first two dotted segments from the effective grouping name, including exact
     two-segment parent markers, matching the parent-prefix behavior already implemented for normal names.
   - `_name_prefix_member_rank()` should compare the effective grouping name to the computed prefix so exact markers
     sort before their descendants.
   - Continue suppressing root/prefix grouping entirely under `BY_DATE`.

3. Add focused regression tests.
   - Model tests for `a9f` plus dotted family `a9f.w1` in `STANDARD` mode: one `a9f` root heading, with the dotted
     family under that heading rather than a separate `a9f.w1` root.
   - A `BY_STATUS` variant, because the reported Agents tab can be in status grouping mode and this path also uses
     name-root grouping.
   - A widget-level regression for rendered row order if the model assertions do not cover the visible heading shape
     clearly enough.
   - Keep existing plain dotted-name and parent-prefix tests passing.

4. Verify the live shape locally.
   - Re-run a small loader/tree inspection for the current `a9f`/`a9f.w1` rows and confirm there is one `a9f` heading
     containing both families.
   - Run focused tests for `tests/ace/tui/models/test_agent_groups_*` and
     `tests/ace/tui/widgets/test_agent_list_grouping*`.
   - Run `just install` if needed, then `just check` before final response, per repo instructions.

## Scope Notes

This is presentation-layer TUI grouping behavior. It should stay in the Python Agents-tab grouping model rather than
moving into `sase-core`. The change should not alter agent naming, wait/fork allocation, metadata persistence, or
backend wait/resume resolution.
