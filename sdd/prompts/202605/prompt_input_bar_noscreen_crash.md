---
plan: sdd/tales/202605/prompt_input_bar_noscreen_crash.md
---
 The `sase ace` TUI just crashed on me again with the below error. This happened right after I attempted to launch a new agent using the prompt input widget. Can you help me diagnose the root cause of this issue and (finally) fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
  
```
╭──────────────────────────────────────────────────────────────────────────────────── Traceback (most recent call last) ────────────────────────────────────────────────────────────────────────────────────╮
│ /home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/widgets/prompt_input_bar.py:162 in _update_height                                                                                              │
│                                                                                                                                                                                                           │
│   159 │   │   │   return                                                                       ╭─────────────────────── locals ───────────────────────╮                                                   │
│   160 │   │   visual_lines = self._get_visual_line_count()                                     │         self = PromptInputBar(id='prompt-input-bar') │                                                   │
│   161 │   │   # Reserve a few rows for the header/tabs at minimum                              │ visual_lines = 1                                     │                                                   │
│ ❱ 162 │   │   screen_height = self.screen.size.height                                          ╰──────────────────────────────────────────────────────╯                                                   │
│   163 │   │   max_height = screen_height - 2                                                                                                                                                              │
│   164 │   │   # +2 for border top and bottom, plus completion panel when visible                                                                                                                          │
│   165 │   │   completion_rows = self._completion_line_count if self._completion_visible else 0                                                                                                            │
│                                                                                                                                                                                                           │
│ /home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/textual/dom.py:806 in screen                                                                                                          │
│                                                                                                                                                                                                           │
│    803 │   │   │   │   "Widget is missing attributes; have you called the constructor in your w ╭─────────────────── locals ───────────────────╮                                                          │
│    804 │   │   │   ) from None                                                                  │ node = None                                  │                                                          │
│    805 │   │   if not isinstance(node, Screen):                                                 │ self = PromptInputBar(id='prompt-input-bar') │                                                          │
│ ❱  806 │   │   │   raise NoScreen("node has no screen")                                         ╰──────────────────────────────────────────────╯                                                          │
│    807 │   │   return node                                                                                                                                                                                │
│    808 │                                                                                                                                                                                                  │
│    809 │   @property                                                                                                                                                                                      │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
NoScreen: node has no screen
```

Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_11
- github: /home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_11
- telegram: /home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_11
- nvim: /home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_11
- chezmoi: /home/bryan/.local/share/chezmoi
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`)