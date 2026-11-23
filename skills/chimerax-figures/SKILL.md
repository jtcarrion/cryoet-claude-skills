---
name: chimerax-figures
description: Build ChimeraX .cxc scripts (and the map bundle around them) that display cryo-EM / cryo-ET densities in a configurable figure style (default white background, silhouettes, soft lighting) with dust hidden and computed contour levels - from one map on its own up to several maps side by side coloured by local resolution, Noise2Map-denoised comparisons, maps of opposite hand, and density + fitted PDB/mmCIF model + ligand close-ups. Use this whenever the user wants a ChimeraX figure, session, .cxc or .cxs, wants to "show", "render", "colour by local resolution", "compare maps side by side", "make a figure of the map/ligand/drug site", pick a contour level, or bundle maps for opening in ChimeraX - even if they don't say "skill" or "cxc". Works when ChimeraX is only on the user's laptop (the default: a script + bundle they open locally) or absent (the bundle is still produced).
---

# ChimeraX figures

Writes a folder the user opens in ChimeraX: maps + `.cxc` (+ `recolor.cxc`, `closeup.cxc`, README). Default assumption:
ChimeraX runs on the user's own machine, not where you work, so the scripts are validated **as text** (`check_cxc.py`),
never by a render you claim to have seen. Say that plainly in the reply.

## Setup check

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").

```
source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"     # loads ~/.config/cryoet-skills/config.sh
cryoet_require CRYOET_PYTHON || echo "set CRYOET_PYTHON (python with numpy, scipy, mrcfile; gemmi for ligands)"
cryoet_have calc_level && echo "CNN contour levels available" || echo "no CNN: use --mw / --volume / --ref-level"
cryoet_have noise2map  && echo "Noise2Map available"           || echo "no Noise2Map: no denoised comparisons"
cryoet_have chimerax   && echo "CHIMERAX_BIN=$CHIMERAX_BIN"    || echo "ChimeraX not configured here: deliver script + bundle"
echo "style: ${CHIMERAX_STYLE:-default}"
```
- `write_cxc.py` / `check_cxc.py` are stdlib-only (Python 3.6+, any locale) and run with any `python3`, even with no
  config. The map tools (`calc_level`, `fill_locres`, `place_matrix`, `set_origin`) need `"$CRYOET_PYTHON"`.
- **CNN levels** (optional): `CALC_LEVEL_REPO` = a clone of https://github.com/mariacarreira/calc_level_ChimeraX
  (AGPL-3.0; cite Kinman, Carreira et al. 2024, SIREn) with `tar -xzf weights.tar.gz` done, plus torch in
  `CRYOET_PYTHON`. Without it, use `--mw KDA` / `--volume A3`, and **say which rule was used**. A user with ChimeraX can
  also install that repo as a ChimeraX plugin and run `volume calc_level #1` locally; pass the result as `--ref-level`.
- **ChimeraX here** (`CHIMERAX_BIN` set and runnable on this machine): you may *offer* an offscreen syntax test
  (`$CHIMERAX_BIN --nogui --offscreen --exit figure.cxc` from inside the bundle, after asking - it loads every map;
  offscreen rendering needs a ChimeraX build with OSMesa). Otherwise never
  try to run ChimeraX. If ChimeraX is absent everywhere, still produce the bundle and say it needs ChimeraX >= 1.8.

## Inputs / Outputs (handoff)
| artifact | path pattern | produced / consumed | by |
|---|---|---|---|
| maps to show | `cryoet_project.json` `maps[]` `{name, map, half1, half2, locres, angpix, hand_flipped}`, or user paths | consumed | relion-refine, m-refine (also tomodrgn-run `vol_###.mrc`, EMDB downloads) |
| refinement half-maps / masks | `refinements[]` `{half1, half2, mask, angpix, resolution_A}` | consumed (Noise2Map, locres) | relion-refine |
| local-resolution map | `*_locres.mrc` / `<species>_localres.mrc` | consumed (filled copy in bundle) | relion-refine postprocess, m-refine |
| fitted model | `.cif` / `.pdb` (+ ligand residue name) | consumed | user / PDB |
| docking transform | `dock.json` `{"A": 3x3, "b_A": [3]}` (format in references/multimap.md) | consumed | user / any docking tool |
| levels | `<bundle>/levels.json` (`calc_level.py --json`) | produced | this skill |
| spec | `<bundle>/spec.json` | produced | this skill |
| scripts | `<bundle>/<name>.cxc`, `recolor.cxc`, `closeup.cxc`, `README.md` | produced | this skill |
| bundle maps | `<bundle>/maps/*.mrc` (origin 0; `*_zflip.mrc`; filled locres, `*_raw.mrc` kept out of the zip) | produced | this skill |
| figure record | `cryoet_project.json` `figures[]` `{name, bundle_dir, cxc}` | produced | this skill |
| session / images | `<name>.cxs`, PNGs | produced later, by the user's ChimeraX | user |

