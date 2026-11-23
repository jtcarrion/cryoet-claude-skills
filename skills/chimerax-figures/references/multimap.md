# Comparing several maps side by side (case C)

## Make the maps comparable before showing them
Finished maps from different programs are filtered differently (RELION postprocess keeps grain near the resolution
limit; M runs its built-in denoiser when `ApplyDenoising = True` in the `.species` file; deposited maps may be sharpened,
denoised or both). Side by side, that reads as a quality difference that is really processing. Symptom: one map looks
much "cleaner" at the same resolution. Check: compare the share of power in a band near the resolution limit (e.g.
4.5-6 Å vs 30-4 Å) between the maps - large differences mean different filtering.

So for any comparison figure: start from each map's raw half-maps and denoise all of them with identical settings.
Noise2Map (ships with Warp) is optional: `cryoet_have noise2map` (key `NOISE2MAP_BIN`, or Warp configured). If it is not
available, say so and either compare the maps with one common filter (same B-factor/low-pass for all) or label the
processing difference plainly in the figure.
```
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"
mkdir -p n2m/mapA && ln -s /path/to/half1.mrc /path/to/half2.mrc /path/to/mask.mrc n2m/mapA/
cryoet_submit gpu 1 01:00:00 "${CLAUDE_SKILL_DIR}/scripts/noise2map.sbatch" n2m/mapA half1.mrc half2.mrc mask.mrc <apix> <FSC0.143 A>
```
- One run folder per map; output `denoised/half1.mrc` (float16) inside it. Ask before submitting (GPU job).
- Same `--iterations/--window/--batchsize/--overflatten_factor` for every map; only `--angpix` and `--lowpass` (the map's
  own FSC 0.143) differ. Training worked if `log(loss)` falls in the log.
- Re-denoise downloaded maps from their deposited half-maps instead of reusing a depositor's denoised map.
- Label figures "Noise2Map-denoised"; FSC and local-resolution numbers come from the ORIGINAL maps.
- Header pixel size can differ slightly from the nominal one (some RELION half-maps say 2.2526 for 2.25 Å): use the
  nominal value for masks, docking and local resolution, and state both.

## Same contour rule for every map
`calc_level.py --match-volume ref.mrc other.mrc ...`: the CNN level on the reference map (or `--ref-level L` without the
CNN) defines an enclosed volume; every other map gets the level enclosing the same volume on its own grid. With a known
mass, `--mw KDA` gives every map the same volume directly. Per-map CNN levels are NOT one rule: two maps of the same
complex can get enclosed volumes ~15% apart. If you change one map's level later, change all of them by the same rule.

## Layout without `tile`
Put every offset into `view matrix models #N,...` (12 numbers, row-major `[R | t]`). Same-frame maps: pure x shift,
x_step ~ box x pixel + a margin (compute it per figure: `"layout": {"x_step": ...}`). Nested local-resolution children
follow automatically. One `view matrix` line per model.

## Opposite hand or different frame: flip + exact placement, never resample
Trilinear resampling low-passes the map (visibly softer fine detail). Instead:
1. **Decide the hand against an atomic model** (references/model_ligand.md), not by map-vs-map correlation (margins ~1%).
2. **Get a rigid-body transform** between the maps. No docking tool is shipped; any of these works:
   - your own exhaustive rotation search + local refinement (low-pass both maps to ~10-12 Å, search both hands);
   - ChimeraX locally: `volume flip #2` (exact plane reversal, axis z), then `fitmap #3 inMap #1 search 50
     resolution 10` and `view matrix` to read the placement - in this route ChimeraX does the placement itself, so
     write that matrix into the spec and skip step 3's docking input;
   - a transform deposited with the maps or produced by another program, converted to the format below.
   `place_matrix.py` expects JSON `{"A": 3x3, "b_A": [3]}` with `x_ref = A . x_mov + b`, physical Å, coordinates
   centred on each box (centre = n x pixel / 2), numpy (z, y, x) order; `det(A) = -1` when the hands differ.
3. `"$CRYOET_PYTHON" scripts/place_matrix.py --ref ref.mrc --mov mov.mrc --dock dock.json --ref-mask ref_mask.mrc
   --also mov_locres.mrc mov_mask.mrc --shift-x <x_step> --outdir bundle/maps` - flips by array reversal along **z**
   (numpy axis 0), converts to a proper ChimeraX rotation, and writes nothing unless det = +1, orthonormal, and the
   correlation through exactly that matrix beats its controls: both maps low-passed to one common resolution (default
   the coarser map's, from `--ref-res/--mov-res`), cc must exceed every +-(lowpass/2) shifted copy by >= 0.05 and the
   same matrix without the flip by >= 0.10 (`--min-margin-shift/--min-margin-hand`; floor `--min-cc` 0.30). An
   absolute threshold does not work: a correctly placed mirrored EMDB map vs a 7 A in-cell map gave 0.76 at full
   resolution and 0.82 at an 8 A common low-pass, against 0.65-0.67 for one-voxel shifts and 0.16 unmirrored.
   The other-hand control only checks that flip and matrix belong together; it does not decide the hand.
   `--force` writes despite a failed correlation gate (never a failed geometry gate) - say so in the README.
   Memory ~40 x box^3 bytes: not on a shared login node for big boxes.
4. Paste the printed `view matrix models #N,...` numbers into the spec's `"matrix"`.
All bundled maps need origin 0 for this matrix (`scripts/set_origin.py`).

## What went wrong before (do not repeat)
1. A sharpened map vs a denoised map that had also been trilinear-resampled: looked like a quality gap, was processing.
2. FSC curves vanished: RELION `_rlnResolution` is spatial frequency (1/Å), not Å.
3. Docking direction inverted on the first try - caught only by the correlation gate. Always gate.
4. Filler values in local-resolution maps -> hard edges, level-dependent colours.
5. `tile` + hidden local-resolution maps -> stuck colours.
6. A fixed cc >= 0.90 gate rejected a correct placement of a mirrored external map at different resolution; gate on
   the margin over controls at a common low-pass instead.
