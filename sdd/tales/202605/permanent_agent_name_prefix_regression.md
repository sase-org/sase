---
create_time: 2026-05-09 13:06:29
status: done
prompt: sdd/prompts/202605/permanent_agent_name_prefix_regression.md
---
# Plan: Fix Permanent Agent Name Prefix Regression

## Problem

The `sase ace` snapshot shows `@260509.by.plan` for an agent launched as `%n:by`. That should not happen after the
permanent agent-name migration: the `YYmmdd.` prefix was a one-time migration device for names that already existed
before the new permanent-name registry, not a prefix to apply to new plan-chain agents.

Recent related chat context:

- `~/.sase/chats/202605/sase-ace_run-aoa_plan-260508_200053.md` planned the permanent-name migration. The user
  explicitly required that names become permanent and that `YYmmdd.` be added to existing auto-generated names to reset
  the auto namespace.
- `~/.sase/chats/202605/sase-ace_run-by_plan-260509_124156.md` shows the affected agent was launched with `%n:by`; the
  planner chat name was `by.plan`.

On-disk evidence:

- The completion notification for the affected run still recorded `agent_name: "by"`, but the root artifact was later
  rewritten with `"name": "260509.by.plan"` while the coder child stayed `"by.code"`.
- The remaining legacy prefixing path is dismissed-bundle deserialization:
  `src/sase/ace/tui/models/agent_bundle.py::_synthesize_dismissed_name()` still prefixes any non-prefixed
  `agent.agent_name` with `YYmmdd.`. If a dismissed or recovered bundle is restored, `_restore_agent_meta()` and
  done/workflow marker restoration can write that synthesized name back to artifact JSON.

## Root Cause Hypothesis

The permanent-name work removed the old dismissal-time renaming behavior, but left the compatibility repair in bundle
loading. That repair predates permanent names and treats any unprefixed loaded bundle name as something that should be
converted to a dismissal-prefixed historical name. Under the new rules, `by.plan` is already the permanent name for that
stored agent phase, so the repair is now wrong.

The fix should preserve stored names exactly. For genuinely old bundles that lack any `agent_name`, we can keep a
limited compatibility fallback if needed, but an existing stored name must never be rewritten.

## Implementation Plan

1. Update `src/sase/ace/tui/models/agent_bundle.py` so `_synthesize_dismissed_name()` returns immediately when
   `agent.agent_name` is present, regardless of whether it has a `YYmmdd.` prefix.
2. Keep the old missing-name fallback scoped to bundles with no stored `agent_name`, unless tests reveal that fallback
   also violates current unnamed-agent expectations.
3. Add regression coverage that deserializing a bundle with an unprefixed stored name such as `by.plan` preserves that
   name.
4. Add or extend restore/lifecycle coverage so artifact restoration does not merge a synthesized `YYmmdd.` name into
   `agent_meta.json` for an unprefixed stored name.
5. Run focused tests for bundle, revive, dismissed lifecycle, and name tests.
6. Run `just install` if needed, then `just check` per repo instructions.

## Expected Outcome

New and revived agents preserve permanent names exactly:

- `%n:by #plan` may display plan-chain phases as `by.plan` / `by.code`.
- It must not become `260509.by.plan` unless that exact prefixed name was already the stored permanent name from the
  historical migration.
