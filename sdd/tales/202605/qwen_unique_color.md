---
create_time: 2026-05-12 18:23:59
status: done
prompt: sdd/prompts/202605/qwen_unique_color.md
---
# Plan: Give QWEN a Unique, Brand-Aligned Color

## Problem

QWEN's CLI status color (`#7CFF6B`, a bright lime green) is visually too close to CODEX's color (`#10A37F`,
OpenAI-family teal-green). In dense TUI surfaces (agent rows, plan-approval badges, prompt-panel model fields, model
picker), users can't reliably tell QWEN and CODEX apart at a glance — they both read as "the green one."

The color sits in `src/sase/llm_provider/qwen.py` under the `llm_cli_status_color()` plugin hook and flows through
`provider_cli_status_color_map()` into `provider_style_for()` in `src/sase/ace/tui/provider_styles.py`, where it
overrides the `name_style` of the fallback palette via `_with_primary(...)`.

## Goals

1. Replace QWEN's primary color with something that is visually distinct from every other currently-registered provider
   (claude, codex, gemini, opencode) at a glance, including for users with mild color-vision deficiencies (red-green
   confusion is the common case — picking another green or yellow-green would not actually fix the bug).
2. Pick a color that fits Qwen's brand identity. Alibaba's Qwen / Tongyi Qianwen product UI uses a purple/violet
   identity, which is conveniently the one slot in our provider palette that is currently unused.
3. Keep the change minimal and self-contained: the plugin's `llm_cli_status_color()` is the single source of truth that
   fans out to every surface that asks the registry for a color, so we should not need ad-hoc patches across the TUI.

## Non-Goals

- Reworking how provider colors are themed in general (the `_PROVIDER_FALLBACK_STYLES` table, the `_with_primary` logic,
  vendor-family defaults in `registry.py`, etc.). The current architecture is fine; only the QWEN entry is wrong.
- Touching CODEX, CLAUDE, GEMINI, OPENCODE, or neutral provider colors.
- Changing any non-color QWEN styling (emoji badge `🐼`, short name `qwn`, model aliases, etc.).

## Current Color Landscape

| Provider           | Primary (`llm_cli_status_color` / family)           | Visual feel                          |
| ------------------ | --------------------------------------------------- | ------------------------------------ |
| claude / anthropic | `#FF5F00` (fallback `name_style`), family `#D97757` | warm orange / red                    |
| codex / openai     | `#10A37F` (family default)                          | teal-green                           |
| gemini             | `#4285F4` (family default)                          | google blue                          |
| **qwen**           | **`#7CFF6B`** (plugin override)                     | **lime green — collides with codex** |
| opencode           | `#FFB454` (plugin override)                         | amber / orange-yellow                |

Notable: `src/sase/ace/tui/provider_styles.py` already has a purple `_PROVIDER_FALLBACK_STYLES["qwen"]` palette
(`name_style="bold #D75FFF"`, delimiter `#AF5FD7`, model `#E6A8FF`, …). Today `_with_primary()` overrides `name_style`
to `bold #7CFF6B`, producing a mixed green-name / purple-delimiter look that is incoherent in addition to being too
close to codex. Switching the plugin color to a purple unifies the whole row under one identity.

## Proposed Color

**`#D75FFF`** — a vivid magenta-violet that:

- Is already the canonical QWEN fallback `name_style` in `provider_styles.py`, so this change effectively _promotes_ the
  existing-but-overridden purple to be QWEN's authoritative color.
- Is far away in hue from every other provider color (orange, teal-green, blue, amber). The hue gap is large enough that
  red-green colorblind viewers can also distinguish it from codex.
- Aligns with the Qwen brand identity (Alibaba's Qwen marketing uses purple/violet accents).
- Already flows correctly through the rest of the palette (`delimiter_style`, `model_style`, `dim_style`) in
  `provider_styles.py`, so once we drop the green primary, the row becomes internally consistent without any further
  edits.

If we later decide we want a slightly punchier hue, `#C77DFF` or `#A855F7` are drop-in substitutes — but `#D75FFF` is
the recommendation because it matches what's already in the fallback table and avoids dragging the palette into a second
round of cleanup.

## Implementation Sketch

1. **`src/sase/llm_provider/qwen.py`** — change the `llm_cli_status_color()` return value from `"#7CFF6B"` to
   `"#D75FFF"`. Single line, no other code change in this file.

2. **`tests/test_qwen_opencode_integration_polish.py`** — update the two assertions that pin the old color:
   - `assert provider_cli_status_color_map()["qwen"] == "#7CFF6B"` (around line 43)
   - `assert "#7CFF6B" in qwen` in `test_plan_approval_badge_renders_new_provider_colors` (around line 83) Both should
     become `"#D75FFF"`. No new tests are needed — these existing assertions are the regression guard, and the rest of
     QWEN's behavior is unchanged.

3. **`src/sase/ace/tui/provider_styles.py`** — no change required. The QWEN entry in `_PROVIDER_FALLBACK_STYLES` already
   uses `#D75FFF` as `name_style`, so `_with_primary()` will now be a no-op for QWEN (overriding purple with the same
   purple). I considered refactoring `_with_primary` to skip when primary matches, but that's beyond scope and would
   tangle the change with unrelated cleanup.

4. **Verification** — run `just check` (lint + mypy + tests). Visual PNG snapshot tests (`tests/ace/tui/visual/`) may
   also need refreshing if any golden image renders the QWEN color; if so, inspect `.pytest_cache/sase-visual/` diffs to
   confirm the change is just a hue shift on QWEN rows and accept with `--sase-update-visual-snapshots`.

## Risks & Open Questions

- **PNG snapshot churn**: any visual snapshot whose frame shows a QWEN-flavored row will need to be regenerated. This is
  mechanical but the diff should be reviewed to make sure no other pixels shifted.
- **Downstream consumers**: a quick repo-wide grep for `7CFF6B` shows only `qwen.py` and the one test file. There are no
  documentation files, README screenshots, or skill prompts that hardcode the color, so no external comms need updating.
- **Brand color choice**: `#D75FFF` is a judgment call grounded in Qwen's purple branding and consistency with the
  existing fallback. If you prefer a different purple/violet (or want to match a specific Qwen marketing hex), swap the
  constant before merging — the rest of the plan is unaffected.
