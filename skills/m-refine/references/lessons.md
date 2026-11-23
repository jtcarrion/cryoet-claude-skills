# M lessons (general form: symptom -> check)

Behaviour below was read from, or confirmed against, the Warp 2.0 source; re-check after a Warp upgrade.

- **Mask convention.** M grows any input mask by ~3 x Softness (Softness = GlobalRes / (2 x pixel)), i.e. ~1.5 x
  GlobalRes in A of dilation plus a cosine edge. On identical poses M's number comes out worse than RELION's; never
  compare them. Measure everything on the RELION soft mask (`measure_halfmaps.py`).
- **Iter 0 = transfer cost.** M iter 0 on RELION's poses, measured on RELION's mask, should land within a few tenths
  of an A of the RELION result. A larger gap means a transfer problem (pixel size in the half-map headers, mask grid,
  particle coordinates units, hand).
- **M's stored *_mask.mrc is the tight BINARY input** - measuring on it gives fscrand_hi far above 0.05.
- **Rescale a mask by pixel size before padding** to a different box, or it shrinks in A and fakes a better number
  (fscrand_hi jumps). `measure_halfmaps.py` does this.
- **Inherited image warp is real signal.** Zeroing or resizing it costs resolution that pose refinement does not
  recover. It is frame-locked to the tilt-series alignment: never carry it (or poses) into a different alignment -
  reused poses after an alignment change give a map that is many A worse.
- **Resize trap** (image AND volume warp): any size passed to `--refine_imagewarp` / `--refine_volumewarp` other than
  the stored one resamples the field. The size stored in the population's LastRefinementOptions is an inert default;
  the XML grid dimensions are what count (xml_diff prints them on change).
- **Volume warp may not engage** - check that GridVolumeWarp* actually changed (xml_diff).
- **Pose refinement vs good poses.** On culled/sparse sets M pose refinement can steadily erase the gain from
  culling, even with a matched reference. Discriminator: particles per tilt series.
- **Shared-term overfitting** shows as own-FSC up, cross-FSC down (and sometimes fscrand rising). Revert.
- **Cross-FSC** must use the unfiltered half-map average and the same reference file for a whole series of rounds
  (iter 0 included); an unsharpened map is the better reference (a sharpened map works but reads lower).
  <!-- NEEDS AUTHOR REVIEW: rule change below proposed from one end-to-end test; original author to approve. -->
- **The RELION map is not an independent guard beyond its own resolution.** `run_class001.mrc` comes from the same
  particles and poses as M's half-maps, so above the RELION resolution its cross-FSC is shared noise: inflated at
  iter 0 and falling as soon as M moves poses - a real gain then reads as overfitting. Symptom: own-FSC up, both
  half-maps up, cross-FSC vs RELION down mostly at fine resolution. Check: cross-FSC vs an external map of the same
  complex (hand- and pixel-matched) - if it rises too, the gain is real. Prefer such a map (or a held-out-particle
  reconstruction) as `GUARD_REF`; with only the RELION map, score cross-FSC coarser than the RELION resolution
  (`GUARD_REF_KIND=relion RELION_RES=..`).
- **Iter-0 audit noise.** MCore's first write turns empty `ZernikeCoeffsOdd/Even` into zero lists and fills a
  placeholder `VolumeDimensionsAngstrom` Z (1 -> the tomogram thickness). Neither is a refined value; `xml_diff.py`
  compares numerically and reports them as `ok`/`info`. If an audit still flags iter 0, read `check_transfer.py`'s
  verdict (it runs regardless) before treating the population as broken.
- **Rewritten tomostars orphan particles**: species particles are matched to series by a hash of the series name +
  the start of its `.tomostar`; after a rewrite every series falls below `--min_particles` and is skipped - a very fast
  round with no "Final score" lines.
- **Box exactly 128 px** - silent no-op (see SKILL.md).
- **Runtime/memory**: `--perdevice` > 1 needs spare VRAM (fine on 80 GB cards at moderate boxes); host RAM of a few
  hundred GB is normal. Tilt movies and magnification are the slow terms.
- **Logs**: refine-log names differ between builds (e.g. `000000-refine-<series>.log`); a too-specific glob finds
  nothing silently.
- **Weight threshold**: the CLI default `--weight_threshold 0.05` is used; the value stored in the .population is not.
  At high total dose it Fourier-crops late tilts around 5-6 A - only a limit for sub-5 A work.
- **MCore --iter 0 rewrites every XML byte-wise** (new attributes) without changing values - diff parsed values.
- `relion_tomo_reconstruct_particle` / `relion_reconstruct` cannot reconstruct WarpTools particle series; M (iter 0)
  or relion_refine can.
- **Single-series WarpTools reruns rewrite processed_items.json wholesale** - keep a copy in every population
  (create_population and every snapshot do).
- **`--min_particles` counts all species** in a series, so a sparse species can be refined on the strength of a
  dense companion.
- **OPEN**: do series skipped by `--min_particles` still contribute to the reconstruction? The source skips only the
  refinement step for them (TiltSeries.MPARefinement.cs); the reconstruction path is unverified. Check before relying.
