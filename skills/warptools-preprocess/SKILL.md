---
name: warptools-preprocess
description: Set up a WarpTools 2.0 processing directory for a cryo-ET dataset and run the tilt-series preprocessing chain on a Slurm cluster or a workstation - create_settings, fs_motion_and_ctf / fs_ctf, ts_import, alignment (ts_etomo_patches, ts_etomo_fiducials, ts_aretomo3 or ts_import_alignments), ts_defocus_hand --check (and the hand fix if needed) before ts_ctf, and ts_reconstruct - including several alignment pipelines side by side with --input_processing / --output_processing variants, job submission and monitoring, and per-step QC. Use this whenever the user wants to start processing a new tilt-series dataset or EMPIAR download with Warp, re-align or import an external alignment (IMOD .xf, AreTomo), check or fix defocus handedness, re-run CTF or reconstruct tomograms, compare alignment arms, or asks about any WarpTools preprocessing flag, including on a new machine where WarpTools/IMOD are not installed or configured yet (the setup check says what to install and stops) - even if they just say "set up warp for this data" or "reconstruct the tomograms".
---

# WarpTools tilt-series preprocessing

Turns raw movies (or per-tilt images) + MDOCs into aligned, CTF-corrected, hand-checked tilt series and tomograms in a
WarpTools processing folder that particle export (relion-refine), M (m-refine) and TeamTomo (teamtomo-preprocess) can
read. The skill ships project TEMPLATES and three tools; `scripts/init_project.sh` copies the templates into
`<PROJECT>/scripts/` with the dataset's values filled in, plus a copy of the shared config library (`scripts/_lib/`)
and `qc_summary.py`. From then on the project owns its scripts (edit `warp_params.sh`, never the skill).
Flags were checked against WarpTools 2.0 `--help`; the website can lag the build - when in doubt run
`WarpTools <verb> --help` after activation.

Read `references/pitfalls.md` before any non-routine step (imports, variants, hand, dose, axis).
`references/worked-example-empiar10499.md` shows every trap on one public dataset.

## 1. Setup check

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").


```
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh" || echo "no config: run the cryoet-workflow skill's setup"
cryoet_have warp     || echo "WarpTools not configured (WARP_ENV_SCRIPT) - stop and ask"
cryoet_have imod     || echo "no IMOD (IMOD_DIR): ts_etomo_patches / ts_etomo_fiducials unavailable"
cryoet_have aretomo3 || echo "no AreTomo3 (ARETOMO3_BIN): ts_aretomo3 unavailable"
echo "scheduler=$SCHEDULER gpu_partition=${SLURM_GPU_PARTITION:-<cluster default>} python=${CRYOET_PYTHON:-python3}"
```
- No config -> do not guess site values; send the user to the cryoet-workflow skill's setup.
- No WarpTools -> stop: say what is missing (key `WARP_ENV_SCRIPT`, or WarpTools on PATH) and do nothing else.
- No IMOD and no AreTomo3 -> only `--method import` (an external alignment) is possible; say so.
- `SITE_NOTES_FILE` set -> read it first (maintenance windows, login-node rules).
- Verify the install once: `cryoet_activate warp && WarpTools --version`.

## 2. Inputs / Outputs (handoff)