Read and record the project state (stdlib):
```
PS="${CLAUDE_SKILL_DIR}/scripts/_lib/project_state.py"
python3 "$PS" get "$PROJECT" maps                 # what upstream skills produced (may be absent: then ask for paths)
python3 "$PS" add "$PROJECT" figures '{"name": "fig1", "bundle_dir": "figures/fig1", "cxc": "figures/fig1/fig1.cxc"}'
```

## Pick the case
| Case | Inputs | Read |
|---|---|---|
| A. One density | one map | this file only |
| B. Density coloured by local resolution | map + local-resolution map (+ mask) | `references/localres.md` |
| C. Several maps compared | 2+ maps, maybe different software/hand/pixel size, often with B | `references/multimap.md` (+ localres.md) |
| D. Density + fitted model (+ ligand) | map + .cif/.pdb, ligand residue name | `references/model_ligand.md` |

Cases combine (C with B is the usual comparison figure). Only add what the user asked for - a single map needs no local
resolution, no denoising, no placement matrix. `references/chimerax_syntax.md` has checked command syntax and traps;
skim it before writing any command not generated by `write_cxc.py`.

## Procedure
1. **Inventory the inputs** before writing anything: for each map - file, box, pixel size (header AND nominal), origin /
   nstart, hand, which program made it (RELION postprocess / M / Noise2Map / tomoDRGN / EMDB), FSC 0.143 resolution; for
   local-resolution maps which mask and program. Read headers with `"$CRYOET_PYTHON"` + mrcfile (`header_only=True`).
   Put these in the spec's `header`. Ask only for what files cannot tell you (e.g. which map is the reference hand).
