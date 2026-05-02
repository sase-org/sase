---
plan: sdd/epics/202603/prompt_widget_improvements.md
---
#gh:sase We recently (see 9febfa43ed7b git commit) replaced the prompt bar with a TextArea widget. Can you help me make
some more improvements?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### Requirements

- The prompt widget should continue to, if necessary, expand to take up the entire screen (see the `sase ace` snapshot
  below for current bad behavior).

#### Vim-Mode

From now on, when the user presses `<esc>`, it should launch them into vim's "NORMAL" mode which will do several things:

- Start showing relative, instead of absolute, line numbers (except for the current line). For example, in the below
  snippet, `8` is where the current line is (where the user is editing):
  ```
   7
   6
   5
   4
   3
   2
   1
  0
   1
   2
   3
   4
   5
  ```
- Support as many of vim's navigation keymaps as possible. For example, `w` to go to the next word, `j`/`k`, `W`/`w`,
  `b`/`B`, `e`/`E`, etc...

#### `sase ace` snapshot (demonstrates bad behavior)

```
 ⭘                                                                                                                    sase ace
  CLs (2)  │  Agents  │  AXE (6)                                                                                                                                                                                                          ■ IDLE  ✉ 0
 Agents: 0/0   (auto-refresh in 8s)
┌──────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                      ││                                                                                                                                                                                                            │
│                                      ││  No agent selected                                                                                                                                                                                         │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
│                                      ││                                                                                                                                                                                                            │
└──────────────────────────────────────┘└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Prompt ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  6                                                                                                                                                                                                                                                 │
│  7                                                                                                                                                                                                                                                 │
│  8                                                                                                                                                                                                                                                 │
│  9                                                                                                                                                                                                                                              ▅▅ │
│ 10                                                                                                                                                                                                                                                 │
│ 11                                                                                                                                                                                                                                                 │
│ 12                                                                                                                                                                                                                                                 │
│ 13                                                                                                                                                                                                                                                 │
│ 14                                                                                                                                                                                                                                                 │
│ 15                                                                                                                                                                                                                                                 │
│ 16                                                                                                                                                                                                                                                 │
│ 17                                                                                                                                                                                                                                                 │
│ 18                                                                                                                                                                                                                                              ▅▅ │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────  cancel ─┘

```
