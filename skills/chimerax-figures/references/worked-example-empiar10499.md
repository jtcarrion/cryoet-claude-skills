# Worked example: EMPIAR-10499 / EMD-11650 (public data)

In-cell *M. pneumoniae* 70S ribosomes, chloramphenicol-treated (EMPIAR-10499); the Warp/M authors' map of this dataset is
EMD-11650; chloramphenicol models in the peptidyl-transferase centre include PDB 7OOD (built into EMD-11999, a focused
50S map from this dataset), 8P7X and 8P8B. Facts below are what the figure work on this dataset settled; numbers are
indicative only.

- **Hand**: 70S maps refined from Warp exports of this dataset came out mirrored relative to EMD-11650. The atomic-model
  test (dock 8P7X as-is and into the flipped map, under the mask, z-score at heavy atoms) picked the flipped map by about
  2x, and the same test on EMD-11650 confirmed it is in the correct hand. Map-vs-map correlation could not tell.
  That figure mirrored along x (`array[:, :, ::-1]`); the skill's convention is z - both are valid hand flips, never mix
  them inside one bundle.
- **Reflection bug**: eigenvector-based docking once returned a det -1 "rotation" and docked the model mirrored; the
  superposition RMSD gate (tens of Å instead of ~1 Å) caught it.
- **Levels**: 70S ~2.5 MDa -> `--mw 2500` (~3.0e6 Å^3). Per-map CNN levels on two 70S maps enclosed volumes ~15% apart,
  hence `--match-volume` for comparisons. The ligand-median close-up level differed ~15% between fitted models (8P7X vs
  7OOD): name the model.
- **Local resolution**: fill outside the mask before display; RELION and M use different filler values.
- **Pixel size**: some RELION half-map headers read 2.2526 Å for nominal 2.25 Å; state both and use the nominal value.
- **Display**: zone radius 2.6 Å at 1.7 Å/px; mesh for the close-up; surface for the whole-ribosome overview.
