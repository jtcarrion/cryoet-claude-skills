# cryoet-claude-skills

Claude Code skills for cryo-electron tomography subtomogram averaging, from raw tilt series to a refined map and a
figure. They work on any Slurm cluster, or on a single workstation, and use whatever software your site has installed.

| skill | what it does | needs |
|---|---|---|
| `cryoet-workflow` | **Start here.** Sets up your config, reports which stages can run on your machine, plans the pipeline with you and runs each stage in a subagent | - |
| `warptools-preprocess` | WarpTools 2.0: motion/CTF, import, alignment (etomo patches/fiducials, AreTomo3, imported alignments), defocus-hand check, tilt-series CTF, reconstruction; several alignment arms side by side | WarpTools (+ IMOD / AreTomo3 for those aligners) |
| `teamtomo-preprocess` | [teamtomo-workflows](https://github.com/jtcarrion/teamtomo-workflows): tomograms from Warp XMLs, or TeamTomo alignment + CTF + reconstruction written back as a Warp arm | teamtomo-workflows env |
| `relion-refine` | `ts_export_particles --2d` and RELION 5 gold-standard auto-refine: preflight, reference/mask prep, RAM/scratch sizing, monitoring, postprocess with an honest FSC readout | RELION 5, WarpTools |
| `m-refine` | M (MTools/MCore) multi-particle refinement on a cloned population, staged by round, with audit and overfitting checks | WarpTools/M build |
| `tomodrgn-run` | [tomoDRGN](https://github.com/bpowell122/tomodrgn) VAE training, k-means analysis, class review, selections mapped back to RELION/Warp | tomoDRGN |
| `chimerax-figures` | ChimeraX `.cxc` scripts + map bundles: single maps, local-resolution colouring, side-by-side comparisons, model + ligand close-ups; configurable style | ChimeraX (local is fine); optional [calc_level_ChimeraX](https://github.com/mariacarreira/calc_level_ChimeraX) |

Stages whose software you don't have are skipped. Particle picking is not included yet; bring a coordinate STAR from
any picker. <!-- TODO(jolt-preprint): jolt-picker skill -->

## Install

As a Claude Code plugin (recommended):
```
/plugin marketplace add jtcarrion/cryoet-claude-skills
/plugin install cryoet-skills@cryoet-tools
```
Or copy the skill folders: `cp -r skills/* ~/.claude/skills/` (the stage agents in `agents/` are only used in <!-- lint: allow -->
plugin mode; the director falls back to general subagents).

## Running it

**Login and launch.** Open Claude on the CLI the normal way (`claude` or `claude agents`) and simply ask 
your Claude **"Please help me set up the cryo-ET skills"**.

**First session: setup and intake.** The `cryoet-workflow` skill probes your site 
(Slurm partitions, GPU request format, installed packages, etc.), asks you simple questions about the data, 
and writes it all inside `~/.config/cryoet-skills/config.sh`. 
Note: Ask Claude **"what can I run here?"** to show which tools are supported. (Warp, RELION, TomoDRGN, M, TeamTomo, Chimerax)

**Then one session per stage.** Approve a stage, let it submit, and leave. If you come back in a **new** session, 
just say **"resume the project in /path/to/dir"**. The project record (`cryoet_project.json`) carries every decision, path and job id,
so nothing is lost, and short sessions cost far less than one long one!

**What to expect** (end-to-end test, EMPIAR-10499, 6 tilt series, 2,813 ribosomes, raw movies to a 7.3 A M map):

| | |
|---|---|
| GPU | about 15 A100-hours |
| Disk | about 40 GB (raw movies symlinked) |
| Claude usage (API-equivalent) | about $2-6 per turn in fresh per-stage sessions, up to $20/turn late in one long session; $123 for the whole test, which was run mostly as one long session |
| Your time | about 25 short replies: setup, intake, one approval per stage, and the decision gates (alignment, defocus hand, particle check, map hand, tomoDRGN classes, M rounds) |

## Layout
```
.claude-plugin/   plugin.json, marketplace.json
skills/<skill>/   SKILL.md, scripts/ (+ scripts/_lib: vendored shared library), references/, templates/
agents/           one stage agent per skill (plugin mode)
lib/              canonical shared library: config loader (bash + python), STAR reader, project hand-off record
config/           config.example.sh: every config key, documented
evals/            `claude plugin eval` cases (routing + behaviour; no cluster data needed)
tools/            lint.py (portability/static checks), sync_lib.sh (vendor lib/ into skills)
docs/             DESIGN.md, CONVENTIONS.md (rules for contributors)
```

## Contributing
Edit `lib/` and run `tools/sync_lib.sh`, never the vendored `_lib` copies. Before a PR: `python3 tools/lint.py`
(0 errors) and `claude plugin eval . --runs 1`. Follow `docs/CONVENTIONS.md`: no site paths, partitions or typed
GPU requests in shipped files; dataset specifics go in `references/worked-example-*.md`.

## License
MIT. These skills drive third-party software (WarpTools/M, RELION, IMOD, AreTomo3, tomoDRGN, TeamTomo, ChimeraX);
cite those tools in your work as their authors request.
