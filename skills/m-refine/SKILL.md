---
name: m-refine
description: Run M (MTools / MCore / EstimateWeights, Warp 2.0) multi-particle refinement of cryo-ET particles on a Slurm cluster or a workstation, seeded from a RELION refinement - isolated population creation from a Cs-reset copy of the tilt-series XMLs, MCore --iter 0 baseline, round-by-round refinement following the M paper schedule (stage angles, image warp, volume warp, poses, CTF, tilt movies, magnification, Zernike), optional per-tilt / per-series weight estimation, per-round snapshots, the box-128 no-op guard, an audit of which XML terms moved, re-measurement on the fixed RELION mask and the cross-FSC overfitting guard, plus species swaps and particle-set tests in clones. Use this whenever the user mentions M, MCore, MTools, EstimateWeights, a population or species, multi-particle refinement, image warp, refining tilt-series geometry/CTF with particles, or wants to push a RELION map further with M - even if they just say "run M on this".
---

# M refinement (MTools / MCore / EstimateWeights)

M refines tilt-series geometry (image warp, stage angles, volume warp), CTF, magnification and particle poses jointly
against a reference, starting from a RELION refinement of WarpTools particle series. This skill builds an ISOLATED
population, measures an iter-0 baseline, then runs one MCore invocation per round, each snapshotted, audited for which
XML terms moved, and re-measured on the fixed RELION mask with a cross-FSC overfitting guard. It reads RELION output
(relion-refine) and Warp tilt-series XMLs (warptools-preprocess); its refined XMLs and species go back to relion-refine
or tomodrgn-run.

## Setup check

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").


```bash
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh" || exit 2   # no config -> run cryoet-workflow setup
cryoet_require CRYOET_PYTHON                                          # numpy, scipy, mrcfile for the helpers
cryoet_have m || echo "M not configured"                              # WARP_ENV_SCRIPT, or MCore on PATH
( cryoet_activate m && command -v MTools MCore EstimateWeights )      # check in a subshell; jobs activate themselves
```

- If `cryoet_have m` fails: tell the user M (Warp 2.0: MTools, MCore, EstimateWeights) must be installed and
  `WARP_ENV_SCRIPT` set via the cryoet-workflow setup. Stop; do not search the filesystem for a Warp build.
- If `EstimateWeights` alone is missing, skip only the weights round.
- Read `SITE_NOTES_FILE` if set. GPU partition/account/gres all come from the config via `cryoet_submit`.
- Check the MCore build's flags once: `MCore --help` (flag names change between Warp builds; this skill uses
  `--devicelist --perdevice --task_dir --port`). Older builds without `--perdevice`/`--task_dir` need the FLAGS adjusted.
- Nominal Cs: `MICROSCOPE_CS_MM`, else the XMLs' own `<OptionsCTF>` Cs (the value ts_ctf used), else ask.

## Inputs / Outputs (handoff)

| artifact | path pattern | produced / consumed | by |
|---|---|---|---|
| RELION particles (poses; coords in `_rlnImagePixelSize` units, shifts in A) | `Refine3D/<job>/run_data.star` | consumed | relion-refine |
| Unfiltered half-maps | `run_half{1,2}_class001_unfil.mrc` | consumed | relion-refine |
| Cross-FSC guard map: external map of the same complex (preferred), else RELION map + its resolution | `GUARD_REF` (e.g. hand/pixel-matched EMDB map) or `run_class001.mrc` + `RELION_RES` | consumed | user / relion-refine |
| Soft mask on the export grid (measurement mask) | `mask_<apix>A_box<N>.mrc` | consumed | relion-refine |
| Sharpened map (for the binary mask) | `postprocess.mrc` | consumed | relion-refine |
| Tilt-series XMLs + `processed_items.json`, `.settings`, `.tomostar` | `<warp_dir>/*.xml`, `<name>.settings` | consumed (COPIED) | warptools-preprocess |
| Particle subsets for a new species | STAR | consumed | tomodrgn-run |
| Population | `<NEWROOT>/<POP>.population`, `create.env`, `round_<LABEL>.env` | produced | m-refine |
| M-refined XMLs (re-export input) | `<NEWROOT>/warp_tiltseries_m/*.xml` + `processed_items.json`, `<settings>_m.settings` | produced | relion-refine, tomodrgn-run |
| Species (half-maps, M particle table in A with temporal samples) | `<NEWROOT>/species/<sp>_<id>/<sp>_{half1,half2}.mrc`, `<sp>_particles.star` | produced | relion-refine (`--coords_angpix 1` style export), tomodrgn-run |
| Per-round record | `rounds/<LABEL>_<sp>/`, `snapshots/before_<LABEL>/`, `rounds_measured.csv` | produced | m-refine, chimerax-figures |
| Final half-maps for postprocess | `rounds/<best>_<sp>/<sp>_half{1,2}.mrc` + species pixel | produced | relion-refine (postprocess) -> chimerax-figures |

