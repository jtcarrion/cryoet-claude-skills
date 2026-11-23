# Worked example: EMPIAR-10499 (M. pneumoniae ribosomes, chloramphenicol-treated)

Public data: EMPIAR-10499 tilt series (65 series, 41 tilts, dose-symmetric +/-60 deg, 1.7 A/px raw); reference map
EMD-11650; published particle set EMPIAR-11843. Outline of one run, light on numbers.

- **Upstream.** WarpTools fiducial alignment, RELION 5 refinement of a picked ribosome set, origins folded into the
  centres, particles with negative coordinates dropped (an earlier attempt failed on them).
- **Export for tomoDRGN.** `ts_export_particles --2d --dont_premultiply` at 6 A/px, box 96 (~30k particles).
  A separate finer, premultiplied export served refinement; selections were mapped onto it by coordinates.
- **Polarity.** Measured on the export: this dataset trained with `--uninvert-data`. Another Warp build / dataset
  needed the default inversion - which is why the check is per export.
- **Model.** zdim 8, 20 epochs, batch 10, data in RAM, 1 A100: about 4 min/epoch. Loading the stacks took minutes.
- **Analysis.** k-means 50 reviewed against the refinement's consensus map: a minority of classes looked like intact
  ribosomes; the rest were blobs, fragments or mis-posed. The user kept the ribosome classes (roughly a third of
  the particles).
- **Validation.** The kept subset refined to a better resolution than a size-matched random subset with identical
  poses and mask, and its poses agreed far better with the published poses than the rejected particles did. A
  smaller curated subset beat the larger pool.
- **Hand.** Maps refined from these Warp exports came out mirrored relative to EMD-11650; flip before comparing.
