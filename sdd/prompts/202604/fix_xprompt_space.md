---
plan: sdd/plans/202604/fix_xprompt_space.md
---
When I was in neovim typing out a prompt, I had the following text typed out (`<cursor>` represents by cursor position):

```
The prompt input widget just froze on me while I was typing (see the `sase ace` snapshot below). I think it maybe has something to do with the prompt input widget's `prettier` / auto-wrap functionality. Can you help me diagnose
the root cause of this issue and fix it? #plan #pr:fix_piw_freeze #<cursor>
```

I then hit the `@` key, which triggered the ../sase-nvim repos xprompt selection popup. I then selected `m_opus_codex`
and this is what the prompt looked like after:

```
The prompt input widget just froze on me while I was typing (see the `sase ace` snapshot below). I think it maybe has something to do with the prompt input widget's `prettier` / auto-wrap functionality. Can you help me diagnose
the root cause of this issue and fix it? #plan #pr:fix_piw_freeze#m_opus_codex
```

Notice how the there is no space between the `e` and `#m_opus_codex`? This is not correct. Can you help me diagnose the
root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.
