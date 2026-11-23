---
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
tags: [warptools-preprocess]
---

I have IMOD alignments from etomo for all my series: /data/me/imod_align/<series>/<series>.xf and .tlt. The etomo stacks were binned 4x from the raw 1.35 Å/px data. Import these into my existing Warp project /data/me/proc/cells as a new alignment arm and get CTF and tomograms going on it.
