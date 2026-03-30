---
create_time: 2026-03-30 09:43:39
status: done
---

# Plan: Prevent TIMESTAMPS loss during HOOKS updates

## Problem Summary

The newly introduced `TIMESTAMPS` ChangeSpec field can be unintentionally removed when HOOKS are rewritten (for example
when hooks are added, reset, or started). This causes audit trail data loss.

## Root Cause

`HOOKS` persistence rewrites the HOOKS section by scanning forward until it finds the next recognized field header. The
recognized-header list does not include `TIMESTAMPS:`. As a result, if `TIMESTAMPS` appears after `HOOKS`, the rewrite
logic treats it as HOOKS content and skips it, effectively deleting the section on write.

## Implementation Plan

1. Update HOOKS formatting/persistence boundary detection so `TIMESTAMPS:` is treated as a first-class ChangeSpec field
   header.
2. Add regression tests for `apply_hooks_update` that prove `TIMESTAMPS` survives when:
   - replacing an existing HOOKS section, and
   - inserting HOOKS into a ChangeSpec that already contains `TIMESTAMPS`.
3. Run focused tests for hooks formatting and timestamps parsing/recording coverage.
4. Run full repo validation (`just install` if needed, then `just check`) to ensure no regressions.

## Expected Outcome

Any HOOKS update path preserves the TIMESTAMPS section and its entries exactly, eliminating this data-loss class while
keeping current HOOKS behavior intact.
