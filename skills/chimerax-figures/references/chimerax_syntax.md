# ChimeraX command syntax used by this skill

Checked against the ChimeraX User Guide (https://www.cgl.ucsf.edu/chimerax/docs/user/commands/) on 2026-11-21. Scripts
target ChimeraX 1.8 or later (`CHIMERAX_VERSION` in the config only changes the header comment). If a command errors in
the user's version, `usage <command>` inside ChimeraX shows that version's options.

| command | syntax | notes |
|---|---|---|
| background | `set bgColor white` | style |
| lighting | `lighting soft\|gentle\|full\|simple\|default\|flat` | soft = ambient only, 64-direction ambient shadows, depth cue on; gentle = soft tuned for larger indentations; full adds key-light shadows; flat turns silhouettes on |
| silhouettes | `graphics silhouettes true\|false [width W] [color C] [depthJump 0.03]` | width default = display scaling (1, or 2 on HiDPI) |
| dust | `surface dust #!1 size S [metric size\|area\|volume\|size rank\|area rank\|volume rank] [update true]` | default size 5, metric size (bounding-box side, Å). Skill default S = `dust_factor` (10) x voxel size. `surface undust` undoes |
| dust vs zone | | per the guide, `surface zone` / `surface showall` turn dust hiding off, and `surface dust` turns zoning off. Do not dust a zoned close-up |
| level | `volume #!1 style surface\|mesh level L step 1 [color C] [transparency 0-1]` | `step 1` = every voxel; without it ChimeraX auto-coarsens to stay under its voxel limit (1 Mvoxel) |
| flip | `volume flip #1 [axis x\|y\|z]` | default axis z; reverses data planes (no interpolation), new map |
| map zone | `volume zone #!1 nearAtoms <atoms> range R [newMap false]` | range default 3 Å |
| surface zone | `surface zone #1 nearAtoms <atoms> distance D` | keyword `distance`, default 2 Å; `surface unzone` |
| sample colour | `color sample #!1 map #1.5 palette <spec> [range low,high\|full] [offset d] [outsideColor C] [update true]` | defaults: palette redblue, range full, outsideColor #808080 (vertices outside the sampled map's box), update true |
| palette spec | `4.5,#fde725:5.19,#addc30:...:10,#440154` | value,colour pairs joined by `:`. `viridis` is NOT in the documented built-in list (`palette list` shows what a version has); write explicit stops |
| key | `key #fde725:<=4.5A #5ec962: ... pos 0.40,0.06 size 0.2,0.03` | colours left->right; pos = lower-left corner, window fractions; defaults size 0.25,0.05, pos 0.7,0.08; quote labels with spaces; `key delete` |
| 2D labels | `2dlabels text "..." xpos 0.02 ypos 0.92 size 16 color black` | window fractions |
| placement | `view matrix models #3,r11,r12,r13,t1,r21,r22,r23,t2,r31,r32,r33,t3` | row-major, translation is numbers 4, 8, 12, no spaces; one model per line. `view matrix` alone reports current positions |
| same transform | `view position #2 sameAsModels #1` | copies a transform, does not superimpose |
| named views | `view name overview` / `view overview` / `view list` | camera, clip planes, model positions; NOT display state; saved in sessions |
| nesting | `rename #2 id #1.5` | children move with the parent |
| rename | `rename #!1 "name"` | `#!1` = model 1 only (plain `#1` renames its children too) |
| hide models | `hide #2,4 models` | |
| colour by element | `color SPEC byhetero` | like byelement but leaves carbons unchanged |
| independent rotation | `mousemode right "rotate independent"` | each top-level model about its own centre (what `tile` assigns to the left button) |
| session | `save name.cxs includeMaps true` | embeds maps -> opens anywhere |
| image | `save name.png width 3000 supersample 3` | |

## Traps
- **Comments**: only lines whose first non-space character is `#`, or `; # ...` after a command, are comments. A `#` after a
  command without the `;` is read as an atom spec -> errors such as "Expected a keyword".
- `#1` matches #1 AND its children (#1.5); `#!1` is model 1 only. Use `#!N` for `volume`, `color sample` targets and
  name `rename`s once a child is nested, or the hidden local-resolution map is shown or renamed too.
- ChimeraX reuses a freed top-level id for the next model opened: open everything, THEN rename/nest.
- `tile` and `mousemode right "rotate independent"` move top-level models; un-nested hidden maps stay behind.
- The Surface Color panel overwrites scripted palettes; re-run `recolor.cxc`.
- Opening a `.cxc` makes its folder the current directory while it runs (then restores it), so relative paths resolve
  from the script's folder.
- Model ids in a written script assume a fresh session (`close session` first).
