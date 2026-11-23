---
name: relion-refine
description: Export cryo-ET particle series with WarpTools ts_export_particles --2d and run RELION 5 gold-standard 3D auto-refine (relion_refine_mpi) on a Slurm cluster or a workstation - preflight checks, reference/mask preparation, reference hand and greyscale checks, preread-vs-scratch RAM sizing, job submission, monitoring with crash/stall detection, and postprocess with an honest FSC readout (also for half-maps from other programs). Use this whenever the user wants to extract/export particles for RELION, refine a particle set, re-refine a subset, continue or resume a refinement, check why a refine is slow or stuck, size GPUs/MPI ranks/memory for relion_refine_mpi, or postprocess/measure a refinement or a pair of half-maps - even if they only say "refine these particles", "run auto-refine" or "export at 2 A box 200". Particle-series (2D) pipeline only, RELION 5+.
---

# RELION 5 particle-series refinement (export -> refine -> measure)

Takes picked particles on a WarpTools tilt-series project, exports them as 2D particle series, refines them with
RELION 5 gold-standard auto-refine and measures the result on a mask whose honesty is checked. The skill writes,
checks, SUBMITS and MONITORS the jobs. Every job script is driven by environment variables and submitted through
`cryoet_submit`; never edit the scripts per run. RELION 5's tomography pipeline only (RELION 3/4 subtomogram
workflows are different programs with different flags - do not mix advice).

Read `references/lessons.md` before anything non-routine (slow first iteration, odd FSC, comparing programs or
arms, duplicates, an external reference). `references/worked-example-empiar10499.md` shows the procedure on public
data.

## Setup check

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").


```bash
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh" || exit   # no config -> run the cryoet-workflow setup first
cryoet_require CRYOET_PYTHON                                          # numpy, scipy, mrcfile for the helpers
cryoet_have relion || echo "RELION not configured (RELION_ENV_SCRIPT empty, relion_refine_mpi not on PATH)"
cryoet_have warp   || echo "WarpTools not configured: export (step 2) unavailable; refining an existing export still works"
( cryoet_activate relion && relion_refine --version 2>&1 | head -3 )  # must report 5.x
( cryoet_activate relion && command -v "${RELION_MPI_LAUNCHER:-mpirun}" ) || echo "RELION env has no MPI launcher"
[ -n "${SITE_NOTES_FILE:-}" ] && cat "$SITE_NOTES_FILE"               # site rules (quotas, partitions) - obey them
```

- No config file: stop and point the user to the `cryoet-workflow` skill's setup. Never guess partitions, accounts
  or software paths.
- RELION missing or not 5.x: say so and stop (this skill cannot run without it). WarpTools missing: skip export and
  only work from existing particle-series stacks.
- `"$CRYOET_PYTHON"` runs every helper (`"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/<x>.py" --help`).
- `RELION_MPI_LAUNCHER` (`mpirun` | `srun`) decides how `cryoet_mpirun` starts ranks; `srun` needs RELION built
  against a PMI-capable MPI. `SCHEDULER=none` runs the same scripts locally in the background. If the launcher is
  not on PATH after `cryoet_activate relion`, every MPI job dies seconds in: tell the user to add the MPI module load
  to `RELION_ENV_SCRIPT` (or a wrapper env script) before submitting. refine3d/postprocess check this and exit 2.

## Inputs / Outputs (handoff)

| Artifact | Path pattern | Produced / consumed | Other skill |
|---|---|---|---|
| Tilt-series settings + processing folder (XMLs, `processed_items.json`), `.tomostar` dir | `<proj>/*.settings`, `<proj>/<processing>/` | consumed (export) | warptools-preprocess |
| Particle coordinate STAR (any picker; tomoDRGN-filtered; M species) | user path | consumed | any picker, tomodrgn-run, m-refine |
| M-refined XML folder (re-export after M) | `<m_project>/...xml` | consumed (copy, Cs reset) | m-refine |
| Exported particle series | `<OUTSTAR>.star`, `<stem>_tomograms.star`, `<processing>/particleseries/*.mrcs` | produced | tomodrgn-run (re-export with `PREMULT=0`) |
| Our optimisation set (pass as `--ios`) | `<stem>_abspath.star`, `<stem>_abspath_optimisation_set.star` | produced | m-refine, tomodrgn-run |
| Reference / mask on the export grid | `ref_<apix>A_box<N>_lp<L>.mrc`, `mask_<apix>A_box<N>.mrc` | produced | m-refine (same mask for re-measurement) |
| Refinement | `Refine3D/<job>/run_data.star`, `run_half{1,2}_class001_unfil.mrc`, `run_class001.mrc`, `RELION_JOB_EXIT_SUCCESS` | produced | m-refine (seed), tomodrgn-run (poses), chimerax-figures |
| Postprocess | `<OUTDIR>/postprocess{.mrc,_masked.mrc,.star,.log}`, `postprocess_locres_locres.mrc` | produced | chimerax-figures |
| `postprocess.sbatch` with `HALF1`/`HALF2`/`ANGPIX`/`OUTDIR` | called on foreign half-maps | consumed | m-refine (re-measure M maps on the RELION mask) |

