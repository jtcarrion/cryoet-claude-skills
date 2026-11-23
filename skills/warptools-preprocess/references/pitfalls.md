# WarpTools preprocessing pitfalls

Each entry: the rule, the symptom if you get it wrong, and the check. Concrete numbers from one public dataset are in
`worked-example-empiar10499.md`.

## Settings and acquisition
- **`--exposure` sign.** Negative = dose per FRAME; positive = TOTAL dose per movie. A per-frame value given positive
  under-weights the dose by the frame count, silently (no error, slightly worse CTF/dose weighting everywhere).
  Check: `grep Exposure warp_frameseries.settings` shows a negative number equal to the MDOC FrameDosesAndNumber dose.
  The templates negate DOSE_PER_FRAME themselves; `init_project.sh` refuses a negative input.
- **Relative paths in `.settings`** resolve against the settings file's own directory, not the cwd (symptom: zero
  movies found, or paths like `warp/data/data`). Everything absolute.
- **Tilt axis 90 deg off.** Some acquisition software quotes the axis in a frame whose X/Y are swapped relative to the
  saved images. Symptoms: the MDOC `ImageSize` is the image header transposed (`inspect_mdoc.py` WARNs), the IMOD
  weighted-mean residual is tens of nm instead of ~1 nm on every series, and IMOD's align.log says "rotation angle
  seems to be closer to <X>". Fix: `OVERRIDE_AXIS=1 TILT_AXIS=<MDOC axis - 90>` (or IMOD's suggested value). Confirm on
  ONE series (residual drops to ~1 nm) before the batch; never trust the MDOC axis blindly when the sizes disagree.
- **Archive metadata can be wrong** (pixel type, image size, even pixel size). The image header is authoritative;
  confirm pixel size with the user / deposition paper.
- **Gain orientation.** The gain must match the movies' header dims and orientation (`--gain_flip_x/_y`,
  `--gain_transpose`). Symptom of a wrong flip: a fixed-pattern grid / stripes in the averages and poor CTF fits.
  Check: average one movie each way, or compare a gain-corrected average for residual detector pattern.
- **SubFramePath extension not on disk** (e.g. `.eer` in the MDOC, `.mrc` files) -> every tilt "file not found", the
  worker blacklisted, alignment spinning forever. Rewrite COPIES of the MDOCs.
- **Dose order** comes from MDOC DateTime x `--tilt_exposure` (per tilt), not ExposureDose. DateTime must exist; check
  that the tomostar dose column follows the acquisition scheme (e.g. dose-symmetric).
- **Pre-tilt** (lamellae): `--tilt_offset`. Imported .tlt values overwrite tomostar angles, so they must share the
  same sign and offset.
- **`--dont_invert` means two different things**: ts_import = tilt-angle sign; ts_reconstruct = contrast.
- **ts_import convention: keep Warp's default** (`TS_IMPORT_DONT_INVERT=0`). `ts_import --dont_invert` mirrors the
  geometry relative to standard Warp/IMOD processing of the same data. Symptom: the hand check says 'flip' (negative
  correlation) where a default import says 'no flip', and external coordinates registered to standard Warp tomograms
  fit the volume only mirrored. Use `1` only to match an existing project imported that way; check
  `stages.warptools-preprocess.ts_import_dont_invert` in the project record.
- **Counting-reference exposures** (a file with no MDOC entry) are ignored by ts_import - harmless.
- **Motion grid** temporal nodes = frames per movie (`NFRAMES`), or the EER group count for EER. There is no safe
  default; `init_project.sh` requires it.

## Alignment
- **Gold present -> fiducials.** If the tilts show gold beads, `ts_etomo_fiducials` with the MEASURED bead diameter is
  the reference alignment; patch tracking and AreTomo3 become comparison arms. Check bead visibility on a 0-deg
  average; residuals should be ~1 nm or below.
- `ts_etomo_patches` has no `--patch_x/--patch_y` in current builds (older examples used them) - check `--help`.
- IMOD residuals compare only WITHIN a method: patch tracking and bead tracking fit different numbers of points and
  variables, so residuals can differ several-fold for reasons unrelated to quality.
- Large per-tilt shifts can be real stage jumps; confirm with a second alignment method before discarding a tilt.
- Failed series (no .xf in tiltstack/) - exclude them before CTF. A series with a huge prealignment offset can crash
  ts_ctf; rerun the others with `--series`.
- AreTomo3: occasional segfaults succeed on retry; intermediate stacks are tens of GB per run, so the templates pass
  `--delete_intermediate` (ARETOMO_DELETE_INTERMEDIATE=1). Flag Global_Shift > ~200 px.

