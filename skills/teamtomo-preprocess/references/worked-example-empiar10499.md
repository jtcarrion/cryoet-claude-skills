# Worked example: EMPIAR-10499 (public)

EMPIAR-10499: tilt series of native *M. pneumoniae* cells (chloramphenicol-treated), gold fiducials, dose-symmetric
+-60 deg. Reference map EMD-11650. Numbers below are from the teamtomo-workflows README validation (one series,
TS_00254) and are what "working" looks like.

- **xml_to_tomograms vs WarpTools ts_reconstruct** (same XML, same pixel size): Pearson corr 0.995 full resolution,
  0.999 after a 1-voxel Gaussian, amplitude ratio 0.999. Anything well below this on an unchanged XML is a problem.
- **TSA (blind axis search)**: tilt axis -4.50 deg vs IMOD fiducial -4.30 deg. Gold-bead reprojection error ~1 px,
  between IMOD fiducial alignment (better) and Warp's AreTomo import (worse). Defocus within 0.02 um of ts_ctf.
- **MDOC trap on this dataset**: the MDOC tilt axis is 90 deg off the real one (85.7 vs ~-4.3). A TSA run with
  `--axis-prior tomostar` inherits whatever the tomostar says; a blind run (`null`) finds the real axis. If the
  blind axis and the tomostar prior differ by ~90 deg, check the MDOC (warptools-preprocess inspect_mdoc warns).
- **Hand**: Warp's ts_defocus_hand says 'no flip' here, and maps refined from it still come out mirrored relative to
  EMD-11650 - a defocus-hand check is not an absolute map-hand check.
- Sizing: 10 A tomograms are a few hundred MB each (float32); xml_to_tomograms takes seconds per series on one
  data-centre GPU, TSA a minute or two.
