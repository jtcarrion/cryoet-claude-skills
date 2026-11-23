# Stage graph and decision points

| stage (skill) | needs | produces | typical compute | optional? |
|---|---|---|---|---|
| warptools-preprocess | movies or stacks, mdocs, gain ref, pixel size, dose | Warp project: motion/CTF, aligned tilt series, CTF, tomograms | GPU; hours per 50-100 series | core |
| teamtomo-preprocess | a Warp project (XMLs) or raw tilt series | tomograms from Warp XMLs, or TeamTomo alignments written back as a Warp arm | multi-GPU, 1 job | yes (TEAMTOMO_REPO) |
| picking | tomograms | coordinate STAR + its pixel size | - | **external** (user-supplied) |
| relion-refine | Warp project, particle STAR, reference, mask | particle series, Refine3D dir, half maps, postprocess, FSC | multi-GPU, hours-days | core |
| tomodrgn-run | export with `--dont_premultiply`, a consensus refinement | VAE, k-means classes, selection STARs | 1 GPU, hours | yes (TOMODRGN_ENV) |
| m-refine | a RELION refinement + its Warp project | cloned M population, per-round half maps, refined geometry/CTF | multi-GPU, hours per round | yes (MCore) |
| chimerax-figures | maps (+ half maps, locres, models) | .cxc + bundle to open in ChimeraX | none (local render) | yes |

Decision points the director must put to the user (not decide silently):
1. **Alignment method** (fiducial / patch / AreTomo / TeamTomo) - gold beads present? compare arms on a few series first.
2. **Defocus hand** - after alignment, before CTF (`ts_defocus_hand --check`).
3. **Particle source** - which STAR, at what pixel size, how many per tomogram; sanity-check positions on a tomogram.
4. **Reference** - external EMDB map (low-pass, correct box/pixel, `--firstiter_cc`) or de novo.
5. **Map hand vs. reference/model** - after the first good refinement; record in `decisions`.
6. **tomoDRGN classes to keep** - the user chooses from the class-review aid; never auto-select.
7. **When to stop M rounds** - a round that does not improve the fixed-mask FSC, or whose cross-FSC suggests
   overfitting, ends the schedule.
Validate the chain on 2-3 tilt series before committing a full dataset.