Project record (if the project has `cryoet_project.json`): read the seed from
`"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/_lib/project_state.py" get <PROJECT> refinements` (half1/half2/mask/
angpix/data_star), and after iter 0 append the population:
`project_state.py add <PROJECT> m_populations '{"name":..,"population":..,"source_refinement":..,"rounds_dir":..}'`;
update `best_round`/`resolution_A` (RELION-mask number) as rounds finish, and add the final map to `maps[]`.

## Procedure

Ask before running: (1) the seed - which RELION refinement (poses, unfil half-maps, soft mask), particle count, and the
tilt-series XML folder; (2) GPUs and wall time (MCore uses every listed GPU; 3-4 large-memory GPUs and 300-400 GB RAM
are typical for a few tens of thousands of particles); (3) the schedule (`references/recipe.md`): full M-paper schedule,
geometry-only, or iter 0 only - recommend from particles per tilt series and the goal, and confirm before every round
that adds a new term; (4) temporal samples (1, or 3 pose trajectories as in the paper) and the species pixel/box.

Every job takes an env FILE (bash `KEY=VALUE`), not `sbatch --export` (which splits values on commas). The file is
copied into the population as the round's record. Submit with `cryoet_submit`; under `SCHEDULER=none` the same script
runs locally.

1. **Binary mask** (CPU, interactive is fine):
   `"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/make_binary_mask.py" --map postprocess.mrc --soft-mask <RELION soft mask> --mw-kda <MW> --out <mask_binary.mrc>`
   (or `--volume <A^3>`; there is no default size).
2. **Seed check** (optional, read-only): `"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/_lib/reset_ctf_cs.py" <xml_dir> --out_dir /tmp/x --zero_zernike_odd --dry_run`
   shows whether a previous M run left a fitted Cs / odd Zernikes. `create_population.sbatch` resets them in its
   private copy (`RESET_SEED=1`, default); the seed folder itself is never written.
3. **Population + iter 0**: write `create.env` (variables documented at the top of
   `scripts/create_population.sbatch`: NEWROOT, POP_NAME, SPECIES_NAME, SEED_XMLS, SETTINGS_SRC, PARTICLES, HALF1/2,
   MASK_BIN, TRUE_ANGPIX, DIAMETER, SYM, ANGPIX_RESAMPLE, LOWPASS, RELION_MASK, RELION_RES, GUARD_REF, GUARD_REF_KIND,
   REF_APIX, TEMPORAL), then
   ```bash
   CRYOET_SBATCH_OPTS="--output=<NEWROOT>.create_%j.out" \
     cryoet_submit gpu 4 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/create_population.sbatch" create.env
   ```
   Iter 0 refines nothing (xml_diff runs with `--expect none`; it compares numerically, so MCore's first-write
   rewrite of empty Zernike lists as zeros and its fill-in of a placeholder `VolumeDimensionsAngstrom` Z are reported
   as `ok`/`info`, not as changes). `check_transfer.py` then runs whatever the audit said: M positions vs RELION's
   `coord x pixel - origin` (< 0.5 A), particle count, and the iter-0 RELION-mask FSC0.143 vs `RELION_RES` (the
   transfer cost: within a few tenths of an A). A large gap is a transfer problem (pixel size, hand, particle table) -
   stop and look. The job ends with a one-line summary (MCore | audit | measurement | transfer); exit 5 = transfer
   failed, 3 = audit flagged with transfer PASS (read the flagged terms before treating iter 0 as invalid).