| artifact | path pattern | produced / consumed | by |
|---|---|---|---|
| movies or per-tilt images | `$RAW_FRAMES/*.{tif,eer,mrc}` | consumed | user / EMPIAR download |
| MDOCs (+ gain) | `$MDOC_DIR/*.mdoc`, `$GAIN_PATH` | consumed | user |
| external alignment (optional) | `DIR/<series>/<series>.{xf,tlt}` | consumed by `--method import` | IMOD/etomo, AreTomo, JOLT (optional) |
| project params | `$PROJ/scripts/warp_params.sh` | produced | this skill (`init_project.sh`) |
| settings | `$PROJ/warp/warp_{frameseries,tiltseries}.settings` | produced; consumed by all Warp steps | this skill, relion-refine, m-refine |
| frame series | `$PROJ/warp/warp_frameseries/` (XMLs, `average/*.mrc`, halves) | produced | this skill (step 2) |
| tomostars | `$PROJ/warp/tomostar/*.tomostar` | produced; consumed by export | this skill (step 3), relion-refine |
| baseline processing folder | `$PROJ/warp/warp_tiltseries/` (`<series>.xml`, `tiltstack/`, `reconstruction/`, `hand_status.txt`) | produced | this skill; consumed by relion-refine, m-refine (private copy), teamtomo-preprocess |
| variant processing folders | `$PROJ/<variant>/` (same layout) | produced | this skill (`--variant`); consumed with the SAME `--variant` downstream |
| tomograms | `<proc>/reconstruction/<series>_<RECON_ANGPIX>Apx.mrc` (+ deconv, halves) | produced | this skill; consumed by pickers, teamtomo-preprocess comparisons |
| Warp project root for TeamTomo | `$PROJ/warp` (`warp_tiltseries/`, `warp_frameseries/`, `tomostar/`, settings side by side) | consumed | teamtomo-preprocess |

The scripts write the hand-off record `$PROJ/cryoet_project.json` themselves (via `scripts/_lib/project_state.py`):
init sets `acquisition.*`, `stages.warptools-preprocess.{warp_project,default_arm,status,ts_import_dont_invert}`;
step 4 adds to `.arms`, step 5 (set modes) adds to `decisions`, step 7 sets `.tomograms.<arm>`.
Also tell the director/downstream: `PROJ`, the baseline folder, every variant name and what it holds, the ts_import
angle convention (`TS_IMPORT_DONT_INVERT`), the hand decision (`hand_status.txt`), `ANGPIX`, `RECON_ANGPIX`.

## 3. Inspect, then ask

Run `"${CRYOET_PYTHON:-python3}" "${CLAUDE_SKILL_DIR}/scripts/_lib/inspect_mdoc.py" --mdocs <dir> --frames <dir>` first.
It proposes pixel size, dose per tilt and per frame, frames per movie (NFRAMES), tilt count/range, axis, image size,
defocus range, and WARNs on the traps (transposed MDOC ImageSize = axis 90 deg off; SubFramePath extension not on
disk; missing DateTime; files with no MDOC entry). Confirm every acquisition value with the user (never guess pixel
size, dose, voltage or Cs; Cs may come from config `MICROSCOPE_CS_MM`). Then ask, with a recommendation each (these
are baked into outputs and cost GPU-hours to change):

