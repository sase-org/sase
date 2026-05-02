---
create_time: 2026-04-15 16:29:06
status: done
prompt: sdd/prompts/202604/profile_show_all.md
---

# Plan: Fix `sase ace --profile` output hiding all frames

## Problem

The profile output from `sase ace --profile` is nearly useless:

```
59.337 handle_ace_command  main/ace_handler.py:12
└─ 59.337 AceApp.run  textual/app.py:2258
      [188 frames hidden]  asyncio, textual, ace, pathlib, glob,...
```

Only 2 frames are visible; 188 are hidden. The purpose of profiling is to see _where_ time is spent, but the default
pyinstrument filtering hides any frame whose `total_self_time < 20%` of root time — which in a TUI with many small
contributors means everything gets hidden.

## Root Cause

In `src/sase/main/ace_handler.py:66`:

```python
f.write(profiler.output_text(unicode=True, color=False))
```

The `output_text()` method defaults to `show_all=False`, which applies several frame-collapsing processors
(`group_library_frames_processor`, `remove_importlib`, `remove_irrelevant_nodes`, `remove_tracebackhide`). These hide
frames that don't individually account for a large share of total time.

## Fix

Pass `show_all=True` to `profiler.output_text()` on line 66 of `ace_handler.py`:

```python
f.write(profiler.output_text(unicode=True, color=False, show_all=True))
```

This removes the filtering processors and shows the full call tree, which is what a developer profiling the TUI actually
needs.

## Files to Change

1. `src/sase/main/ace_handler.py` — line 66: add `show_all=True`

## Verification

- `just check` passes