## Always ask (do not default these)

1. **Export pixel size and box size** for `ts_export_particles --2d`. Offer context: Nyquist = 2 x pixel; the box
   should hold ~1.5-2x the particle diameter (e.g. a 300 A particle at 2.25 A/px: box 208 = 468 A).
2. **How many GPUs.** Then MPI ranks = GPUs + 1 (must be odd, >= 3); 8-12 threads per rank. Check what the
   partition allows first (`scontrol show partition`, `sacctmgr show qos`, `SLURM_MAX_GPUS_PER_JOB`): a request over
   a per-job cap pends forever rather than failing.

Confirm by reading files, not asking: the coordinate unit of the input STAR (`--coords_angpix`: M species use
Angstrom = 1; RELION/tomoDRGN stars their own pixel size; tomogram picks the tomogram's pixel size), the expected
particle and tilt-series counts, which processing folder holds the geometry, the particle diameter, and Cs/kV from
the Warp XMLs or `.settings` (else `MICROSCOPE_CS_MM`).

## Procedure

0. **Is an export needed at all?** If the particles were already exported at the wanted pixel size and box on the
   same tilt-series geometry, the stacks are still valid: run `make_optset.py` on the existing STAR (or a refined
   `run_data.star`) and go to step 3 - no GPU hours, no new stacks. Re-export when pixel size, box or geometry
   change, or to re-centre: build the input with `fold_origins.py --star <refined run_data.star> --out <x>.star`
   (folds `_rlnOrigin*Angst` into Angstrom centres) and export with `COORDS_ANGPIX=1`.
1. **Isolate the geometry.** Export from a COPY of the processing folder's tilt-series XMLs + `processed_items.json`,
   never the live folder. If M/MCore ever refined it, reset Cs to nominal and zero odd Zernikes in the copy -
   `"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/_lib/reset_ctf_cs.py" --zero_zernike_odd [--cs_mm <nominal>] --out_dir <copy> <xmls>` (`--dry_run` first) - but keep M-refined defocus, image
   warp and alignments.
2. **Export** - `scripts/export_particles.sbatch` (GPU, its OWN allocation). One-series test first
   (`SERIES=<id> TOMOSTAR_DIR=<dir>`), then the full set. Use `OUTPROC` for any second particle set at an already-used
   pixel size. Set `EXPECTED_N` / `EXPECTED_TS`. It ends with `make_optset.py`: our own optimisation set with absolute
   image paths, plus checks (count, optics pixel/box, premultiplied = 1, no negative coordinates, Cs, stale
   per-particle optics). Its FAIL lines stop the pipeline. A few particles fewer than expected is normal when
   `--max_missing_tilts` drops edge particles - report the number; with deselected tilts, raise `MAX_MISSING`.
3. **Duplicates** - `dedup_audit.py --star <..._abspath.star> --radius 20` before EVERY refinement; `--against
   <existing pool>` when adding supply; `--coords-angstrom` for a `fold_origins.py` output. Audit REFINED centres when
   they exist (re-picks converge during refinement). Cross-half pairs invalidate the FSC and cannot be fixed later.
   Fix with `--write`, say how many: `--policy drop --rank-col _rlnMaxValueProbDistribution` (removes the weaker twin)
   or `--policy same-half` (keeps N, moves each partner into its twin's half). Ask which if the user cares about N.
4. **Reference and mask** - `prep_reference.py` onto the exact export grid (pixel + box), low-passed (40 A own map;
   60 A external; 12-20 A when restarting from your own good map). Masks: clamped to [0,1], sized by VOLUME
   (`--mask-volume-check <A^3>`). **Hand:** an external reference's hand is not covered by the defocus-hand check;
   test it (step 5).
5. **Reference hand + smoke test - MANDATORY before the first full refinement whenever the reference did not come
   from these particles** (EMDB, another program or dataset). A wrong-hand seed does not error: it converges to the
   wrong hand and stalls several-fold worse than the data allow, after GPU-hours. Make both hands on the export grid
   (`prep_reference.py ... --out ref.mrc` and `... --flip z --out ref_zflip.mrc`), then `bench_iter1.sbatch` (1 GPU):
   - a. Arms `as|ref.mrc|60|` and `zflip|ref_zflip.mrc|60|` (no `--firstiter_cc`, N=200, ITER=1). Clearly sharper
     posteriors in one (fewer significant samples, higher MaxValueProb) = that hand. Flat in BOTH (median samples in
     the hundreds, MaxValueProb ~0) = greyscale -> `EXTERNAL_REF=1` (`--firstiter_cc --scale`), and go to b.
   - b. Same two arms with `--firstiter_cc --scale`, `ITER=3 N=1000`: compare the printed `_rlnCurrentResolution` and
     posteriors at iteration 3. Clearly better in one = that hand.
   - c. Still a tie, or the particles carry poses that do not come from this reference (published, earlier own
     refinement): reconstruct without it - a bench arm with `--skip_align` and `ITER=1` backprojects the given poses
     (`relion_reconstruct` cannot read Warp particle series), or a quick de novo model (`--grad --denovo_3dref`, see
     lessons) - and correlate that map, low-passed to a common resolution, with both hands; clearly higher wins.
   Decide only on a clear margin; otherwise say "hand undetermined" and ask before spending GPU-hours. Refine with
   the winning file and record it: `"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/_lib/project_state.py" add <PROJECT>
   decisions '{"what": "reference hand (<ref>)", "choice": "as-is|zflip", "evidence": "<arm: samples, maxprob, res>",
   "date": "<YYYY-MM-DD>"}'`. Fix greyscale and hand before touching I/O, MPI or particle count.
6. **Memory** - `estimate_ram.py --star <..._abspath.star> --gpus G --node-ram-gb <GPU node RAM>` decides
   `MODE=preread` or `MODE=scratch` and `--mem`. Never both modes; always an explicit `--mem`.
7. **Refine** - `scripts/refine3d.sbatch`:
   ```bash
   source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
   G=2; mkdir -p <OUT>
   CRYOET_SBATCH_OPTS="--chdir=<PROJECT> --ntasks=$((G+1)) --cpus-per-task=12 --mem=<estimate>G \
     -o <OUT>/slurm_%j.out -e <OUT>/slurm_%j.err" \
   IOS=<..._abspath_optimisation_set.star> REF=<ref> OUT=<Refine3D/jobNNN> MODE=<preread|scratch> DIAM=<A> MASK=<mask> \
     cryoet_submit gpu $G 48:00:00 "${CLAUDE_SKILL_DIR}/scripts/refine3d.sbatch"
   ```
   (Under `SCHEDULER=none`, cd to `<PROJECT>` and drop the sbatch options; set `NGPU` if `CUDA_VISIBLE_DEVICES` is
   unset. If the site sets `SBATCH_EXPORT=NONE`, add `--export=ALL` to `CRYOET_SBATCH_OPTS`.) New job dir per
   refinement; resubmitting the identical command continues from the newest complete iteration. For a global first
   iteration of hours (big set, large box) raise `STALL_MIN` (>= 480 for ~3 h iterations).
8. **Monitor** (below) until `RELION_JOB_EXIT_SUCCESS`, a crash or a stall.
9. **Postprocess** - `scripts/postprocess.sbatch` (CPU) with the mask on the export grid:
   `JOBDIR=<OUT> MASK=<mask> cryoet_submit cpu 0 04:00:00 "${CLAUDE_SKILL_DIR}/scripts/postprocess.sbatch"`. For
   another program's half-maps pass `HALF1 HALF2 ANGPIX OUTDIR` instead of `JOBDIR`. Local resolution: `LOCRES=1`
   plus `--ntasks=16 --cpus-per-task=1` in `CRYOET_SBATCH_OPTS` (a separate `--locres` call with `--adhoc_bfac` =
   the fitted B-factor: relion_postprocess refuses `--auto_bfac` with `--locres`). It prints FSC 0.143 and
   `fscrand_hi` (must be <= 0.05).

**Report:** particles in, particles in `run_data.star`, iterations, final resolution (postprocess, masked),
fscrand_hi, median MaxValueProb / significant samples, mask used (file + enclosed volume), duplicates removed. Give
raw counts next to every fraction.

## Submitting and monitoring

- Before submitting: show the user the exact command (resources + env) with the site values the config resolves to
  (`cryoet_sbatch_args gpu $G 48:00:00`). Submit, record the job id and job dir in the conversation (and in a project
  log if the project keeps one). If a submit call was interrupted, check `squeue -u $USER` before resubmitting.
- Progress: `"$CRYOET_PYTHON" "${CLAUDE_SKILL_DIR}/scripts/refine_status.py" --jobdir <OUT> --slurm-job <ID>
  [--input-n N] [--stall-min <the job's STALL_MIN>]` (`<ID>` may be `local:<pid>`): iteration table, posteriors, fatal
  log patterns, success marker, stall test. Wait in the background at an interval matched to the iteration time
  (10-30 min) - never a tight polling loop on a login node.
- On a verdict:
  - `CRASHED` (the watchdog already stopped the launcher): read the log lines; for GPU/MPI errors resubmit the same
    command (it continues). Two crashes on one node -> exclude that node (`--exclude=<node>` in
    `CRYOET_SBATCH_OPTS`) or drop to 2 GPUs / 3 ranks.
  - `STALLED`: cancel, resubmit (continues). If iteration 1 is the slow one, it is greyscale, not I/O (step 5).
  - `OSCILLATING`: angle changes rising with flat resolution -> oversized mask or missing `--solvent_correct_fsc`.
  - `DONE`: the marker is authoritative; the scheduler may show FAILED (exit 134/139) from a crash in MPI teardown.
- Cancelling or resubmitting a running job the user started: ask first.

## General rules

- **Coordinates.** In the export's OUTPUT STAR, coordinates are in export pixels (`_rlnImagePixelSize`), not
  tilt-series pixels. A wrong `--coords_angpix` shifts every particle; check by Angstrom extent vs tomogram size.
- **Premultiplied for RELION**, not premultiplied for tomoDRGN (`PREMULT=0`, see tomodrgn-run).
- **Same pixel size, different set = clobber.** Stacks are named by pixel size + index: use `OUTPROC`.
- **Preread vs scratch.** Preread RAM ~= one float copy x (GPUs + 2) + working set. If it does not fit, stage to
  node-local scratch (`SCRATCH_ROOT`, job-unique, cleaned on exit) - never a near-full network mount; if neither fits,
  read in place. Check scratch free space against the stacks' size.
- **External references** (EMDB, other software, other dataset) are on an arbitrary greyscale: symptoms are flat
  posteriors, "estimated accuracy angles" of tens of degrees and an absurd iteration-1 ETA. Fix with `--firstiter_cc
  --scale` (`EXTERNAL_REF=1`), never `--maxsig`. Diagnose WITHOUT `--firstiter_cc` - with it iteration 1 always looks
  perfect (1 sample, MaxValueProb 1.0).
- **Hand.** A wrong-hand seed converges to the wrong hand and stalls. Test both hands (step 5) BEFORE the first
  full refinement from any external reference, and record the choice. Before
  comparing with or depositing next to a public map, check the final map's hand against it (fit both the map and its
  Z-flip; the much better fit is the right orientation) - RELION's `_rlnTomoHand` is a CTF/defocus convention, not a
  fix for a mirrored map.
- **Sampling.** `--healpix_order 2` global start; each halving of the angular step costs ~8x. Offsets are in EXPORT
  pixels.
- **`--solvent_correct_fsc` with every solvent mask**, or the mask does not drive sampling.
- **Honest FSC.** fscrand_hi <= 0.05 or the mask is too tight; compare arms on ONE mask; rescale a mask by pixel size
  before padding it into a bigger box; never compare a RELION FSC with M's own FSC (M grows its mask) - re-measure M
  half-maps with `postprocess.sbatch HALF1/HALF2` on the RELION mask. An FSC that plateaus at ~0.1 toward Nyquist
  instead of decaying means cross-half duplicates, which fscrand_hi cannot detect.
- **A consensus map is not an independent check.** `run_class001.mrc` (or any map refined from the same
  particles) shares their noise and poses: agreement with it beyond its own FSC resolution proves nothing, and
  features finer than that are not validated by it. Cross-check against a map from different particles or an
  atomic model, and compare half-maps only on one mask.
- **Pixel size for postprocess** from the optics table, not the half-map header (RELION rounds it).
- **The success marker, not the exit code,** decides whether a refine finished.

## Never

`--delete_intermediate` (continue needs iterations) · `--maxsig` (turns a flat posterior into arbitrary,
reference-biased poses) · `--preread_images` with `--scratch_dir` · `relion_refine_mpi` with `--denovo_3dref` (use
single-process `relion_refine --grad --denovo_3dref`, see lessons) · comparing arms on different masks, or a RELION FSC
against an M FSC · joining STARs on `_rlnTomoParticleName` (renumbered every export; join on TomoName + coordinates)
· a typed GPU or partition in a command (they come from the config) · writing into the master geometry folder, a
reference project or another user's folders.

## References

- `references/lessons.md` - the rules above with their symptoms and checks (export, layout, greyscale, hand, masks,
  measuring, shell traps in job scripts).
- `references/worked-example-empiar10499.md` - the procedure on a public ribosome dataset.
- Script headers (`bash <script>.sbatch --help`, `"$CRYOET_PYTHON" <script>.py --help`) document every variable.
