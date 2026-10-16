---
title: Macro discovery order
description: File-backed macro and workflow locations in lookup order.
---

<!-- generated, do not edit; source: sase_core_rs.sase_content_layout (tools/render_keymap_macro_reference; run just fix to regenerate) -->

# Macro discovery order

This table is the file-backed source order returned by SASE's Rust content-layout contract. The first matching file definition wins. Project-local definitions are namespaced with the project name; canonical locations are writable and legacy locations are read-only compatibility paths.

| Priority | Location | Source | Formats | Write policy |
| --- | --- | --- | --- | --- |
| 1 | `<project>/sase/macros/` | Canonical | `.md`, `.yml`, `.yaml` | Writable |
| 2 | `~/sase/macros/` | Canonical | `.md`, `.yml`, `.yaml` | Writable |
| 3 | `~/sase/macros/<project>/` | Canonical | `.md`, `.yml`, `.yaml` | Writable |
| 4 | `<project>/sase/xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 5 | `<project>/.xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 6 | `<project>/xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 7 | `~/sase/xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 8 | `~/.xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 9 | `~/xprompts/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 10 | `~/sase/xprompts/<project>/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |
| 11 | `~/.config/sase/xprompts/<project>/` | Legacy compatibility | `.md`, `.yml`, `.yaml` | Read-only |

Configuration-defined macros, plugin definitions, and bundled package definitions use separate loaders. Memory macros and skills use reserved namespaces, so they do not take part in ordinary macro-name collisions. See the [macro reference](../../macros.md) for those definition forms.
