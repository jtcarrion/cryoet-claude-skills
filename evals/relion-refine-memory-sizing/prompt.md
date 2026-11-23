---
max_turns: 20
allowed_tools: [Read, Glob, Grep, Skill, Bash]
timeout_seconds: 900
tags: [relion-refine]
---

How much --mem should I request for a RELION 5 particle-series refine of 50,000 particles, box 160, about 40 tilts per particle, on 4 GPUs? Our GPU nodes have 512 GB of RAM. Should I use --preread_images or --scratch_dir?
