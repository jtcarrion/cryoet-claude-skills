---
max_turns: 30
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
tags: [teamtomo-preprocess]
---

teamtomo's xml_to_tomograms crashes right at the start with `TypeError: 'NoneType' object is not iterable` on my older Warp project (/data/me/old_project/warp, made with a Warp 1.x-era build a couple of years ago). What's wrong and how do I get it to run? Please don't modify my Warp files.
