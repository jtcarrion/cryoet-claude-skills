---
max_turns: 30
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
tags: [teamtomo-preprocess]
---

I processed my tilt series with WarpTools using the warptools skill; the project is at /data/me/ribo_project (Warp files in its warp/ subfolder, alignment done with ts_etomo_patches, CTF done). I'd like 10 Å tomograms of every series reconstructed with teamtomo xml_to_tomograms instead of ts_reconstruct, on 4 GPUs. Prepare everything and show me the exact submit command, but don't submit anything.
