---
plan: sdd/tales/202606/prompt_number_increment.md
---
 Can you help me implement the `<ctrl+a>` and `<ctrl+x>` keymaps (inspired by vim) in the prompt input widget to increment/decrement numbers?

- The `<ctrl+a>` keymap already jumps to the beginning of the line. This should be preserved in insert mode but not in normal mode.
- If the cursor is not currently on a number but there's a number on the current line or in the current prompt, we should jump to an increment/decrement that number.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Jump target

> When the cursor is NOT on a number, which number should ctrl+a/ctrl+x jump to and modify?

- [x] **Forward, wrap to top (Recommended)** — Vim-style: first number at/after the cursor; search continues onto later lines; if none found, wrap to the top of the prompt and scan up to the cursor (covers earlier-on-line and previous lines).
- [ ] **Current line first, then prompt** — Exhaust the current line first (number after cursor, else before cursor on the same line), and only if the current line has no number, search the rest of the prompt forward then wrap.
- [ ] **Nearest by distance** — Pick whichever number is closest to the cursor by character distance, regardless of direction (forward or backward).

#### Q2: Number formats

> Which number formats should the increment/decrement support in v1?

- [x] **Decimal + sign + leading-zero width (Recommended)** — Decimal integers; treat a leading - as a negative sign (5 ctrl+x on -3 -> -8); preserve leading-zero width like vim (007+1 -> 008). No hex/octal/binary.
- [ ] **Plain unsigned decimal only** — Only runs of digits [0-9]+. A leading - is left untouched (so decrementing 0 yields -1 written as a fresh sign). Simplest possible.
- [ ] **Decimal + hex/octal/binary (full vim)** — Also recognize 0x1f, 0o17, 0b101 like vim nrformats. More complex; larger surface area and tests.

#### Q3: Count & dot

> Should count prefixes and dot-repeat work with these commands?

- [x] **Yes - count + dot-repeat (Recommended)** — 5 ctrl+a adds 5; . repeats the last increment/decrement, matching the existing ~/x/dd vim behavior in this widget.
- [ ] **Count only, no dot-repeat** — Support 5 ctrl+a but do not make . replay it.
- [ ] **Neither - always +/-1** — Simplest: each press changes by exactly 1, no count, no dot-repeat.

%xprompts_enabled:true