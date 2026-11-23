#!/usr/bin/env python3
"""project_state.py -- the per-project handoff record shared by all cryoet-skills stages (stdlib, Python 3.6+).

The record lives at <PROJECT>/cryoet_project.json. Stages read what upstream stages produced and append what they made.
    project_state.py init  PROJECT --dataset NAME [--angpix 1.7 --kv 300 --cs 2.7 --amp 0.07 --dose_per_tilt 3.2]
    project_state.py get   PROJECT [dotted.key]                 # whole record or one value (JSON)
    project_state.py set   PROJECT dotted.key VALUE             # VALUE parsed as JSON if possible, else string
    project_state.py add   PROJECT list.key '{"json": "object"}' # append to a list (e.g. refinements)
    project_state.py check PROJECT                              # verify every recorded path still exists
Writes are atomic (temp file + rename). Keys are free-form; references/handoff.md lists the conventional ones.
"""
import argparse, datetime, json, os, sys, tempfile

def path(proj): return os.path.join(os.path.abspath(proj), "cryoet_project.json")

def load(proj):
    p = path(proj)
    if not os.path.isfile(p):
        sys.exit("no %s -- run: project_state.py init %s --dataset NAME" % (p, proj))
    return json.load(open(p))

def save(proj, d):
    d["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    fd, tmp = tempfile.mkstemp(dir=os.path.abspath(proj), prefix=".cryoet_project.")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, path(proj))

def walk(d, key, create=False):
    parts = key.split(".")
    for k in parts[:-1]:
        if k not in d:
            if not create: raise KeyError(key)
            d[k] = {}
        d = d[k]
    return d, parts[-1]

def val(s):
    try: return json.loads(s)
    except ValueError: return s

def paths_in(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from paths_in(v, prefix + "." + k if prefix else k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from paths_in(v, "%s[%d]" % (prefix, i))
    elif isinstance(o, str) and o.startswith("/") and (prefix.endswith(("dir", "path", "star", "map", "mask", "project")) or "/" in o[1:]):
        yield prefix, o

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd")
    i = sp.add_parser("init"); i.add_argument("project"); i.add_argument("--dataset", required=True)
    for k in ("angpix", "kv", "cs", "amp", "dose_per_tilt"): i.add_argument("--" + k, type=float)
    g = sp.add_parser("get"); g.add_argument("project"); g.add_argument("key", nargs="?")
    s = sp.add_parser("set"); s.add_argument("project"); s.add_argument("key"); s.add_argument("value")
    a_ = sp.add_parser("add"); a_.add_argument("project"); a_.add_argument("key"); a_.add_argument("value")
    c = sp.add_parser("check"); c.add_argument("project")
    a = ap.parse_args()
    if a.cmd == "init":
        if os.path.exists(path(a.project)): sys.exit("%s exists; use set/add" % path(a.project))
        os.makedirs(a.project, exist_ok=True)
        acq = {k: getattr(a, k) for k in ("angpix", "kv", "cs", "amp", "dose_per_tilt") if getattr(a, k) is not None}
        save(a.project, {"schema": 1, "dataset": a.dataset, "project": os.path.abspath(a.project),
                         "acquisition": acq, "stages": {}, "decisions": [], "particle_sets": [], "refinements": [],
                         "maps": []})
        print(path(a.project))
    elif a.cmd == "get":
        d = load(a.project)
        if a.key:
            p, k = walk(d, a.key); d = p[k]
        print(json.dumps(d, indent=1, sort_keys=True))
    elif a.cmd in ("set", "add"):
        d = load(a.project); p, k = walk(d, a.key, create=True)
        if a.cmd == "set": p[k] = val(a.value)
        else: p.setdefault(k, []).append(val(a.value))
        save(a.project, d)
    elif a.cmd == "check":
        bad = [(k, v) for k, v in paths_in(load(a.project)) if not os.path.exists(v)]
        for k, v in bad: print("MISSING %s = %s" % (k, v))
        print("ok" if not bad else "%d missing path(s)" % len(bad)); return 1 if bad else 0
    else:
        ap.print_help(); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
