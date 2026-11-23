---
name: tomodrgn-run
description: Run tomoDRGN heterogeneity analysis on cryo-ET particle series from WarpTools - export with ts_export_particles --2d --dont_premultiply, prepare and check the STAR (premultiply flag, negative coordinates, stale optics columns, tilts per particle, Cs, data polarity), smoke-test, queue tomodrgn train_vae and analyze (k-means, default 50 and 100) as Slurm or local jobs, monitor training, build a class-review aid against the consensus map, then turn the user's class choice into filtered STARs mapped back onto any RELION/Warp particle set by tomogram + coordinates with a many-to-one check. Use this whenever the user wants to clean particles with tomoDRGN, train a tomoDRGN VAE, analyze/cluster a latent space, pick or filter tomoDRGN classes, map tomoDRGN selections back to RELION, or troubleshoot a tomoDRGN run (hollow or inverted volumes, crashes, OOM) - even if they just say "run tomodrgn on these particles".
---

# tomoDRGN: export -> prepare -> smoke test -> train -> analyze -> user selects -> filtered STARs

tomoDRGN learns a latent space of per-particle structural variation from tilt-series particle images. In practice it
is used to remove junk and mis-posed particles and to separate conformations before (re)refinement. This skill takes a
refined particle set, exports it non-premultiplied, checks it, trains `tomodrgn train_vae`, clusters with
`tomodrgn analyze`, helps the user review classes against the consensus map, and maps the user's choice back onto any
particle STAR. The user picks the classes; the scripts only rank and report. Never modify the tomoDRGN code base: read
its installed source (`python -c "import tomodrgn, os; print(os.path.dirname(tomodrgn.__file__))"`) to answer
questions about it.

## Setup check (do this first)

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").


