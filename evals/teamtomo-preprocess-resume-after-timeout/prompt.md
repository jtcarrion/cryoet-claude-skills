---
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
tags: [teamtomo-preprocess]
---

My teamtomo TSA batch job (8 GPUs worth of series, output root /data/me/proj/teamtomo/tsa_to_tomograms_blind) hit the wall-time limit. batch_summary.csv in that folder is empty, which worries me. How do I find out what actually finished, and how do I finish the rest without redoing finished work? Don't submit anything yet; just tell me the commands.
