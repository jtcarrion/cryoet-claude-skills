# M round schedule - a generic default

## Source: Tegunov et al. 2021 (Nat Methods), Methods for the EMPIAR-10499 ribosomes
"global movement and rotation, a 5x5x41 image-space warping grid, a 8x8x2x10 volume-space warping grid, as well as
particle pose trajectories with 3 temporal sampling points ... over 5 iterations. Starting with iteration 3, CTF
parameters were also refined. At the beginning of iteration 4, reference-based tilt movie alignment was performed".

## Default schedule (one MCore invocation per round, `ITER=3`, `MIN_PARTICLES` ~50-100)

| round | FLAGS (add to the previous round's) | EXPECT (xml_diff) |
|---|---|---|
| it0 | `--iter 0` (create_population) | none |
| it1-2 | `--refine_stageangles --refine_imagewarp WxH --refine_volumewarp XxYxZxT --refine_particles` | `GridAngle:GridMovement:GridVolumeWarp` |
| it3 | + `--ctf_defocus` (only if the species is finer than `--ctf_minresolution`, default 8 A) | + `GridCTF` |
| it4+ | + `--refine_tiltmovies` (slow; needs the original tilt movies) | same |
| later | + `--refine_mag` (slow) | + `MagnificationCorrection` |
| later | + `--ctf_zernike3` (beam tilt, trefoil) | + `ZernikeCoeffsOdd` |
| optional | `WEIGHTS="--resolve_items"` or `"--resolve_frames"` (EstimateWeights), then MCore | auto-added weight terms |

Stage angles stand in for the paper's "global movement and rotation". Grid sizes: image warp roughly matching the
detector aspect (e.g. 5x5 square, 6x4 landscape); volume warp 8x8x2x10 as in the paper. Introduce a grid once
(`FIRST_ITER_FRACTION=0.7` helps the first round), then repeat the SAME sizes on every later round.
`--ctf_cs` is rarely needed (Cs is also a proxy for pixel size) and is what contaminates seed folders: avoid it unless
the pixel size is in doubt. Stop when a round gains a few hundredths of an A on the RELION mask.

## Choosing a schedule
- **Dense** (several hundred particles/TS) with poses from a full RELION search: the schedule above, one term group
  at a time, each round judged by RELION-mask FSC + cross-FSC against one guard map (external preferred; see
  SKILL.md "Which guard map").
- **Sparse / culled** (well under ~150/TS): iter 0 only (M as reconstructor). If trying anyway: geometry only
  (`--refine_imagewarp WxH --refine_stageangles`, `MIN_PARTICLES` ~50, `FIRST_ITER_FRACTION=0.7`), NO
  `--refine_particles`, cross-FSC guard on.
- **Sparse subset of a dense set**: keep the rest as a non-overlapping companion species in the same population; it
  carries the per-series geometry. Judge only the subset species. Or refine on the dense set first and continue the
  subset from that geometry (a new species from M's half-maps + `--particles_m`).

## Weights (EstimateWeights)
Separate tool, separate from MCore's refinement: it fits per-series (`--resolve_items`), per-tilt
(`--resolve_frames`, averaged over series; both together = per series per tilt) or spatial (`--resolve_location`)
B-factor weights from the per-series FSCs the LAST MCore round wrote to `<popdir>/refinement_temp/<source>/*_fsc.mrc`;
the next MCore reconstruction uses them. `--min_resolution` (default 20 A) is the low-resolution limit of the fit;
`--reset` clears all weights. Flags checked against the Warp 2.0 source (EstimateWeights/Options.cs) - re-check with
`EstimateWeights --help` on your build. Gains are modest; it is a late polish step and needs the cross-FSC guard like
any shared term.

## Re-anchoring new orientations onto M trajectories
M tables store several temporal samples per particle (`_wrpAngleRot1..Psi3` for 3). To inject new RELION
orientations without losing the trajectory: for each sample s, R_s' = (R_s . R_mid^-1) . R_new, where R_mid is the
sample RELION's pose corresponds to. Importing the RELION poses as a single-pose table instead discards the
trajectories and can cost several A.

## CTF refinement gate
`--ctf_minresolution` (default 8.0 A) gates the WHOLE CTF block on the species GlobalResolution: coarser than that,
the CTF step never runs and "M ignored --ctf_defocus" (xml_diff shows no GridCTF change). Refined defocus goes into
GridCTF (per tilt), not the scalar Defocus. The default is well calibrated; lowering it gains little.
