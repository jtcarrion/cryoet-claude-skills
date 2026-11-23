# Density + fitted model (+ ligand) (case D)

## Deliberate rules
- **Hand is decided against an atomic model, before any display.** Dock a deposited model into the map AS-IS and into
  the map FLIPPED, under the particle mask, refine each (e.g. 8 -> 5 -> 4.5 Å low-pass), and score the mean map z-score
  at heavy atoms. The correct hand wins clearly (roughly 2x in z-score in our experience); run the same test on a
  deposited map of known hand as a control. Map-vs-map correlation and low-resolution envelope fits do NOT decide hand
  (~1% margins).
- **Flip the MAP, never the model.** Mirror the map (and its mask and local-resolution map, on the same axis) and keep
  the deposited model. Skill convention: mirror along **z** (numpy axis 0, `array[::-1]`; ChimeraX `volume flip`
  default), which is what `place_matrix.py` does and assumes. Any single-axis mirror inverts the hand - x and z mirrors
  differ only by a 180 degree rotation - so a bundle made with an x mirror is not wrong, but every map in it must use the
  same axis and the placement matrix must be derived for that axis. State the axis in the header and README.
- **Rotations must be proper.** Principal axes from `np.linalg.eigh` (or SVD) can come back with det -1; a "rotation"
  that is silently a reflection docks the model mirrored. Force det(V) = +1 and assert det(R) > 0.99.
- **Dock under the particle mask.** In crowded (e.g. in-cell) maps, neighbour density pushes both hands to similar CC.
- Sanity gates before trusting a fit: superposition RMSD of shared atoms (P / C-alpha) between related models ~1 Å
  (tens of Å exposes a reflection); local refinement should move the model < 1 degree.
- **Overview = surface, close-up = mesh**: a mesh lets the sticks show inside the density.
- **Zone the close-up** to the ligand + contacts (`volume zone #!1 nearAtoms sel range r`); otherwise a large map buries
  the site. Do not run `surface dust` after a zone (it turns zoning off).
- **Origins**: the model sits in the frame of the map it was fitted to. Do not zero that map's origin unless you move
  the model by the same shift (`set_origin.py` prints it).
- Header comments state map provenance, resolution, hand (and flip axis) and model sources; paths relative.

## Sensible defaults (change with reason)
| setting | default | note |
|---|---|---|
| zone radius | ~1.5 voxels (2.6 Å at 1.7 Å/px) | ~3-3.5 Å for 4.5-6 Å maps |
| contacts shown | within 4.5 Å of the ligand | labels only within 4 Å |
| clip | +/- 9 Å around the ligand | |
| overview map | style `map_color`, transparency `overview_map_transparency` (0.65) | so the cartoon shows through |
| colours | from the style (`models`, `closeup` blocks) | keep consistent across figures |

## Levels - computed, never typed
- Overview: `calc_level.py --mw KDA` / `--volume`, or the CNN level.
- Close-up mesh: `calc_level.py map.mrc --ligand-median model.cif --ligand RES` = 0.8 x median map value at the ligand's
  heavy atoms, so the ligand sits just inside the mesh. **The answer depends on which fitted model you sample** (models of
  the same complex can differ by ~15%): name the model in the header.
- A ligand-derived level makes a weak or partial-occupancy ligand look as convincing as anything else. Always report the
  ligand's density relative to its neighbours next to the figure (e.g. z-score at ligand atoms vs at protein/RNA atoms
  within 8 Å, and where the site falls among random placements) and say so in the README.

## Overview vs close-up
`view name` restores camera, clip planes and model positions but NOT display state (styles, zones, levels). So:
- main `.cxc` = overview display state + `view name overview`;
- `closeup.cxc` = sets the close-up display state itself (mesh, zone, sticks, labels, clip) + `view name closeup`;
- going back = re-open the main `.cxc`. `write_cxc.py` emits both from one spec (`"closeup": {...}`).
- Alternative ligand poses / models: a separate toggle `.cxc`, not a comment.
- Add a `save <png> width 2000 supersample 3` line per view and a 2D title with resolution, level and model ID.

## Do not
- Judge fit or hand from 2D slice images at ~1.7 Å/voxel - nearly unreadable; judge in 3D.
- Show a ligand without stating occupancy/density evidence relative to its surroundings.
