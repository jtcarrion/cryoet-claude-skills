# Worked example: EMPIAR-10499 (M. pneumoniae, chloramphenicol-treated; ribosome reference EMD-11650)

Public dataset, 65 tilt series. These are the values the general rules in `pitfalls.md` produced on it; use them to
recognise the same traps elsewhere, not as defaults.

| item | value | rule it illustrates |
|---|---|---|
| pixel size | 1.7005 A/px (MDOC PixelSpacing = header) | confirm against the header |
| voltage / Cs / AC | 300 kV / 2.7 mm / 0.07 (voltage is not in the MDOC: ask) | microscope constants from the data or user |
| movies | 12 frames per tilt (NumSubFrames) -> `M_GRID 1x1x12` | NFRAMES required |
| dose | 0.27054 e/A^2 per frame -> `--exposure -0.27054`; ~3.25 per tilt -> `--tilt_exposure` | negative = per frame |
| tilt scheme | 41 tilts, -60..+60 step 3, dose-symmetric | dose order from DateTime |
| defocus | target 1.75-3.75 um underfocus | bracket DEFOCUS_MIN/MAX |
| image size | header 3838 x 3710; MDOC ImageSize "3708 3838" (transposed) | header is authoritative |
| tilt axis | MDOC 85.7 deg; true -4.3 deg -> `OVERRIDE_AXIS=1 TILT_AXIS=-4.3` | transposed size = axis 90 deg off |
| axis symptom | IMOD residual tens of nm with 85.7, below 1 nm with -4.3; IMOD log "rotation angle seems to be closer to -4.3" | confirm on one series |
| gain | `CountRef_*.dm4`, needs `--gain_flip_y` (no transpose) | check gain orientation |
| extra file | `TS_01_001_-0.0.tif` has no MDOC entry (counting reference) | ignored by ts_import |
| gold | 10 nm beads -> `ALIGN_METHOD=fiducials FIDUCIAL_NM=10`; patches / AreTomo3 as comparison arms | gold -> fiducials |
| tomogram | `TOMO_DIM 3838x3710x2000`, reconstructed at 10 A/px | generous Z |
| hand | the original processing used Warp's default ts_import (no `--dont_invert`) and the check said 'no flip'; the same series imported with `--dont_invert` says 'flip' | check follows the convention |
| map hand | refined maps came out mirrored vs EMD-11650 despite the 'no flip' check -> flip the final maps for comparison/deposition | defocus hand != map hand |

Suggested smoke-test series: 00254, 00255, 00261 (good particle density, beads visible).

`init_project.sh` call for this dataset (paths are placeholders):
```
bash "${CLAUDE_SKILL_DIR}/scripts/init_project.sh" --proj /data/me/EMPIAR-10499 RAW_FRAMES=/data/me/10499/frames \
  FRAME_EXT="*.tif" MDOC_DIR=/data/me/10499/mdocs HAVE_FRAMES=1 NFRAMES=12 ANGPIX=1.7005 VOLTAGE=300 CS=2.7 \
  DOSE_PER_FRAME=0.27054 DOSE_PER_TILT=3.2465 TILT_AXIS=-4.3 OVERRIDE_AXIS=1 TOMO_DIM=3838x3710x2000 \
  GAIN_PATH=/data/me/10499/CountRef_TS_01_001_-0.0.dm4 GAIN_FLAGS=--gain_flip_y DEFOCUS_MIN=1.0 DEFOCUS_MAX=5.0 \
  ALIGN_METHOD=fiducials FIDUCIAL_NM=10 TS_IMPORT_DONT_INVERT=0
```
