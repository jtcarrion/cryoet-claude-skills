# Lessons behind the rules

Each item: the rule, what you see when it is broken, and how to check. Numbers are illustrative; dataset-specific
detail is in `worked-example-empiar10499.md`.

## Export
- **Coordinate units.** M species coordinates are Angstrom (`--coords_angpix 1`); RELION/tomoDRGN STARs are in
  their own pixel size; tomogram picks in the tomogram's pixel size. A wrong value shifts or scales every particle.
  Check: max coordinate x coords_angpix should match the tomogram extent in A. In the OUTPUT STAR coordinates are in
  export pixels (`_rlnImagePixelSize`): Angstrom = coord x export pixel. Using the tilt-series pixel silently turns a
  "20 A" duplicate audit into a ~30 A one.
- **Premultiplication.** RELION wants premultiplied series (default; `_rlnCtfDataAreCtfPremultiplied 1`). tomoDRGN
  wants `--dont_premultiply` (flag 0) - that is the tomodrgn-run skill.
- **Empty optimisation set.** Some WarpTools 2.x builds write `_rlnTomoParticlesFile` empty and image paths relative
  to `metadata/`, while RELION resolves them against its cwd. Symptom: RELION cannot find particles or images. Always
  write your own optimisation set with absolute paths (`make_optset.py`); leave Warp's as-is.
- **Same pixel size, different set = clobber.** Stack names embed the pixel size and an index; a second export at
  the same pixel size into the same `particleseries/` overwrites by index and corrupts the older STAR without any
  error. Use `--output_processing` (`OUTPROC`).
- **Queue-dir lock.** An earlier export's manager can stay resident and keep the default `tasks/` lock ("Another
  manager is already using queue dir"): use a job-unique `--task_dir` (the script does).
- **GPU OOM in disguise.** Exporting inside another GPU job's allocation fails with cuFFT `CUFFT_ALLOC_FAILED`.
- **Contaminated geometry.** M/MCore runs on another species leave refined Cs and odd Zernikes in the XMLs. Symptom:
  `make_optset.py` warns that Cs varies between optics groups or differs from nominal. Export from an isolated copy
  with Cs reset and odd Zernikes zeroed (`scripts/_lib/reset_ctf_cs.py`); keep defocus, warp and alignment.
- **Stale per-particle optics columns** ride along from older exports (e.g. `_rlnImageSize 100` on a box-192 set).
  RELION ignores them; tomoDRGN reads the particle copy first. `make_optset.py` warns.
- **Deselected tilts count as missing.** With a reduced tilt set, `--max_missing_tilts` must allow for the
  deselected tilts too, or whole series vanish from the export. Set it from the number of disabled tilts per series.
- **`--max_missing_tilts` drops edge particles** when the geometry changes (e.g. after an alignment swap a few
  dozen out of tens of thousands): real, not a bug - report the count.
- `--input_data` lists must be on shared storage; a compute node cannot see the login node's /tmp.

## Layout and resources
- 1 leader + 1 follower per GPU, odd total (gold-standard splits followers between halves). Many followers with few
  threads each (e.g. 12 ranks x 4 threads) was much slower despite 100% GPU utilisation.
- A node that aborts a rank twice (CUDA error 700, "Aborted") can then deadlock MPI and hold the GPUs for hours.
  Exclude that node; the same job usually finishes on 2 GPUs / 3 ranks elsewhere.
- VRAM: a box ~200 particle-series refine can fill an 80 GB GPU. Check `nvidia-smi` memory early in iteration 1
  before choosing finer sampling or larger `--pool`.
- Preread RAM ~= one float copy x (workers + 2) + working set (measure per-process RSS; `sstat` counts page cache).
  Scratch staging runs at the node disk's speed (~10 min per 100 GB on local NVMe/xfs) regardless of MPI layout. A
  network scratch mount, or a small /tmp, is worse than reading in place.
- Watch GPU power, not utilisation: low power at 0% = staging or stalled; high power at 100% = real compute.
- `--mem=0` means "the site default" on many Slurm setups, which may be far below the node's RAM: always explicit.

## Reference, sampling, mask
- **Greyscale.** An EMDB map can be orders of magnitude too faint relative to the particles. Symptoms: flat
  posteriors (median significant samples in the thousands, MaxValueProb ~0), iteration-0 SSNR orders of magnitude
  low, "Estimated accuracy angles" of ~30 deg at iteration 1 (healthy: a few deg), an ETA of days for iteration 1.
  `--firstiter_cc` fixes it; `--scale` alone cannot (group scales only update after iteration 1). It is NOT caused by
  scratch/preread, mpirun/srun, particle count or box size - do not tune those first.
- **`--firstiter_cc` hides a bad reference in iteration 1.** CC mode makes hard assignments: every particle shows 1
  significant sample and MaxValueProb 1.0 whatever the reference, even a wrong-frame map. Diagnose greyscale and
  hand WITHOUT the flag (bench_iter1 arms); a healthy own-data reference gives single-digit median samples and
  MaxValueProb ~0.3.
