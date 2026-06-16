---
create_time: 2026-06-16 12:27:11
status: done
prompt: sdd/prompts/202606/jinja2_prompt_input.md
---
# Plan: Beautiful Jinja2 Support & Visual Aid in the Prompt Input Widget

## Goal

Give the `sase ace` prompt input bar first-class Jinja2 awareness: live, tasteful syntax highlighting of Jinja2
constructs layered on top of the existing markdown highlighting, plus glanceable visual feedback (validity, error
location, unknown variables) and editing ergonomics (delimiter auto-pairing, in-template completion). The bar should
make Jinja2 _feel native_ and _look beautiful_ while staying honest about what will actually happen when the prompt is
rendered.

Today the prompt bar is fully Jinja2-blind: `{{ vars }}`, `{% blocks %}`, and `{# comments #}` render as plain markdown
text, syntax errors are only discovered at submit time (where `render_toplevel_jinja2` calls `sys.exit(1)` on
`TemplateError`), and there is no hint about which variables are actually available.

---

## Product vision — what the user will see

When a user types Jinja2 into the prompt bar:

1. **Live syntax highlighting** — delimiters, control-flow keywords, variables, filters, and comments each take a
   distinct, theme-harmonized color, layered _over_ the markdown highlighting that is already there. Jinja2 inside
   fenced code blocks is intentionally _not_ highlighted, mirroring the fact that the renderer protects fenced blocks.

2. **A validity chip** in the bar's border title that only appears when Jinja2 is present: `⟨jinja ✓⟩` in the theme's
   success color when the template parses, `⟨jinja ⚠ L3⟩` in the warning color when it does not.

3. **Inline error marking** — when the template is invalid, the offending region is underlined in the error color and
   the message (`unexpected '}}'`) is shown in the diagnostics surface, so the user fixes it _before_ submitting instead
   of getting a hard failure afterward.

4. **Unknown-variable awareness** — references to variables that won't exist at render time (top-level prompts only get
   `root`) are flagged gently, since `StrictUndefined` will otherwise blow up at submit.

5. **Editing ergonomics** — typing `{{`, `{%`, or `{#` auto-pairs to `{{ ▮ }}` / `{% ▮ %}` / `{# ▮ #}`; the matching
   closing delimiter highlights when the cursor is inside a tag; and completion inside a tag offers known variables,
   Jinja2 keywords, and registered filters.

### Mockup

```
┌─ Prompt  [INSERT]                                        ⟨jinja ✓⟩ ─┐
│ Summarize the changes in {{ root }} for {% if urgent %}the team{%   │
│ endif %}. {# leave a TODO #}                                        │
└─ [Enter] send   [Esc] normal   [^C] cancel ────────────────────────┘
        ^^^^      ^^^^^^      ^^^^^^^^                ^^^^^^^^^^^^^
     delimiters   keyword     variable               dim comment
```

Invalid state:

```
┌─ Prompt  [INSERT]                                    ⟨jinja ⚠ L1⟩ ─┐
│ Hello {{ name }                                                    │
│            ~~ unexpected end of template, expected '}}'            │
└────────────────────────────────────────────────────────────────────┘
```

---

## Scope

**In scope**

- Jinja2 syntax highlighting overlaid on markdown in the prompt text area.
- Live validity diagnostics (parse errors with line/location) and a status chip.
- Unknown-variable linting against the real top-level render context.
- Delimiter auto-pairing and matching-delimiter highlight.
- In-template completion (variables, keywords, filters) via the existing soft-completion machinery.
- Unit tests, widget tests, and a PNG visual snapshot to lock the look.

**Out of scope (this plan)**

- A full rendered _preview_ of the prompt (proposed as an optional stretch phase).
- Changing how prompts are actually rendered/submitted (`sase/xprompt` rendering semantics stay exactly as they are — we
  only _inspect_).
- Jinja2 support outside the prompt bar (catalog HTML, workflow YAML editor).

---

## Key design decisions (leading the design)

### 1. One authoritative Jinja2-inspection module in the domain layer

All Jinja2 _understanding_ (tokenization, validity, variable analysis, known context) lives in a new domain module
**`src/sase/xprompt/jinja_inspect.py`**, not buried inside a Textual widget. The TUI is a thin presentation consumer.

Rationale, and how this reconciles with the Rust-core boundary (`memory/short/rust_core_backend_boundary.md`):

- The litmus test ("would another frontend need this to match?") says yes — a web prompt box or the `sase-nvim`
  integration would want identical highlighting and diagnostics. So this logic must **not** live inside the Textual
  widget.