4. **Rounds**: one env file per round, e.g. `<popdir>/round_r1.env`:
   ```bash
   POPULATION=/abs/pop/pop.population
   LABEL=r1
   FLAGS="--refine_imagewarp 5x5 --refine_stageangles --refine_volumewarp 8x8x2x10 --refine_particles"
   EXPECT="GridMovement:GridAngle:GridVolumeWarp"
   RELION_MASK=/abs/mask_soft.mrc
   GUARD_REF=/abs/external_map_on_halfmap_grid.mrc   # see "Cross-FSC guard" below
   GUARD_REF_KIND=external                            # or: relion (+ RELION_RES=<A>) for run_class001.mrc
   REF_APIX=<pixel of GUARD_REF>
   ```
   `cryoet_submit gpu 4 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/mcore_round.sbatch" <popdir>/round_r1.env`.
   The job: lock -> box-128 check -> snapshot -> [EstimateWeights] -> MCore `--port $(cryoet_port)` -> audit (log
   "Final score" count, `xml_diff.py`) -> save round -> own-FSC + fscrand_hi + cross-FSC appended to
   `rounds_measured.csv` with a `GUARD ok|FELL` line vs the previous row on the same guard map. The audit runs even if
   MCore fails; the job still fails with MCore's exit code.
   Continue while the RELION-mask FSC improves AND cross-FSC does not fall; add a term group only after the previous
   set plateaus; stop at gains of a few hundredths of an A.
5. **Weights round (optional, late)**: after geometry/CTF plateau, `WEIGHTS="--resolve_items"` (per tilt series) or
   `WEIGHTS="--resolve_frames"` (per tilt, averaged over series) in a round env file. The job runs
   `EstimateWeights --population P --source <source> $WEIGHTS` first (it reads the `*_fsc.mrc` the previous MCore round
   left in `<popdir>/refinement_temp/<source>/`), then MCore with your FLAGS (may be empty = reconstruct with the new
   weights). Typical gain is small (a few tenths of an A at best); judge it like any other round.
   `EstimateWeights --reset` undoes all fitted weights (or restore the snapshot).
