---
plan: sdd/epics/202607/first_blog_post.md
---
 I'm attempting to write my first blog post for sase. I already have a draft out but most of that is irrelevant. A lot of my more recent ideas of what I want in the blog post can be found in the ~/bob/sase_blog_0.md file. I've decided that I want this blog post to be narrowly focused on the parts that users need to know about:
- how sase integrates with agent CLIs instead of models directly
- how xprompts work
- how the UX works for the agents tab in the TUI
- how to install, configure, and initialize sase properly

I've already generated demo GIF files that should be integrated into this blog post after you improve them if necessary. Make sure you provide a good introduction and explain what sase adds to the status quo, which I believe to be the Boris Cherny method of opening up multiple different tmux tabs, each containing an agent CLI instance, and then hopping to different ones as needed. Reference the tmux_ai_window script in my Cheetos repo for context on how I actually used to use this method.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 Make sure you provide heavy guidance to these agents on what you consider to be the core content of this blog post and also regarding the content flow of the post in general. 