| # | question | default / recommendation |
|---|---|---|
| 1 | GPUs per job | 2 (partition/account come from the config; respect `SLURM_MAX_GPUS_PER_JOB`) |
| 2 | Alignment method | `fiducials` if gold is visible (measure the bead size), else `patches` (800 A); `aretomo3`; `import` an external .xf |
| 3 | Tilt axis: MDOC value or override? | MDOC, unless inspect_mdoc warns (transposed size) or IMOD says "rotation angle seems to be closer to ..." |
| 4 | Tilts to drop | `--min_intensity 0.3` (grid bars), `--min_fov 0.3` |
| 5 | Tomogram thickness (TOMO_DIM Z, unbinned px) and recon pixel | generous Z; 10 A/px |
| 6 | ts_import angle convention | `TS_IMPORT_DONT_INVERT=0` (Warp default, standard frame); `1` (--dont_invert) only to match an existing project imported that way; never mix |
| 7 | Contrast: view (--dont_invert) or template matching (inverted)? | --dont_invert; inverted runs get their own variant |
| 8 | Where to write | baseline `warp/warp_tiltseries`; every alternative as `--variant NAME` at the project root |
| 9 | Defocus hand (after step 5's check) | follow the check, but confirm with the user before setting it |

## 4. Set up

```
bash "${CLAUDE_SKILL_DIR}/scripts/init_project.sh" --proj /abs/PROJECT RAW_FRAMES=... FRAME_EXT="*.tif" MDOC_DIR=... \
  HAVE_FRAMES=1 NFRAMES=<frames per movie> ANGPIX=... VOLTAGE=... CS=... DOSE_PER_FRAME=<positive> DOSE_PER_TILT=... \
  TILT_AXIS=... TOMO_DIM=XxYxZ [OVERRIDE_AXIS=1] [GAIN_PATH=... GAIN_FLAGS=--gain_flip_y] [EER_FLAGS="--eer_ngroups N"] \
  [ALIGN_METHOD=fiducials FIDUCIAL_NM=10] [TS_IMPORT_DONT_INVERT=0|1]
```
It refuses missing acquisition values, a missing NFRAMES with frames (EER: taken from `--eer_ngroups`, Warp default
40), unknown keys, a negative DOSE_PER_FRAME (it negates it itself), relative paths, and overwriting an existing
project. Projects under `$HOME` are refused on Slurm sites (quota; `ALLOW_HOME=1` for tiny tests): suggest
`DEFAULT_PROJECT_ROOT` from the config. Pre-split stacks with no frames: split one MRC per tilt named after the MDOC
SubFramePath stem, `HAVE_FRAMES=0`, and symlink the tilts into `warp/warp_frameseries/average/` after step 2.

## 5. Run

`$PROJ/scripts/...` below; `cryoet_submit` comes from `source $PROJ/scripts/_lib/cryoet_config.sh`.

| step | command | where | check before moving on |
|---|---|---|---|
| 1 settings | `bash scripts/01_create_settings.sh` | CPU, seconds | absolute DataFolder/ProcessingFolder; Exposure negative = dose per frame; gain flip vs header |
| 2 frames | `CRYOET_SBATCH_OPTS="-o logs/02_%j.out -e logs/02_%j.err" cryoet_submit gpu 2 "" scripts/02_fs_motion_and_ctf.sbatch` | GPU | XML count = tilt count; averages exist; rc=0 in the log |
| 3 import | `bash scripts/03_ts_import.sh` | CPU, seconds | tomostar count = series; tilts per series vs MDOCs; dose order follows DateTime |
| 4-5 | `scripts/submit_chain.sh` (align -> hand CHECK, then stops) | GPU | residuals and axis warnings (04 log), series with no .xf, the hand check line |
| 5 fix | `scripts/submit_chain.sh --from 5 --to 7 --hand auto` (or `--from 6` if 'no flip' already) | GPU | AreAnglesInverted consistent |
| 6-7 | (continues from the line above) | GPU | `qc_summary.py`; look at 2-3 tomograms; polarity as intended |

- Steps 1 and 3 are seconds of CPU. If the site forbids login-node work, `cryoet_submit cpu 0 00:30:00 scripts/01_...`.
- `SCHEDULER=none`: `submit_chain.sh` runs the steps one after another in the foreground; run 02 as
  `WARP_NGPU=<n> bash scripts/02_fs_motion_and_ctf.sbatch > logs/02.out 2>&1`.
- Smoke test first on a new dataset: `scripts/submit_chain.sh --to 7 --hand auto --series <ONE> --variant smoketest`
  (~10-20 min). A one-series hand call is weak: provisional; the full run decides.
- QC: `"${CRYOET_PYTHON:-python3}" scripts/qc_summary.py <processing folder> --cs <CS> [--compare <other folder>]` -
  per-series tilts, CTF resolution, defocus, Cs, hand, .xf, IMOD residual, tomogram; `--compare` proves a variant
  really changed geometry. Optional series filter: `WarpTools filter_quality --settings ... --histograms` (read-only).
- `submit_chain.sh --dry-run` prints every submission line; show it to the user before submitting.

## 6. Defocus hand (strict order: check BEFORE ts_ctf)

1. Step 5 `--hand check` (default in the chain) reports "Average correlation: X" - positive = 'no flip', negative = flip.
   It writes `hand_status.txt` in the processing folder.
2. Show the user the number and the AreAnglesInverted counts, recommend, and only then set it (`--hand auto` determines
   and sets for all series; `flip` / `noflip` force).
3. Only then ts_ctf. `06_ts_ctf.sbatch` refuses a folder with no `hand_status.txt`, or whose last check said 'flip'
   while its XMLs are unflipped (override: `--skip-hand-check`, or `AUTO_HAND=N` for `ts_ctf --auto_hand`).
If the check says 'flip' on a fresh import, first ask whether coordinates or maps from elsewhere (published picks,
another Warp project, a template) must match a standard Warp frame. If so, and the import used `--dont_invert`, re-import
with the default (`TS_IMPORT_DONT_INVERT=0`) and re-check rather than flipping: a flip fixes the CTF gradient but leaves
the volume mirrored relative to standard Warp tomograms.
The check tests the defocus GRADIENT under the chosen ts_import convention, not the absolute hand of the final map: a
dataset can pass 'no flip' and still give a map mirrored vs the deposited structure. Say so, and check the map hand
downstream against an atomic model/reference (relion-refine). A whole-dataset mirror is fixed on the final maps, not by
re-flipping the tilt series.

## 7. Several pipelines side by side

Every alternative alignment is a `--variant NAME` folder at the project root, seeded from the baseline XMLs (keeps CTF;
only geometry is rewritten). `--output_processing` is not sticky, so 05/06/07 (and the export) must carry the SAME
`--variant` - `submit_chain.sh` passes it to every step, and 05-07 refuse a variant folder that step 4 never wrote. Each
variant gets its own hand check. Use `--series` when only some series changed. After any import or new alignment
ts_ctf is mandatory. Rank alignments by downstream STA resolution (relion-refine), not by frame-split tomogram FSC
(blind to shift error) and not by IMOD residuals across methods (different point counts / fit variables).
For M: give each population a PRIVATE copy of the processing folder (MCore writes refined Cs/Zernikes/warp back into
whatever folder its source points at). Never point a job at a write-protected master or another user's folder.

### Importing an external alignment
`scripts/submit_chain.sh --method import --alignments DIR --alignment-angpix A --variant NAME` with
`DIR/<series>/<series>.xf + .tlt`. `A` = the pixel size the .xf shifts were computed at (ask; verify by round-trip).
Step 4 prints .xf/.tlt/tomostar row counts per series; mismatches mean dropped tilts (cutviews) or the wrong file.
<!-- TODO(jolt-preprint) -->
JOLT alignments (optional, unreleased): only if `cryoet_have jolt`; otherwise say JOLT is not enabled and skip. JOLT
writes per-series `.xf`/`.tlt` in the layout above; import them exactly like IMOD's, then check the row ORDER (first/last
.tlt angle vs the stack order) before trusting residuals.