```bash
S="${CLAUDE_SKILL_DIR}"
source "$S/scripts/_lib/cryoet_config.sh" || echo "no config: run the cryoet-workflow skill's setup first, then stop"
cryoet_require CRYOET_PYTHON
cryoet_have tomodrgn || echo "tomoDRGN NOT CONFIGURED"
( cryoet_activate tomodrgn && tomodrgn --version )      # in a subshell; prints e.g. "tomoDRGN v1.0.5"
[ -n "${SITE_NOTES_FILE:-}" ] && cat "$SITE_NOTES_FILE"  # site rules (maintenance windows, limits)
```
- **No config**: hand off to `cryoet-workflow` setup; do not guess partitions or env paths.
- **tomoDRGN not configured** (`cryoet_have tomodrgn` fails, or activation finds no `tomodrgn`): tell the user tomoDRGN
  is not installed/configured, point them to the install instructions at https://github.com/bpowell122/tomodrgn
  (README / docs), and say they then set `TOMODRGN_ENV` in the config (`conda:<env>`, `venv:<path>`, `module:<name>`
  or an env script to source). **Stop** - do not install it, do not write job scripts that call a guessed binary.
  The explanation-only parts (reading an existing run's `run.log`, answering conceptual questions) still work.
- Flags here were checked against tomoDRGN 1.0.5 `--help`. On another version, check `tomodrgn <cmd> --help` for any
  flag you use before submitting.
- Requires WarpTools 2.0 `ts_export_particles --2d` output (RELION 5 particle-series STAR + optimisation set).

## Inputs / Outputs (handoff)

| artifact | path pattern | produced / consumed | by |
|---|---|---|---|
| refined particle STAR (origins folded into centres) | `<refine>/run_data.star` | consumed | relion-refine (or m-refine) |
| Warp project (tilt-series XMLs, settings) | `<warp project>/` | consumed | warptools-preprocess |
| non-premultiplied particle export | `<stem>_abspath.star`, `<stem>_abspath_optimisation_set.star`, `<stem>_tomograms.star` | consumed | relion-refine (export step with `--dont_premultiply`) |
| consensus map in the same particle frame + its A/px | `*.mrc` | consumed | relion-refine / m-refine |
| tomoDRGN-ready STAR + optimisation set | `<stem>_tomodrgn.star`, `<stem>_tomodrgn_optimisation_set.star` | produced | this skill (`prep_tomodrgn_star.py`) |
| training run | `<OUTDIR>/{config.pkl,weights.N.pkl,z.N.pkl,run.log,*_tomodrgn_preprocessed.star}` | produced | this skill (`train_vae.sbatch`) |
| k-means analysis | `<OUTDIR>/analyze.<E>_k<k>/kmeans<k>/{labels.pkl,centers.txt,vol_NNN.mrc}` | produced | this skill (`analyze.sbatch`) |
| review aid | `<analyze dir>/{classes.tsv,summary.txt,montage.png}` | produced | this skill (`review_classes.py`) |
| class volumes for viewing | `vol_NNN.mrc` | produced -> consumed | chimerax-figures |
| kept particles | `<out>_kept_tomodrgn.star`, `<out>_kept_ind.pkl`, `<out>_kept_<target>.star` | produced -> consumed | relion-refine, m-refine |

Project record (`<PROJECT>/cryoet_project.json`, if the project has one): read inputs with
`"$CRYOET_PYTHON" "$S/scripts/_lib/project_state.py" get <PROJECT> refinements` (data_star, angpix, maps). After a
selection, append
`project_state.py add <PROJECT> tomodrgn '{"name":..,"train_dir":..,"epochs":..,"analyze_dirs":[..],"selected_classes":[..],"selection_star":..}'`
and, per mapped target STAR, `project_state.py add <PROJECT> particle_sets '{"name":..,"star":..,"coords_angpix":..,"n_particles":..,"source":"tomodrgn-run","parent":..}'`.
Also tell the user: export A/px and box, polarity verdict (UNINVERT), ZDIM/EPOCHS/BATCH, job ids, mapped counts
(matched / kept / many-to-one).

## Always ask (never default silently)

1. **Export pixel size and box.** tomoDRGN works at coarser sampling than refinement: box roughly 64-128 px, Nyquist
   around 2x the smallest feature you care about (for ribosome-sized particles, ~4-8 A/px is typical).
2. **Model size, every run**: `ZDIM`, `EPOCHS`, `BATCH`. Starting points: zdim 8 for junk/pose cleaning; larger
   (32-128) only for rich conformational heterogeneity, which needs more epochs. `--lr` is defined for batch 1 and
   tomoDRGN scales it by sqrt(batch), so large batches mean fewer updates per epoch and need more epochs.
3. **GPUs and walltime.** 1 GPU is fine; `MULTIGPU=1` splits the GLOBAL batch over GPUs (sub-linear speed-up at small
   batch). Estimate walltime = load time + epochs x minutes/epoch (measure minutes/epoch in the smoke test or the
   first epochs) + margin; it is capped at `SLURM_MAX_WALLTIME`.

Also determine from the files: coordinate units (`--coords_angpix`), expected counts, the consensus map and its pixel
size. If the particle set may contain re-picks, run relion-refine's cross-half duplicate audit first.

## Procedure

1. **Export** with the relion-refine skill's export step, non-premultiplied (`ts_export_particles --2d
   --dont_premultiply`), otherwise the SAME command as for RELION. Fold refined `_rlnOrigin*Angst` into the centres
   first (relion-refine's origin-folding step) and drop particles with negative coordinates. One-series test first.
2. **Prepare** (CPU, interactive is fine for small sets; use a CPU job for large ones):
   `"$CRYOET_PYTHON" "$S/scripts/prep_tomodrgn_star.py" --star <export>_abspath.star [--cs <mm>]`
   FAILs on premultiplied data, negative coordinates, < 10 tilts per particle (every particle checked); strips stale
   per-particle optics columns; WARNs on per-group Cs (reset with `scripts/_lib/reset_ctf_cs.py`, re-export); prints
   the data polarity verdict and the in-RAM size (-> `--mem` or `LAZY=1`). Writes the optimisation set for training.
3. **Smoke test** (1 epoch, 200 particles, minutes) - checks mechanics only:
   ```bash
   "$S/scripts/submit_tomodrgn.sh" train --time 00:30:00 --log <OUTDIR>_smoke.%j.out \
       OPTSET=<..._tomodrgn_optimisation_set.star> OUTDIR=<runs/name>_smoke SMOKE=1 [UNINVERT=1] RUN_ANALYZE=1 KS=5
   ```
   A 1-epoch model is too weak to judge polarity; use the prep verdict now and confirm later with
   `"$CRYOET_PYTHON" "$S/scripts/review_classes.py" --polarity <vol_000.mrc> --ref <consensus.mrc> --apix <A>`.
4. **Train, then analyze as a dependent job.** Show the user the commands (`--dry-run`) and submit only after they agree:
   ```bash
   J=$("$S/scripts/submit_tomodrgn.sh" train --gpus 1 --time <HH:MM:SS> --mem <GB>G --log <OUTDIR>.train.%j.out \
        OPTSET=<optset> OUTDIR=<runs/name> ZDIM=<z> EPOCHS=<n> BATCH=<b> [UNINVERT=1] [LAZY=1] [MULTIGPU=1])
   "$S/scripts/submit_tomodrgn.sh" analyze --after "$J" --log <OUTDIR>.analyze.%j.out WORKDIR=<runs/name> EPOCH=latest
   ```
   k values default to `TOMODRGN_KMEANS` (else "50 100"), each in `analyze.<E>_k<k>/`. With `SCHEDULER=none` there
   are no dependencies: add `RUN_ANALYZE=1` to the train call instead.
5. **Review aid** (the aid ranks; the user decides). For each k:
   `"$CRYOET_PYTHON" "$S/scripts/review_classes.py" --analyze <OUTDIR>/analyze.<E>_k<k> --ref <consensus.mrc> --ref-apix <A> --apix <tomoDRGN A/px>`
   -> `classes.tsv` (combined rank of 10-30 A band CC and lp20 CC, detail vs the median class, counts), `summary.txt`
   (bottom quarter, possible blobs), `montage.png`. Show the user the summary, the montage and the per-class particle
   images (`kmeans<k>/` PNGs); suggest viewing candidates in ChimeraX (chimerax-figures).
6. **Apply the choice**:
   `"$CRYOET_PYTHON" "$S/scripts/select_and_map.py" --analyze <..._k<k>> --classes 1-4,7 --tomodrgn-star <OUTDIR>/*_tomodrgn_preprocessed.star --map-to <target STARs> --out-stem <dir>/<name>`
   Report kept count, matched / kept per target, unmatched and many-to-one counts. Many-to-one matches FAIL by default
   (duplicates or a loose `--tol-A`): deduplicate or tighten, use `--on-duplicate warn` only if the user accepts it.
   For Warp per-series STARs without `data_optics`, pass `--coords-angpix`.
7. **Validation, only when the user asks**: refine/reconstruct the kept set AND a size-matched random subset with
   identical poses, mask and protocol (relion-refine, or an M `--iter 0` baseline in m-refine), compared on ONE mask.

## Monitoring

Record job ids. Progress: `grep 'Epoch:' <OUTDIR>/run.log | tail` (one line per epoch: gen loss, KLD, total, time).
Wait with `squeue -j <id>` (Slurm) or the local log, at an interval of a few epochs - not a tight poll. A falling then
flat loss is expected; the loss is not a convergence test (`tomodrgn convergence_vae <OUTDIR> --epoch latest` is).
A failed train exits non-zero, prints the run.log tail, and the dependent analyze never starts. Ask before cancelling
a job the user started.

## General rules (symptom -> check)

- **Premultiplied input** gives hollow-looking backprojections and a poorer model. Check
  `_rlnCtfDataAreCtfPremultiplied` is 0 (prep FAILs otherwise); re-export with `--dont_premultiply`.
- **Data polarity is per dataset, never assumed.** tomoDRGN inverts the data sign by default (`--uninvert-data` turns
  it off). Wrong polarity -> class volumes anti-correlate with the consensus (negative CC in
  `review_classes.py --polarity`). `analyze/eval_vol --invert` only changes the written volumes, not the training.
- **Negative coordinates** -> train_vae refuses the STAR. Drop them before export.
- **Stale per-particle optics columns** -> wrong-sized CTF without any error. prep strips them; do not re-add.
- **Per-group refined Cs** (e.g. after M) leaks into exports and into tomoDRGN's CTF -> reset to nominal, re-export.
- **Bad poses dominate the latent space.** If a large fraction of poses is wrong, tomoDRGN mainly separates pose
  errors. Fix poses (better refinement) before classifying for biology.
- **Review k-means 50 and 100 against the consensus map**; fine k makes small junk classes visible, and a blob class
  can still score high low-pass CC (use the band-pass CC and detail columns).
- **Smaller curated subsets can beat bigger sets.** Judge a selection by a size-matched random control, not by count.
- **Class IDs are not reproducible** across runs or epochs. Never carry class numbers from one run to another.
- **`labels.pkl` follows the training STAR's particle order** (`*_tomodrgn_preprocessed.star`); lengths are asserted.
- **Join on (tomogram, centre in A), never `_rlnTomoParticleName`** (renumbered on every export). Check many-to-one.
- **Permutation nulls** for latent-vs-quality questions must shuffle within tomograms.
- **CUDA OOM** -> lower `BATCH` or `LAZY=1`; host OOM at load -> `--mem` from prep's estimate, or `LAZY=1`.

## References
- `references/pitfalls.md` - error messages, sizing, epoch choice, joining details.
- `references/worked-example-empiar10499.md` - a public worked example (EMPIAR-10499 ribosomes).