- **However**, the authoritative Jinja2 engine is the Python `jinja2` library in `sase/xprompt/_jinja.py`
  (`StrictUndefined`, `autoescape=False`, fenced-block protection). Diagnostics must match _that_ engine exactly, or
  they would lie. Reimplementing Jinja2 parsing in Rust (e.g. `minijinja`) would create a second, potentially-divergent
  source of truth — strictly worse than a single Python one.
- **Recommendation:** keep the inspection module in the Python domain layer (`sase/xprompt/`), reusing
  `_get_jinja_env()` and `protect_fenced_blocks` so it can never disagree with the real renderer. This honors the
  boundary's _intent_ (reusable domain logic outside the presentation widget) while keeping Jinja2 semantics anchored to
  the one engine that actually runs at submit. This module is the natural seam to expose through `sase_core_rs` later
  if/when cross-frontend parity at the Rust layer becomes a priority — flagged for the reviewer's call.

`jinja_inspect.py` public surface (frontend-agnostic, no Textual imports):

- `tokenize(text) -> list[JinjaSpan]` — spans of kind
  `delimiter | statement | variable | comment | filter | keyword | operator`, with char offsets, skipping fenced regions
  (reusing `protect_fenced_blocks` semantics).
- `diagnose(text) -> JinjaDiagnostics` — `ok: bool`, `message`, `lineno`, `col`, and the char span of the error (derived
  from `jinja2.TemplateSyntaxError`).
- `unknown_variables(text, known: set[str]) -> list[str]` — via `jinja2.meta.find_undeclared_variables(env.parse(text))`
  minus `known`.
- `known_toplevel_context() -> set[str]` — wraps `get_global_template_vars()` keys (currently `{"root"}`), so the lint
  tracks the real context and stays correct if globals grow.

### 2. Highlight by _overlay_, not a new grammar

Textual 8.0's `TextArea._build_highlight_map()` fills `self._highlights[row]` with `(start_byte, end_byte, name)` spans
from a tree-sitter query, and `render_line` styles each span with `theme.syntax_styles.get(name)` via Rich's _layering_
`Text.stylize`. We exploit this:

- A `JinjaHighlightMixin` on `PromptTextArea` overrides `_build_highlight_map()` to call `super()` (keeping markdown
  highlights) and then **append** Jinja2 spans produced by `jinja_inspect.tokenize`, converting char offsets to per-line
  byte offsets (matching how the render path indexes).
- We register a custom `TextAreaTheme` whose `syntax_styles` is the base theme's styles **plus** new `jinja.*` names.
  Because `stylize` layers, markdown bold/ headings still apply underneath the Jinja2 coloring.
- No tree-sitter grammar or injection is required — this avoids the install/grammar fragility the code already guards
  against, and respects the existing per-language size caps (we skip the overlay above a byte/line cap, same spirit as
  `lazy_syntax`).

### 3. Theme-harmonized, not hardcoded, colors

The `jinja.*` styles are derived at registration time from `app.current_theme` (`accent`, `secondary`, `success`,
`warning`, `error`, `foreground`, `text-muted`), and rebuilt when the app theme changes. So Jinja2 highlighting tracks
light/dark and any custom theme — central to "beautiful and consistent."

Proposed palette (semantic, resolved from theme tokens): | Token | Style intent | | --- | --- | | Delimiters
`{{ }} {% %} {# #}` | muted/dim accent — frames without shouting | | Statement keywords
(`if`/`for`/`set`/`endif`/`in`/`else`…) | accent, bold | | Variable name inside `{{ }}` | secondary (interpolation
color) | | Filters (`\| upper`) + `\|` | function-like (success/green), `\|` dim | | Comments `{# #}` | dim italic
(matches comment convention) | | Error region | error color, underlined (mirrors `html.end_tag_error`) |

### 4. Diagnostics surface priority (no popup collisions)

The bar already multiplexes `border_title` (mode), `border_subtitle` (mode hints + soft completion), and the
`#prompt-completion` panel (file completion + xprompt arg hints). To avoid clutter:

- **Validity chip** → right side of `border_title`, only when Jinja2 is present. Always safe; never collides.
- **Error/lint detail** → shown in the `#prompt-completion` panel _only when no higher-priority completion/arg-hint is
  active_; otherwise the chip alone carries the signal. A single explicit priority order (file-completion >
  xprompt-arg-hint
  > jinja-diagnostics > soft-completion) keeps exactly one thing in the panel.
- Diagnostics are **debounced** reusing the existing completion-timer pattern (`_schedule_prompt_completion_refresh`,
  ~90ms) so parsing never blocks typing.

---

## Architecture / files

**New (domain)**

- `src/sase/xprompt/jinja_inspect.py` — the single source of truth (above).

**New (presentation mixins for `PromptTextArea`)**