## 8. Submitting and monitoring

Show the user the exact submission lines (`--dry-run`), then submit. Record job ids and log paths. Watch with a
background wait on `squeue -h -j <ids>` (interval matched to the step: minutes for 01-03 and the hand check, 10-30 min
for alignment/CTF/reconstruct), then read the step's own check block at the end of its log and run `qc_summary.py`.
Pending with "ReqNodeNotAvail, Reserved for maintenance" = the time limit runs into a maintenance window: lower it
(`scontrol update JobId=<id> TimeLimit=03:50:00` on pending jobs, or `submit_chain.sh --time`). A failed step: read
`logs/<step>_<id>.err` and `<processing>/logs/`; resubmitting resumes (Warp steps skip finished items). Every step exits
with WarpTools' own rc, so an `afterok` chain stops at the failure. Ask before cancelling a job the user started.
"Another manager is already using queue dir" = a stale manager: the templates use job-unique `--task_dir`.
`CUFFT_ALLOC_FAILED` = GPU out of memory (shared GPU or too many workers).

## 9. General rules

- Acquisition values come from the data and the user, never from memory; the image header beats the MDOC.
- `--exposure` is negative (per frame). `--tilt_exposure` is per tilt.
- A transposed MDOC ImageSize, a residual many times ~1 nm on every series, or IMOD's "rotation angle seems to be
  closer to" => the axis is wrong (typically 90 deg); fix with `OVERRIDE_AXIS=1` and confirm on one series.
- Gold visible => fiducial alignment is the reference arm.
- Gain orientation must match the movie header; verify on one average.
- Hand: check -> decide -> set -> ts_ctf; defocus hand is not map hand.
- One variant name end to end; ts_ctf after every new geometry; private folders for M.

## 10. References

- `references/pitfalls.md` - every rule with symptom and check.
- `references/worked-example-empiar10499.md` - the values and traps on one public dataset.
