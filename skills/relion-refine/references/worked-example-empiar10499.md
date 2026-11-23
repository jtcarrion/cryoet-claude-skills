# Worked example: EMPIAR-10499 (M. pneumoniae ribosomes, chloramphenicol-treated)

Public data: EMPIAR-10499 tilt series; reference map EMD-11650 (from the Warp/M authors, same dataset); published
particle set EMPIAR-11843. Facts below are from reprocessing it with this skill; numbers are indicative.

**Acquisition.** 1.7005 A/px, 300 kV, Cs 2.7 mm, amplitude contrast 0.07, 41 tilts +/-60 deg in 3 deg steps
(dose-symmetric). The mdoc tilt axis is wrong by 90 deg (see warptools-preprocess); the tilt-series geometry must be
fixed before any export.

**Export.** Tomogram picks at 10 A/px -> `COORDS_ANGPIX=10`; M species tables -> `COORDS_ANGPIX=1`. A 2-3x coarser
export (e.g. box 64 at ~5-10 A/px) is enough for a first refine; ~2 A/px with a box of ~1.5-2x the 70S diameter
(~250 A) for high resolution.

**Memory.** 22.7k particles, box 64, 41 tilts: ~14 GiB per float copy, ~85 GiB preread on 4 GPUs - preread fits. The
same set at box 128 is ~57 GiB/copy (~380 GiB preread) - scratch on most nodes.

**Greyscale.** EMD-11650 resampled to the export grid was ~50x too faint relative to the particles: flat posteriors
(median significant samples in the thousands, MaxValueProb ~0), iteration 1 projected at more than a day. With
`EXTERNAL_REF=1` (`--firstiter_cc --scale`) iteration 1 took normal time. The bench arm WITH `--firstiter_cc` looked
perfect even for a wrong-frame reference, which is why diagnosis is done without it.

**Hand.** Seeding with EMD-11650 in the wrong hand converged to the wrong hand and stalled at ~50 A, while the
correct hand reached ~20 A in the same coarse run. An end-to-end rerun repeated this (as-deposited ~24 A, Z-flipped
~12 A) because the hand was only tested after the first full refinement: with an EMDB seed, run the step-5 hand test
first (iteration-1 arms were flat for both hands here, so the `--firstiter_cc` 3-iteration arms decide). Separately, the final RELION maps from the Warp export came out
mirrored relative to EMD-11650 even though the tilt-series defocus-hand check passed; flip the final map (not the
data) before any comparison with or deposition next to EMD-11650.

**Measuring.** All comparisons on one soft mask with fscrand_hi <= 0.05; M half-maps re-measured with
`postprocess.sbatch HALF1/HALF2` on that same mask rather than quoting M's own FSC.

**Test subset.** Three series (00254, 00255, 00261) are enough to validate the whole chain end to end; expect a much
worse resolution than the full set - validate the chain, not the number.