- **Hand.** Seeding with the wrong-hand map converges to the wrong hand and stalls far worse than the data allow
  (several-fold worse resolution). The defocus-hand check of the tilt series does not test the reference. Check
  BEFORE the first full refinement (SKILL.md step 5): bench both hands without `--firstiter_cc`; if both are flat
  (greyscale), iteration 1 cannot separate them - bench both WITH `--firstiter_cc --scale` for 3 iterations and compare
  resolution/posteriors, or correlate a reference-free map (`--skip_align` from independent poses, or de novo) with
  both hands. Record the choice in the project's decisions. For a final map, fit map and Z-flip against the public map.
- **A consensus map from the same particles is not an independent reference.** It shares their noise and poses, so
  agreement with it is only meaningful up to its own (FSC) resolution; use a map from other particles or a model.
- **Sampling.** `--healpix_order 2` (15 deg) global start; `--auto_local_healpix_order 3` for coarse/quick runs.
  Keeping a finer stage global multiplies cost ~8x per halving of the step - watch the log's OrientationalSampling.
  Offsets are in EXPORT pixels.
- **`--solvent_correct_fsc`.** A solvent mask alone does not drive sampling: without the flag RELION refines against
  the unmasked FSC (often half the masked resolution). It is honoured on `--continue` (switch-on only).
  `refine_status.py` notes it when the optimiser has a mask but the flag is off.
- **Mask size by VOLUME.** A sphere "slightly larger than the subunit" can enclose 4x the molecule; the refine then
  runs for days without converging, angle changes oscillating (healthy runs collapse to ~1-2 deg).
- **Mask resampling.** Fourier rescaling rings (values slightly < 0 and > 1) make `relion_postprocess` abort, while
  the header min/max still look fine. Clamp from the array (`prep_reference.py` does).
- **Pixel size.** RELION writes rounded pixel sizes into half-map headers (e.g. 2.2526 for 2.25): take `--angpix`
  from the optics table.
- `--norm` is a silent no-op for particle series (`_rlnDoCorrectNorm 0`); only `--scale` is live.

## Initial models
- `relion_refine` single process (NOT `_mpi`: it stalls at the end of iteration 1 on the MPI barrier) with `--grad
  --denovo_3dref --iter 100 --auto_sampling --oversampling 1 --pad 1 --pool 10 --tau2_fudge 4 --healpix_order 1`; no
  `--norm`/`--scale`.

## Measuring and comparing
- **fscrand_hi** = max |phase-randomised masked FSC| finer than 12 A must be <= 0.05. Tightening a mask always raises
  it; an eroded mask can report a resolution 1-2 A better than the truth at fscrand_hi ~0.5. Dilate until every arm
  passes, then compare all arms on ONE mask.
- **Never compare a RELION FSC to M's own FSC**: M grows the mask (~1.5x GlobalRes) before its FSC; on identical
  poses that alone moves the number by ~1 A. Re-measure M half-maps on the RELION mask with
  `postprocess.sbatch HALF1=.. HALF2=..`.
- **Rescale a mask by pixel size before padding** it into a bigger box; padding alone shrinks it in Angstrom and
  gives a fake high resolution (with fscrand_hi far above 0.05).
- **Cross-half duplicates** (re-picks within ~20 A in opposite halves) correlate the half-maps directly; a few
  hundred pairs in tens of thousands can make a ~7 A map read ~5 A. fscrand_hi cannot see it; the FSC plateaus at
  0.10-0.14 toward Nyquist instead of decaying. Audit before every refinement; it cannot be undone after.
- **The scheduler's exit code is not the verdict**: RELION often aborts in MPI teardown AFTER
  `RELION_JOB_EXIT_SUCCESS` (exit 134/139; it has hung for a day). The marker plus complete outputs is the truth.
- **Selection by `_rlnMaxValueProbDistribution`**: rank within each half against that half's own reference so halves
  stay independent; re-refine the subset with a full search.
- `relion_tomo_reconstruct_particle` cannot reconstruct WarpTools particle series (all-zero maps from the dummy tilt
  series); `relion_reconstruct` cannot either. Only `relion_refine` and MCore can.

## Shell traps in job scripts
- `x=$(ls glob | wc -l)` under `set -eo pipefail` kills the job on an empty directory: use `find`.
- `grep` that legitimately matches nothing under `pipefail` exits 1: wrap as `{ grep ... || true; }`.
- `set -u` breaks `conda activate` and many env scripts: `export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"` first.
- `while pgrep -f 'foo.py'` matches its own shell forever: `pgrep -f '[f]oo\.py'`.
- Relative STAR paths resolve against the job's cwd: submit with `--chdir`, or use the `_abspath` files.
- `srun` inside a batch job (Slurm >= 22.05) does not inherit `--cpus-per-task`: export `SRUN_CPUS_PER_TASK`
  (refine3d.sbatch does). `srun -n N` with N above the allocation's `--ntasks` is refused.
