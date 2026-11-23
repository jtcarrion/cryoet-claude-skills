#!/usr/bin/env python3
"""setup_config.py -- write the cryoet-skills config from detected values + the user's answers (stdlib, Python 3.6+).

    python3 setup_config.py --detect                         # show what detection proposes (no write)
    python3 setup_config.py --detect --set SLURM_GPU_PARTITION=gpu --set WARP_ENV_SCRIPT=/opt/warp/env.sh
    python3 setup_config.py --answers answers.json [--detect] [--out PATH] [--write]

* Starts from the existing config if there is one (so re-running only changes what you pass), else the template.
* --detect fills keys that are still empty with detect_env.py's proposals (never overwrites a value you set).
* --set KEY=VALUE / --answers {"KEY": "VALUE", ...} apply the user's answers (unknown keys are refused).
* Without --write it prints the diff and stops; with --write it backs up the old file (config.sh.bak-<time>) first.
Comments and key order of the template are preserved, so the file stays self-documenting.
"""
import argparse, datetime, difflib, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "config.template.sh")
DEFAULT_OUT = os.environ.get("CRYOET_SKILLS_CONFIG") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "cryoet-skills", "config.sh")
LINE = re.compile(r'^([A-Z][A-Z0-9_]*)="(.*?)"(.*)$')


def read_values(path):
    vals = {}
    for line in open(path):
        m = LINE.match(line.rstrip("\n"))
        if m:
            vals[m.group(1)] = m.group(2)
    return vals


def render(values):
    out = []
    for line in open(TEMPLATE):
        m = LINE.match(line.rstrip("\n"))
        if m and m.group(1) in values:
            v = values[m.group(1)].replace('"', '\\"')
            line = '%s="%s"%s\n' % (m.group(1), v, m.group(3))
        out.append(line)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--detect", action="store_true", help="fill empty keys from detect_env.py proposals")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--answers", help="JSON file {KEY: VALUE}")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    known = read_values(TEMPLATE)
    base = read_values(a.out) if os.path.isfile(a.out) else dict(known)
    vals = dict(known); vals.update({k: v for k, v in base.items() if k in known})
    src = {}
    if a.detect:
        sys.path.insert(0, HERE)
        import detect_env as de
        f = {"slurm": de.slurm(), "tools": de.tools(), "conda_envs": de.conda_envs()}
        f["python"], f["python_version"] = de.good_python(f["conda_envs"])
        for k, v in de.propose(f).items():
            if v and not vals.get(k) and k in known:
                vals[k] = v; src[k] = "detected"
    answers = {}
    if a.answers:
        answers.update(json.load(open(a.answers)))
    for kv in a.set:
        if "=" not in kv:
            sys.exit("--set needs KEY=VALUE, got %r" % kv)
        k, v = kv.split("=", 1); answers[k] = v
    bad = [k for k in answers if k not in known]
    if bad:
        sys.exit("unknown config key(s): %s (see %s)" % (", ".join(bad), TEMPLATE))
    for k, v in answers.items():
        vals[k] = str(v); src[k] = "user"

    new = render(vals)
    old = open(a.out).read() if os.path.isfile(a.out) else ""
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), a.out + " (current)", a.out + " (new)", lineterm="", n=0))
    print("\n".join(diff) if diff else "no changes")
    if src:
        print("\nsources: " + ", ".join("%s=%s" % (k, s) for k, s in sorted(src.items())))
    if not a.write:
        print("\n(dry run - re-run with --write to save)"); return 0
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if old:
        bak = a.out + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(a.out, bak); print("backup:", bak)
    with open(a.out, "w") as fh:
        fh.write(new)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
