#!/usr/bin/env python3
"""Write a teamtomo-workflows run config (YAML) following this skill's data-management rules, and validate it.

  python make_config.py --workflow xml_to_tomograms|tsa_to_tomograms (--warp-project DIR | --stacks GLOB)
                        --project-root DIR --tag NAME [--series a b ...] [--recon-px 10] [--thickness-A N]
                        [--axis-prior tomostar|DEG] [--flip-hand] [--no-ctf] [--no-warp-xml] [--align-px 10]
                        [--tilt-angles PATTERN] [--stack-px A] [--out-config PATH]

Output root: <project-root>/teamtomo/<workflow>_<tag>/ - one root per run configuration, never inside a Warp
processing folder (warp_tiltseries*/, warp_frameseries*/, tomostar/) - checked on path components. The
config is written INTO that root (config.yaml) so the root is self-describing; teamtomo's own run.json in every series
folder records the merged config, package versions, GPU and timings.
Re-using a tag with a DIFFERENT config is refused (a mixed root cannot be interpreted); same config = resume.
Validated with teamtomo_workflows.load_config from the repo (no repo edits).
"""
import argparse, os, sys
from pathlib import Path

FORBIDDEN_PREFIX = ("warp_tiltseries", "warp_frameseries")
FORBIDDEN_NAME = ("tomostar", "tiltstack", "average")


def forbidden(path):
    """True if any path component is a Warp processing folder (component test, not a substring test)."""
    return any(p.startswith(FORBIDDEN_PREFIX) or p in FORBIDDEN_NAME for p in Path(path).parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workflow", required=True, choices=["xml_to_tomograms", "tsa_to_tomograms"])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--warp-project"); g.add_argument("--stacks")
    ap.add_argument("--project-root", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--series", nargs="+"); ap.add_argument("--recon-px", type=float, default=10.0)
    ap.add_argument("--thickness-A", type=float); ap.add_argument("--axis-prior"); ap.add_argument("--flip-hand", action="store_true")
    ap.add_argument("--no-ctf", action="store_true"); ap.add_argument("--no-warp-xml", action="store_true")
    ap.add_argument("--align-px", type=float, default=10.0); ap.add_argument("--tilt-angles"); ap.add_argument("--stack-px", type=float)
    ap.add_argument("--no-local-shifts", action="store_true", help="xml_to_tomograms: ignore Warp's GridMovement")
    ap.add_argument("--out-config")
    a = ap.parse_args()
    root = Path(a.project_root).resolve() / "teamtomo" / f"{a.workflow}_{a.tag}"
    if forbidden(root):
        sys.exit(f"REFUSING output root inside a Warp processing folder: {root}")
    if a.stacks and (a.stack_px is None or a.thickness_A is None):
        sys.exit("--stacks needs --stack-px (input pixel size, A) and --thickness-A (tomogram thickness, A)")
    inp = {"series": a.series or "all"}
    if a.warp_project:
        wp = Path(a.warp_project).resolve()
        for need in ("warp_tiltseries", "warp_tiltseries.settings"):
            if not (wp / need).exists():
                sys.exit(f"{wp} is not a Warp project view ({need} missing) - for a variant/arm folder use project_view.py")
        x0 = next(iter(sorted((wp / "warp_tiltseries").glob("*.xml"))), None)
        if x0 is None:
            sys.exit(f"no XMLs in {wp}/warp_tiltseries")
        if "ImageDimensionsAngstrom=" not in x0.read_text()[:4000]:
            sys.exit(f"{x0.name} lacks ImageDimensionsAngstrom (older Warp build) - teamtomo cannot read it; build a view:\n"
                     f"  python project_view.py --base-project {wp} --out <project>/teamtomo/views/<name>")
        inp["warp_project"] = str(wp)
    else:
        inp.update(stacks=a.stacks, tilt_angles=a.tilt_angles, pixel_spacing=a.stack_px)
    cfg = {"workflow": a.workflow, "input": inp, "output": {"root": str(root), "overwrite": False},
           "reconstruction": {"pixel_spacing": a.recon_px, "thickness_angstrom": a.thickness_A, "warp_compatible": True,
                              "ctf_and_dose": not a.no_ctf}}
    if a.workflow == "xml_to_tomograms":
        cfg["reconstruction"]["apply_local_shifts"] = not a.no_local_shifts
    else:
        prior = a.axis_prior
        if prior not in (None, "tomostar"):
            prior = float(prior)
        cfg["alignment"] = {"pixel_spacing": a.align_px, "axis_prior": prior, "flip_hand": a.flip_hand,
                            "write_warp_xml": not a.no_warp_xml}
        cfg["ctf"] = {"enabled": False if a.no_ctf else "auto"}
    import yaml
    text = yaml.safe_dump(cfg, sort_keys=False)
    out = Path(a.out_config).resolve() if a.out_config else root / "config.yaml"
    if forbidden(out.parent):
        sys.exit(f"REFUSING --out-config inside a Warp processing folder: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.read_text() != text:
        sys.exit(f"REFUSING: {out} exists with a DIFFERENT config - use a new --tag (same config = resume)")
    out.write_text(text)
    (root / "slurm").mkdir(parents=True, exist_ok=True)   # job stdout goes here (sbatch needs it to exist)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _tt import repo_path
    repo_path()
    from teamtomo_workflows import load_config
    merged = load_config(out)
    print(f"wrote {out}\n  workflow {merged['workflow']}  output {merged['output']['root']}\n"
          f"  input {merged['input'].get('warp_project') or merged['input'].get('stacks')}  series {merged['input']['series']}")


if __name__ == "__main__":
    main()
