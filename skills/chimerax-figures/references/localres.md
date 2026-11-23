# Colouring a density by local resolution (case B)

## Inputs and where they come from
- **Surface shape** comes from the density you display (sharpened, or Noise2Map-denoised for comparisons).
- **Colour** comes from the local-resolution map of the ORIGINAL analysis: RELION `relion_postprocess --locres`
  (`*_locres.mrc`; the relion-refine skill's postprocess step can produce it), M's `<species>_localres.mrc`, or any other
  program's per-voxel resolution map. Never derive local resolution from a denoised map.
- If no local-resolution map exists, say so and offer the command; running it is a CPU job (MPI), submitted with
  `cryoet_submit cpu ...` after asking. Example: `relion_postprocess --i half1.mrc --i2 half2.mrc --mask mask.mrc
  --angpix A --locres --o PostProcess/locres` (check `relion_postprocess --help` for the installed version). An error
  about `gs` (Ghostscript) only means the PDF histogram failed; the maps are written.
- The density and its local-resolution map must share grid, pixel size and origin. Check headers (box, voxel size,
  origin, nstart) for both. If the density is finer than its local-resolution map, Fourier-crop the density to the
  local-resolution grid (do not interpolate). If origins differ, align them with `scripts/set_origin.py --like`.
- When comparing maps, compute local resolution for every map with ONE recipe and ONE mask policy. If a map's existing
  postprocess used a different mask, re-postprocess with the common mask first.

## Fill outside the mask - always
Local-resolution maps carry filler values outside the mask (observed: RELION 0 far outside plus a ~29-50 Å ring just
outside; M 60 Å everywhere outside; version-dependent). A surface that crosses the mask edge samples them: 0 shows as the
best colour, 60 as the worst, with hard edges, and colours jump when the level changes. Symptom: sharp colour boundaries
that move with the contour level. Check: `fill_locres.py` reports the outside min/max before filling.
```
"$CRYOET_PYTHON" scripts/fill_locres.py --locres X_locres.mrc --mask X_mask.mrc   # in place, original kept as *_raw.mrc
```
Display only; state in the README that colour outside the mask is extrapolated. Keep `*_raw.mrc` out of the bundle zip.

## The ChimeraX block (write_cxc.py emits it)
```
open maps/A.mrc
open maps/A_locres.mrc
hide #2 models
rename #2 id #1.5
volume #!1 style surface level L step 1
surface dust #!1 size S
color sample #!1 map #1.5 palette 4.5,#fde725:5.188,#addc30:5.875,#5ec962:6.562,#28ae80:7.25,#21918c:7.938,#2c728e:8.625,#3b528b:9.312,#472d7b:10,#440154
key #fde725:<=4.5A #5ec962: #21918c:7.25A #3b528b: #440154:>=10A pos 0.40,0.06 size 0.2,0.03
```
- `color sample` reads the second map at each surface vertex in **scene coordinates** and re-reads it whenever the surface
  is rebuilt. Anything that moves the density without its local-resolution map (`tile`, independent rotation of an
  un-nested map) leaves colours stuck. Nesting (`#1.5`) fixes it.
- Grey patches (`outsideColor`, default #808080) mean the surface left the local-resolution box: detached map or
  mismatched grid/origin, not bad resolution.
- **Palette**: the style's palette (default: 9-stop viridis, first colour = best). Rebuild stops for other ranges with
  `"palette": {"best": b, "worst": w}` in the spec. Values beyond the ends take the end colours. Do not rely on a
  built-in `viridis` name.
- Choose `best` near the best Nyquist in the figure (2 x pixel) and `worst` ~10 Å for 5-7 Å maps. A map at 2.25 Å/px
  cannot report better than 4.5 Å while one at 2.0 Å/px can reach 4.0 Å: both show the best colour, so say so in the legend.
- The Surface Color panel applies its own range/palette and overwrites the script: ship `recolor.cxc`.

## How colour should behave with the level
Lower level -> surface moves out into flexible density -> colours shift toward worse, gradually. A dramatic change means
unfilled fillers or a detached local-resolution map. Check attachment in ChimeraX with `measure center #!3` and
`measure center #3.5` before and after rotating: same offset = attached.

## Stats to quote
Median / 5th / 95th percentile local resolution inside each map's own mask, from the ORIGINAL local-resolution map,
never from the filled one.
