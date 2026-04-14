---
keywords: [xprompt, directive, workflow step, prompt_part]
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

## Cartesian Product Behavior

Multiple `%alt(...)` or `%(...)` directives produce all combinations via `itertools.product`. A single-arg `%alt(foo)` /
`%(foo)` gets an implicit empty variant, producing two alternatives. `%model(m1,m2)` is internally rewritten to
`%alt(%model:m1,%model:m2)` before splitting.

## Gotchas

- **100-iteration expansion limit** — circular `#ref` chains raise after 100 iterations
- **StrictUndefined** — Jinja2 uses `StrictUndefined`; any missing variable is an error, not silent
- **Fenced code blocks** — ` ``` ` regions are protected from `#ref` expansion and restored after processing
- **Disabled regions** — `%xprompts_enabled:false` / `%xprompts_enabled:true` pairs suppress expansion
