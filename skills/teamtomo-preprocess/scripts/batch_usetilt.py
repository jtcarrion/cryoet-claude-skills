#!/usr/bin/env python3
"""Drop-in for teamtomo-workflows batch.py (same arguments) that also handles DESELECTED TILTS (UseTilt=False).

Upstream bug (teamtomo-workflows commit caf1f46): xml_to_tomograms loads one image per movie in the XML (all tilts)
and the XML's dose / GridCTF defocus for all tilts, but torch_tilt_series.from_warp_xml keeps only UseTilt=True tilts
(ts.image_indices). Any series with a deselected tilt then fails with
  "The size of tensor a (N_used) must match the size of tensor b (N_all) at non-singleton dimension 0"
This wrapper selects images, dose and defocus with ts.image_indices before reconstructing - what WarpTools
ts_reconstruct does (it skips UseTilt=False tilts). Series with every tilt enabled are untouched (identity), and the
repo is not modified (the patch lives only in this process).

It patches the repo's PRIVATE function teamtomo_workflows.workflows._reconstruct. If that function is missing or its
signature changed, this script STOPS with an explanation instead of silently running unpatched: then either the repo
fixed the bug (run with PLAIN_BATCH=1 / the repo's batch.py) or this wrapper needs updating.
Remove this wrapper once the repo selects by image_indices itself.

  python batch_usetilt.py --config <config.yaml> [--series ...] [--overwrite] [--device cuda:0] [--stop_on_error]
"""
import argparse
import inspect
import os
import sys

EXPECTED = ["cfg", "s", "ts", "images", "px_img", "vol_dims", "dose", "defocus"]


def install_patch(WF, np):
    orig = getattr(WF, "_reconstruct", None)
    if orig is None or not callable(orig):
        sys.exit("batch_usetilt: teamtomo_workflows.workflows._reconstruct not found - the repo changed. If it now "
                 "handles UseTilt=False itself, run with PLAIN_BATCH=1; otherwise update batch_usetilt.py.")
    params = list(inspect.signature(orig).parameters)
    if params != EXPECTED:
        sys.exit(f"batch_usetilt: _reconstruct signature is {params}, expected {EXPECTED} - the repo changed. "
                 "Check whether it selects UseTilt tilts itself (then PLAIN_BATCH=1), else update this wrapper.")

    def _reconstruct_selected(cfg, s, ts, images, px_img, vol_dims, dose, defocus):
        idx = getattr(ts, "image_indices", None)
        n = len(ts.tilt_angles)
        if idx is not None and images.shape[0] != n:
            idx = np.asarray(idx.cpu() if hasattr(idx, "cpu") else idx, dtype=np.int64)
            if len(idx) != n or idx.max() >= images.shape[0]:
                raise ValueError(f"{s.name}: cannot select tilts ({images.shape[0]} images, {n} geometry tilts)")
            print(f"[batch_usetilt] {s.name}: {images.shape[0]} images -> {n} UseTilt=True tilts", flush=True)
            images = images[idx]
            dose = None if dose is None else np.asarray(dose)[idx]
            defocus = None if defocus is None else np.asarray(defocus)[idx]
        return orig(cfg, s, ts, images, px_img, vol_dims, dose, defocus)

    WF._reconstruct = _reconstruct_selected


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True); ap.add_argument("--series", nargs="+", default=None)
    ap.add_argument("--overwrite", action="store_true"); ap.add_argument("--device", default=None)
    ap.add_argument("--stop_on_error", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _tt import repo_path
    repo_path()
    import numpy as np
    from teamtomo_workflows import load_config, run_batch
    from teamtomo_workflows import workflows as WF
    install_patch(WF, np)

    ov = {}
    if a.series:
        ov.setdefault("input", {})["series"] = a.series
    if a.overwrite:
        ov.setdefault("output", {})["overwrite"] = True
    if a.device:
        ov["compute"] = {"device": a.device}
    cfg = load_config(a.config, ov)
    rows = run_batch(cfg, stop_on_error=a.stop_on_error)
    for r in rows:
        print(f"{r['series']:>12s}  {r['status']:<16s} {r.get('total_s') or '':>6}  {r.get('error', '')}")
    print(f"-> {cfg['output']['root']}")
    sys.exit(1 if any(r["status"] == "failed" for r in rows) else 0)


if __name__ == "__main__":
    main()