## Importing alignments (`ts_import_alignments`)
- Layout `DIR/<series>/<series>.xf` + `.tlt`, Warp series names (the tomostar stem).
- `--alignment_angpix` = pixel size the .xf SHIFTS were computed at, verified against the source stack - not the raw
  pixel size, and not necessarily the binning of the stack the user mentions. Wrong = every shift silently mis-scaled.
  Check: reconstruct one series and look for doubled/smeared features, or round-trip a known .xf.
- `.xf` rows are positional. A file written in ascending tilt order applied to a descending stack is row-reversed:
  it looks like a catastrophically bad alignment. Check the first/last .tlt angles against the stack order.
- Fewer .xf lines than tilts = dropped tilts: supply cutviews; deposited .xf may be in acquisition order, not angle
  order; .tlt may be missing (generate from the MDOC). `04_ts_align.sbatch` prints the row counts per series.
- Importing resets tilt use; select tilts by MOVIE NAME, never by line index.
- Single-series reruns rewrite `processed_items.json` wholesale; `run_warp` keeps a dated `.bak_<job>` copy.
- `ts_ctf` is mandatory afterwards; poses and image-warp grids from a previous alignment do NOT transfer to a new one
  (re-refine, do not reuse).

## Hand
- **Order:** alignment -> `ts_defocus_hand --check` -> (user decides) -> set the hand -> `ts_ctf`. The CTF fit uses the
  hand; fitting first and flipping later means refitting. The templates enforce this (hand_status.txt).
- `ts_defocus_hand --check` / `ts_ctf --auto_hand N` test the defocus GRADIENT under the ts_import angle convention.
  They follow the convention: the same series imported with and without `ts_import --dont_invert` gives opposite
  verdicts, as it should. Record which convention a project used and never mix tomostars imported both ways.
- **'flip' on a fresh import:** before flipping, ask whether coordinates/maps from elsewhere must match a standard Warp
  frame. If they must and the import used `--dont_invert`, re-import with the default and re-check instead of flipping.
- **Defocus hand != map hand.** A dataset can pass the check ('no flip') and still yield a map mirrored relative to the
  deposited structure. Validate the map hand downstream: dock an atomic model (or compare to a reference map) as-is
  and mirrored under the particle mask; the correct hand fits clearly better. If the whole dataset comes out mirrored,
  flip the final maps (or the reference) consistently - do not change the tilt-series hand after the fact.
- `--auto_hand` / `--set_auto` with one series returns rc 0 but is a weak call: provisional until the full run.

## Variants / processing folders
- Inherited M products ride along when an arm is seeded from a folder M ever wrote into: image warp (GridMovement),
  stage angles (GridAngle), volume warp (GridVolumeWarp) and MagnificationCorrection. A fresh alignment arm has none,
  so arms compared against each other must strip or keep them identically. `qc_summary.py` reports them.
- `--output_processing` replaces the folder wholesale and is not sticky; seed variants with the baseline XMLs; carry
  the same variant through hand, CTF, reconstruct and export (or they silently use baseline geometry).
- An inverted reconstruction into the baseline folder overwrites the viewing tomograms: own variant.
- MCore writes refined Cs/Zernikes/warp grids back into its source processing folder. Give each M population a private
  copy; write-protect masters (`chmod a-w`). Symptom: `qc_summary.py` warns "Cs != nominal".
- Frame-split half-tomogram FSC (`--halfmap_frames`) is blind to alignment shift error (both halves share the
  alignment). Use `--halfmap_tilts` and downstream STA resolution to rank alignments.

## Running jobs
- Partition / account / GPU request come from the cryoet-skills config via `cryoet_submit`; never typed into scripts.
  Some sites need a typed gres or `--gpus`: set `SLURM_GPU_GRES_FMT` in the config, not in the templates.
- CPU-only steps (01, 03) are seconds; if your site forbids work on login nodes, submit them with
  `cryoet_submit cpu 0 00:30:00 <script>`.
- `--input_data` lists on shared storage, never node-local /tmp. Job-unique `--task_dir` (a stale manager holds the
  default lock: "Another manager is already using queue dir"). IMOD must be activated explicitly in batch jobs
  (non-login shell) - `cryoet_activate warp` does it when `IMOD_DIR` is set. Warp steps resume after preemption.
- A comment line inside a backslash-continued command silently truncates it.
- `CUFFT_ALLOC_FAILED` = GPU out of memory (another job on the same GPU, or too many `--perdevice` workers).
- Memory: the #SBATCH defaults (200-300 G) suit ~4k detectors and 10 A tomograms; lower with `submit_chain.sh --mem`
  where nodes are smaller. Rough scale for ~90 series of 4k images on 4 GPUs: fs_ctf minutes, patch alignment
  minutes, AreTomo3 hours, ts_ctf ~10 min, ts_reconstruct at 10 A with deconv ~15 min.