6. **Revert** a bad round (with the user's OK): copy `snapshots/before_<LABEL>/*.xml` back into the processing folder
   and restore the previous species version (M keeps versions; `rounds/<previous>_<sp>/` has the files).
7. **Particle-set tests / swaps** - always in a CLONE of the population (copy the population folder, then rewire its
   `.settings` ProcessingFolder to the clone's XML folder, as create_population does): `MCore --iter 0` per species
   for set A/Bs at fixed geometry. A new pixel size or particle set = a NEW species built from M's latest half-maps and
   M's own particle table (`MTools create_species ... --particles_m`, keeps trajectories); then remove the old species.
8. **Final**: invoke the **relion-refine** skill's postprocess with `HALF1=rounds/<best>_<sp>/<sp>_half1.mrc
   HALF2=.._half2.mrc ANGPIX=<species PixelSize> MASK=<RELION soft mask> OUTDIR=<popdir>/postprocess_<best>` (plus
   local resolution if wanted). Report that number, not M's own.

Monitoring: show the env file and the submit line, submit, record job ids; poll `squeue -j` sparingly (rounds take
10 min - several hours; tilt movies and magnification are the slow terms). Per round read: m_status output, the
"Final score" count, xml_diff, and the measured row. Ask before cancelling a job the user started.

## General rules (symptom -> check)

- **Isolation.** MCore writes refined Cs, Zernikes, magnification, warp grids and weights back into whatever
  processing folder its source points at. A shared or master folder silently becomes "M-refined" for everyone, and a
  new population seeded from it inherits fitted Cs (symptom: Cs far from nominal in `<CTF>`; check with
  `reset_ctf_cs.py --dry_run`). Every population gets a PRIVATE XML copy; decisions are made in CLONES.
- **Populations are rewritten in place.** Every MCore run changes the population's XMLs and species. Never run a test
  in the main population; clone first. One population = one job at a time (the scripts take a lock dir `.m_lock`).
- **Measure on the RELION mask.** M grows its mask by ~1.5 x GlobalRes, so its number is not a RELION number (it
  usually looks worse on identical poses). Every round is re-measured with `measure_halfmaps.py` on the fixed RELION
  soft mask; fscrand_hi must stay <= 0.05. Never measure on M's stored binary mask (too tight).
- **Cross-FSC guard.** Image warp, stage angles, volume warp, CTF, magnification and weights are fitted from BOTH half
  sets, so the own-FSC can rise from overfitting. Real gain = own-FSC up AND cross-FSC vs a guard map (the same file
  for iter 0 and every round) not down (ideally up). Own up with cross down = overfitting: revert. Own up with cross
  flat = unproven: prefer the simpler model unless the next round confirms it. Use M's unfiltered half-maps (never
  `*_filt.mrc`, which is low-passed at M's own resolution).
  <!-- NEEDS AUTHOR REVIEW: the guard-map choice below (external map preferred; RELION map only below its resolution)
  is a rule change proposed from one end-to-end test and must be approved by the original author. -->
  **Which guard map.** RELION's `run_class001.mrc` is NOT independent beyond its own resolution: it is built from the
  same particles and poses, so its cross-FSC there is shared noise - high at iter 0, falling as soon as M moves poses,
  which flags a real gain as overfitting. Symptom: own-FSC and both half-maps improve, cross-FSC vs RELION drops at
  frequencies finer than the RELION resolution. Check: measure against an external map. Default: `GUARD_REF` = a map
  not built from these particles (EMDB entry of the same complex, resampled to the half-map grid, hand-checked;
  `GUARD_REF_KIND=external`), or a held-out-particle reconstruction. Without one, use the RELION map with
  `GUARD_REF_KIND=relion RELION_RES=<A>`: only resolutions coarser than RELION_RES are scored and a caveat is printed.
  Switching guard maps mid-series: re-measure the iter-0 round on the new map first (`measure_halfmaps.py`).
- **Box exactly 128 px = silent no-op.** Every series logs "Final score: 0", nothing is refined, the job "succeeds".
  `m_status.py` predicts the box (species box x 2 x pixel / GlobalResolution, even); `mcore_round.sbatch` refuses 128.
  Fix: nudge the species GlobalResolution so the box is 126 or 130 (user's OK).
- **Which terms to stage when.** Geometry first (stage angles + image warp + volume warp, poses if the set is dense),
  then per-tilt defocus (`--ctf_defocus`) once the species is finer than `--ctf_minresolution` (default 8 A - above it
  the whole CTF block is silently skipped), then tilt movies, then magnification, then 3rd-order Zernike; weights last.
  One new term group per round, each judged on its own.
- **Keep the grid size.** `--refine_imagewarp WxH` / `--refine_volumewarp XxYxZxT` RESAMPLES an existing field to the
  requested size; a different size destroys the inherited deformation. Repeat the stored size every round (xml_diff
  fails the round on a lossy resize unless `ALLOW_RESIZE=1`). Choose the first grid with the detector's aspect ratio.
- **Particle density decides.** Particles per tilt series predicts whether NEW shared terms can be fitted: several
  hundred/TS refine well; well under ~150/TS, refinement from that set alone tends to hurt. Then use iter 0 (M as a
  reconstructor), geometry only without `--refine_particles`, or a dense companion species that carries the geometry
  (M counts particles across all species for `--min_particles`; judge only the subset species). Never merge
  overlapping sets into one species (duplicates). A heuristic from two datasets - state it as such.
- **Poses.** M refines locally toward its current reference: gross pose errors survive any number of rounds (fix them
  with a RELION global search); poses better than the reference get dragged back. Poses and image warp are frame-locked
  to the alignment: never carry them into a different tilt-series alignment. Importing new RELION orientations as a
  single-pose table discards M's trajectories - re-anchor them instead (recipe.md).
- **XMLs differ byte-wise after every run** (re-serialised) - compare parsed values (`xml_diff.py`), never `cmp`.
- **Silent fast round with no "Final score" lines**: series skipped by `--min_particles`, or the `.tomostar` files
  were rewritten after the species was created (M matches particles to series by a hash of the name + file head).
  Never rewrite tomostars under a live population. Refine-log names differ between builds; the script globs `*refine*.log`.
- **Ports and scratch.** MCore opens a REST port (default 14300): two jobs on one node collide unless each gets
  `--port $(cryoet_port)`. Task dirs go to job-unique scratch (`cryoet_scratch`), cleaned on exit.
- **OPEN**: whether series skipped by `--min_particles` still contribute to the reconstruction is not settled; check
  (particle count in the reconstruction log, or iter-0 FSC with and without) before relying on either reading.

## References

- `references/recipe.md` - the M-paper schedule as a generic default, schedule choice by density, re-anchoring poses,
  the CTF gate, weights.
- `references/lessons.md` - the detailed lessons behind the rules above (mask convention, transfer cost, overfitting,
  resize trap, logs, weight threshold).
- `references/worked-example-empiar10499.md` - the public EMPIAR-10499 ribosome run (schedule, outcome, caveats).
- `scripts/` - `create_population.sbatch`, `mcore_round.sbatch`, `xml_diff.py`, `check_transfer.py`, `m_status.py`,
  `measure_halfmaps.py`, `make_binary_mask.py`; `_lib/reset_ctf_cs.py` (shared).
