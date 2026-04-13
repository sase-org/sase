---
keywords: [xprompt, directive, workflow step, prompt_part, reference expansion, workflow yaml, xprompt loading]
---

# xprompt System

## Loading Priority

xprompts are loaded from multiple sources; later sources overwrite earlier by name. Effective priority order (lowest →
highest):

1. **Internal** — `src/sase/xprompts/*.md` (built-in)
2. **Plugins** — `sase_xprompts` entry points
3. **Config YAML** — sase.yml sources (built-in defaults, plugin defaults, user sase.yml, overlay sase\_\*.yml, local
   ./sase.yml)
4. **Memory/long** — `memory/long/*.md` files with `keywords` frontmatter (auto-discovered from CWD and home dirs,
   across all runtimes)
5. **Project config** — `~/.config/sase/xprompts/{project}/*.md`
6. **File-based** (highest) — `~/xprompts/`, `~/.xprompts/`, `xprompts/`, `.xprompts/`

## Reference Syntax

- `#name` — simple expansion
- `#name(args)` — parenthesis arguments
- `#name:arg` — colon argument (word-like chars, backtick-delimited, or `$(cmd)` substitution)
- `#name+` — equivalent to `#name:true`
- `#name: text` — shorthand for inline content
- `#project/name` — namespaced access to project-local xprompts

## Directive Syntax

Directives modify agent behavior. Bare, colon, parenthesis, and plus forms are all supported.

| Directive   | Alias | Purpose                      |
| ----------- | ----- | ---------------------------- |
| `%approve`  | `%a`  | Require approval             |
| `%edit`     | `%e`  | Open in editor               |
| `%hide`     | `%h`  | Hide from display            |
| `%model:X`  | `%m`  | Set model                    |
| `%name:X`   | `%n`  | Set name                     |
| `%plan`     | `%p`  | Enter plan mode              |
| `%repeat:N` | `%N`  | Repeat N times               |
| `%wait:X`   | `%w`  | Wait for dependency/time/dur |

**Cartesian product:** Multiple `%alt(...)` or `%(...)` directives produce all combinations via `itertools.product`. A
single-arg `%alt(foo)` / `%(foo)` gets an implicit empty variant, producing two alternatives. `%model(m1,m2)` is
internally rewritten to `%alt(%model:m1,%model:m2)` before splitting.

## Workflow Steps

Step types: `agent`, `bash`, `python`, `prompt_part`, `parallel`.

Control flow: `if:` (Jinja2 condition), `for:` (var → expression), `repeat: until:`, `while:`.

Output binding: `{{ step_name }}` for full output, `{{ step_name.field }}` for specific fields (Jinja2 context). Join
modes: `array`, `text`, `object`, `lastOf`.

## Frontmatter Fields

`name`, `description`, `snippet`, `skill`, `tags`, `keywords`, `input` (shortform preferred).

## Gotchas

- **100-iteration expansion limit** — circular `#ref` chains raise after 100 iterations
- **StrictUndefined** — Jinja2 uses `StrictUndefined`; any missing variable is an error, not silent
- **Fenced code blocks** — ` ``` ` regions are protected from `#ref` expansion and restored after processing
- **Disabled regions** — `%xprompts_enabled:false` / `%xprompts_enabled:true` pairs suppress expansion