- `src/sase/ace/tui/widgets/_jinja_highlight.py` — `JinjaHighlightMixin`: `_build_highlight_map` overlay, theme-aware
  `TextAreaTheme` build/register, theme-change rebuild, matching-delimiter highlight, error-span styling.
- `src/sase/ace/tui/widgets/_jinja_diagnostics.py` — `JinjaDiagnosticsMixin`: debounced inspection, chip text, panel
  detail, feeds error span to the overlay.

**Edited**

- `src/sase/ace/tui/widgets/prompt_text_area.py` — add the two mixins; auto-pair `{{`/`{%`/`{#` in `_on_key`; trigger
  diagnostics on context change.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` / `prompt_input_bar.py` — render the chip in
  `border_title`; add a `show/hide_jinja_diagnostics` panel path respecting the priority order.
- `src/sase/ace/tui/widgets/prompt_completion.py` / `_prompt_soft_completion.py` — add an in-template completion kind
  (variables from `known_toplevel_context`, Jinja2 keywords, built-in + registered filters such as `tojson`) when the
  cursor is inside a `{{ }}` / `{% %}`.
- `src/sase/ace/tui/styles.tcss` — component styles for the chip and the diagnostics panel state
  (success/warning/error), consistent with the existing prompt-bar section.

**Cross-cutting touch-points (per `src/sase/ace/AGENTS.md`)**

- Update the `?` help modal to document Jinja2 highlighting, the chip, auto-pair, and in-template completion.
- If any new keybinding is added (e.g. a preview toggle in the stretch phase), update `src/sase/default_config.yml`
  keymaps and the footer per the footer keybinding convention; only add it if it has a sometimes-true condition.

---

## Phased implementation

**Phase 0 — Domain seam.** Build `jinja_inspect.py` (`tokenize`, `diagnose`, `unknown_variables`,
`known_toplevel_context`) with thorough unit tests: fenced-block exclusion, multiline `{# #}`, nested `{% %}`,
valid/invalid cases with exact line/column, unknown-vars vs `{% set %}`/loop targets. No UI yet — this is the foundation
everything else consumes.

**Phase 1 — Highlighting (the visual core).** `JinjaHighlightMixin` overlay + theme-aware palette + matching-delimiter
highlight. Add a prompt-bar **PNG visual snapshot** (valid template) as the deterministic "beautiful" gate. This phase
alone delivers most of the perceived value.

**Phase 2 — Live diagnostics.** Validity chip, inline error marking, and unknown-variable lint, debounced, with the
documented surface-priority rule. Add a PNG snapshot of the invalid/error state and widget tests asserting chip + error
span state.

**Phase 3 — Editing ergonomics.** Conservative delimiter auto-pairing and in-template completion
(variables/keywords/filters) reusing the soft-completion pipeline. Widget tests for pairing and completion candidates.

**Phase 4 — (Stretch / optional) Rendered preview.** A toggle that renders the template with the known context and a
forgiving undefined (showing `{{ var }}` placeholders for unknowns) in a transient panel, so the user sees the final
text. Gated behind a keybinding; included only if the reviewer wants it.

---

## Testing strategy

- **Unit** (`tests/`): `jinja_inspect` tokenization, fenced exclusion, validity + exact error location, unknown-variable
  analysis. Pure, fast, no TUI.
- **Widget** (`tests/ace/tui/`): overlay produces expected `_highlights` spans; diagnostics state (chip text, error
  span) for valid/invalid; auto-pair edits; completion candidate sets. Mirrors existing `test_prompt_*` patterns.
- **Visual** (`tests/ace/tui/visual/`): new PNG snapshots of the prompt bar with a valid and an invalid Jinja2 prompt,
  via `AcePage` + `assert_page_png`. These lock the rendering so "beautiful" is regression-protected (the suite already
  pins fonts/colors for determinism).
- Run `just check` (after `just install`) before completion, per build memory.

---

## Risks & mitigations

- **Highlight/markdown overlap** — layering means both apply; verify byte-offset conversion against the render path and
  snapshot the result. Skip overlay above a size cap for performance, consistent with existing caps.
- **Diagnostics diverging from real render** — avoided by construction: the inspection module reuses the same
  `_get_jinja_env()` and fenced protection as the renderer.
- **Surface clutter** — solved by one explicit priority order; the chip is the only always-on element and never
  collides.
- **Theme changes** — rebuild the `TextAreaTheme` on `app.current_theme` change so colors never go stale.

## Open question for the reviewer

- Confirm the recommendation in Decision #1: keep Jinja2 inspection in the Python domain layer (anchored to the real
  engine) vs. lifting it into `sase-core` Rust now. The plan assumes Python; say the word and Phase 0 retargets to a
  Rust `sase-core` API + binding.
- Want Phase 4 (rendered preview) included, or deferred?
