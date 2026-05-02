---
plan: sdd/tales/202604/kitty_tmux_preview_probe_fix.md
---
 Our recent attempt to add TUI support for viewing images with Kitty (run the `sase bead show sase-1i` command for context) seems to have failed (see the `sase ace` snapshot below). The
`kitten icat --passthrough tmux --transfer-mode stream /home/bryan/projects/github/sase-org/sase_100/docs/images/sase_tui_tabs_infographic.png` command correctly displays an image in my terminal in this
same tmux session, so I'm thinking this is a bug on our end. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (x3)  │  AXE (7)                                                                                                                                           Override CODEX(gpt-5.5) 64h32m  ■ IDLE  ✉ 3
 Agents: 1/3   [view: file]   [group: by project (o)]   (auto-refresh in 0s)                                                                              ▌
┌─ (u█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▌ CODEX(gpt-5.5) @iw completed: ace(run)-260430_033057      ┐
│  ▌ █                                                                                                                                                    ▌                                                            │
│  │ █  Notifications                                                                                                                                                                                            █     │
│  │ █                                                                                                                                                                                                           █ ▅▅  │
│  │ █  ┌─────────────────────────────────────────────────────────────────────────────┐ │ File 3/3: ~/projects/github/sase-org/sase_100/docs/images/sase_tui_tabs_infographic.png                                █     │
│    █  │ ▌ INBOX · 3                                                                 │ │ Image preview unavailable                                                                                              █     │
│    █  │ * [user-agent] CODEX(gpt-5.5) @jv completed: ace(run)-260430_0...  3m ago   │ │ /home/bryan/projects/github/sase-org/sase_100/docs/images/sase_tui_tabs_infographic.png                                █     │
│    █  │ [agent]  2 files                                                            │ │ 1,481,865 bytes                                                                                                        █     │
│    █  │ * [user-agent] CODEX(gpt-5.5) @ju completed: ace(run)-260430_0...  3m ago   │ │ terminal family is not known to support Kitty placeholders                                                             █     │
│    █  │ [agent]  3 files                                                            │ │ Open with e in notifications or %E in agent panels                                                                     █     │
│    █  │ * [user-agent] CODEX(gpt-5.5) @iw completed: ace(run)-260430_0...  3s ago   │ │                                                                                                                        █     │
│    █  │ [agent]  2 files                                                            │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █─────┘
│    █  │                                                                             │ │                                                                                                                        █─────┐
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  │                                                                             │ │                                                                                                                        █     │
│    █  └─────────────────────────────────────────────────────────────────────────────┘ │                                                                                                                        █     │
│    █                                                                                                                                                                                                           █     │
│    █  Enter: select  x: dismiss  m: mute  s: snooze  e: edit  C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  q: close                                                                                  █     │
│    █                                                                                                                                                                                                           █     │
│    █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█     │
└──────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────────────── 31 lines ────────────────────────────────────────────────────────────────────────┘
 n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (3 done)                                                                                                                      RUNNING


```