2. **Prepare maps** (only the steps the case needs; outputs go into `<bundle>/maps/`, never into the inputs' folders):
   - frames: `scripts/set_origin.py` (origin 0 for all bundle maps, or `--like` to match a density; prints the shift a
     fitted model would need);
   - local resolution: `scripts/fill_locres.py` (case B);
   - opposite hand / other frame: `scripts/place_matrix.py` (case C/D; z-axis flip + exact matrix, gated);
     say up front that this needs a docking transform (`dock.json` `{A, b_A}`, from a fit you or the user ran), that
     place_matrix refuses a matrix failing its gates (det +1, orthonormal, and a correlation margin over shifted and
     other-hand controls at a common low-pass - pass `--ref-res/--mov-res`), and that maps
     compared side by side must be processed identically (same denoising/sharpening; FSC from the original half maps)
   - denoising for comparisons: `scripts/noise2map.sbatch` via `cryoet_submit gpu 1 ...` (case C; optional, ask first).
   Bundle large maps by symlink when the user will copy with `rsync -L`; otherwise copy only what the figure needs.
3. **Contour levels**, `"$CRYOET_PYTHON" scripts/calc_level.py ... --json <bundle>/levels.json` - computed, never guessed:
   - one map: CNN if configured, else `--mw KDA` (ask for the mass if unknown) or `--volume A3`;
   - comparisons: ONE rule for all maps - `--match-volume` (CNN or `--ref-level`) or `--mw`;
   - ligand close-up: `--ligand-median model.cif --ligand RES`.
   Copy the output's `rule` into the spec's `level_rule`. Compute levels on the maps exactly as displayed (masked
   maps if you show masked maps - see "In-cell maps" below).
4. **Spec + generate**: write `<bundle>/spec.json` (format: `scripts/write_cxc.py --help`) and run
   `python3 scripts/write_cxc.py <bundle>/spec.json [--style NAME]`. It emits the `.cxc` (style block, open order,
   nesting, dust with its size in the header, palette, labels), `recolor.cxc` when colouring by local resolution, and
   `closeup.cxc` when a ligand close-up is given. Hand-edit afterwards if needed.
5. **Check**: `python3 scripts/check_cxc.py <file.cxc>` (and `--closeup` for follow-on scripts). Fix every FAIL; style
   WARNs are fine when the user chose a different look.
6. **README + record**: `README.md` with provenance, levels and rule, what was denoised / filled / flipped (and on which
   axis), a **Display** line per map (soft-masked or unmasked, which mask, and why - the same text as its spec
   `masking`), how to open ("copy the folder, `cd` into it in ChimeraX, `open <name>.cxc`"), and a transfer hint
   (`rsync -avL <bundle> laptop:` or the site's transfer node / web portal; `SITE_NOTES_FILE` may say which). Record the
   bundle in `figures[]`. The `.cxc` ends with `save <name>.cxs includeMaps true`.

## Style (appearance only)
`styles/default.json` (white background, `lighting soft`, silhouettes 1.5, grey `#b4b4b4`, viridis local-resolution
palette, key and label placement, model colours), `styles/publication-dark.json` (talks/posters), `styles/minimal.json`
(close to ChimeraX defaults). Choose with `CHIMERAX_STYLE` (name or path to a JSON file), the spec's `"style"`, or
`--style`; tweak single keys with `"style_overrides"`. If the user asks for a different look ("black background, no
silhouettes"), honour it via the style - it never relaxes the rules below. `write_cxc.py --print-style` shows the
resolved style. `check_cxc.py` reads the `# Style:` header line and only WARNs on deviations.

## Rules that matter (and why)
- **`step 1` always**: ChimeraX auto-coarsens big maps, silently making figures blockier than the data.
- **Hide dust on every displayed surface** right after its level, and write the size into the header: noise blobs inflate
  apparent quality, but dust hiding also hides genuine weak/peripheral density smaller than the size. Default size =
  10 x voxel size (what ChimeraX's Map-toolbar dust button uses). Turning it off needs a stated reason.
  `surface zone`/`showall` switch dust off, and `surface dust` switches zoning off - never dust a zoned close-up.
- **Paths in the `.cxc` are relative**: opening a `.cxc` makes its folder the current directory while it runs.
- **Open every file first, then hide / nest / rename.** ChimeraX gives a freed top-level id to the next model opened.
- **A local-resolution map must be a child of its density** (`rename #2 id #1.5`) before any `view matrix`: `color
  sample` reads it in scene coordinates, so if the density moves without it the colours stick in place.
- **After nesting, `#1` also means `#1.5`.** Use `#!1` for `volume`, `color sample` targets and name `rename`s.
- **Never `tile` with `color sample`**: it moves top-level models only. Put side-by-side offsets in `view matrix`.
- **Comments are whole lines starting with `#`** (or `; # ...`). `cmd # note` is parsed as an atom spec and errors.
- **Compare like with like**: denoise or filter all compared maps identically, say so in the labels, and quote FSC /
  local-resolution numbers from the ORIGINAL maps.
- **Same contour rule for every compared map**, stated in the header (`Level rule:`) and the README: one documented
  rule (`--match-volume`, `--mw` or `--ref-level`) applied to every displayed map, never a per-map eyeballed level.
- **In-cell maps: show the soft-masked map.** For sub-tomogram averages from cells, the unmasked box usually contains
  neighbouring cell material (membrane, other complexes, cytoplasm) that is above threshold - often the majority of
  the above-threshold density - and an enclosed-volume or mass rule then lands on the wrong level. Check: fraction of
  above-threshold voxels outside the refinement mask. Display the map with the refinement's soft mask applied (e.g.
  RELION postprocess `*_masked.mrc`), compute the level on that masked map, set `"in_cell": true` and a per-map
  `"masking"` in the spec (written to the header), and say so in the README. Show the unmasked box only on purpose
  (context figure), labelled as such.
- **Never resample to align.** Flip by array reversal, place with an exact rotation + translation, gate it (det +1,
  orthonormal, correlation margin over shifted / other-hand controls on a common low-pass - not an absolute cc, which
  is far below 0.9 for correct placements of maps at different resolution) before writing the script.
- **Hand**: decide it against an atomic model, not by map-vs-map correlation (margins ~1%). Flip maps, never models.
- **Named views** restore camera, clip planes and model positions, not display state: overview and close-up are separate
  scripts that set both.

## Deliverable checklist
- [ ] style block + `close session`; dust per displayed surface with size in the header; `step 1`
- [ ] levels computed by a stated rule (same rule across a comparison); CNN or fallback named
- [ ] local-resolution maps filled, nested, hidden; explicit palette stops + `key`; `recolor.cxc`
- [ ] placement gated (det, orthonormality, correlation) if any map was moved or flipped; flip axis stated
- [ ] `check_cxc.py` has no FAIL; header gives provenance, resolution, hand, levels
- [ ] in-cell data: soft-masked maps shown (or unmasked on purpose), stated per map in header + README
- [ ] README; relative paths; `save ... includeMaps true` at the end; `figures[]` recorded
- [ ] told the user it was validated as text and must be opened in ChimeraX (version assumed: 1.8+)

## References
`references/chimerax_syntax.md` (checked syntax, traps) - `references/localres.md` (case B) - `references/multimap.md`
(case C, Noise2Map, docking JSON format) - `references/model_ligand.md` (case D, hand test, flip axis) -
`references/worked-example-empiar10499.md` (worked example on public data).
