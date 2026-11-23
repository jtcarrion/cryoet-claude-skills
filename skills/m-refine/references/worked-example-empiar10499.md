# Worked example: EMPIAR-10499 (M. pneumoniae ribosomes, chloramphenicol)

Public data: EMPIAR-10499 (65 tilt series, 300 kV, Cs 2.7 mm, 1.7005 A/px raw, +/-60 deg dose-symmetric, 3 deg
step); published map EMD-11650 (Tegunov et al. 2021, 3.5 A); published particles EMPIAR-11843. This is one
reprocessing with this skill, not a benchmark.

- **Seed**: RELION refinement of ~29k WarpTools-exported particles at 3 A/px; iter 0 at ~450 particles/TS.
- **Schedule**: as in `recipe.md` - it1-2 stage angles + image warp 5x5 + volume warp 8x8x2x10 + poses; it3 +
  `--ctf_defocus`; it4 + tilt movies; it5-7 same; it8 + `--refine_mag`; it9 + `--ctf_zernike3`. Species swapped to
  the raw 1.7005 A pixel after it1 (new species from M's half-maps + M's table), temporal samples 3, lowpass 12 A.
- **Outcome**: RELION-mask FSC improved steadily over the rounds (from >10 A at iter 0 to ~5 A at it9); a later
  round on a cleaner tomoDRGN-filtered subset (~8.7k particles, ~140/TS, continuing from the dense set's geometry)
  reached ~4.3 A; stopped at +0.03 A per round. A per-series EstimateWeights round added roughly 0.2 A.
- **Lessons this dataset showed**: low particle density was fine once the geometry had been fitted on the dense
  set (continuation, not fresh fitting); importing RELION poses as a single-pose table instead of re-anchoring lost
  several A; magnification and tilt movies were the slowest rounds (1-2.5 h on 3-4 large GPUs).
- **Gotchas specific to this data**: the mdoc tilt-axis angle is ~90 deg off (use ~-4.3 deg on import); maps refined
  from Warp exports come out with the opposite hand to EMD-11650 - flip before comparing or depositing.
