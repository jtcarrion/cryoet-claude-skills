#!/usr/bin/env python3
"""Static checks for the cryoet-skills repo (python 3.6+, stdlib only).  Usage: tools/lint.py [--strict]
 1. no site/user-specific values in shipped files (paths, usernames, partitions, typed gres, node names)
 2. vendored scripts/_lib/* identical to lib/*
 3. every .py compiles; every .sh/.sbatch passes `bash -n`
 4. SKILL.md frontmatter: name == dir, description <= 1536 chars; body < 500 lines
 5. no `~/.claude/skills/` paths (use ${CLAUDE_SKILL_DIR}); no cross-skill ../<other-skill> imports
Exit 1 on any error. Warnings (EMPIAR ids outside references/) are informational unless --strict."""
import os, re, subprocess, sys, filecmp, py_compile, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "audit", "local", "results", "__pycache__"}
SITE = [  # (regex, why) - generic checks; add your own site/lab names in local/private_patterns.txt (git-ignored)
    (r"/home/[a-z][a-z0-9_]+/|/net/|/nfs/", "absolute site path"),
    (r"\bnode\d{3,4}\b", "node name"),
    (r"gpu:(a100|l40s|h100|h200|b200|v100|a40|rtx\w*):\d", "typed gres (use cryoet_gres)"),
    (r"^#SBATCH\s+--(partition|gres|account|qos|nodelist|exclude)\b", "site #SBATCH line (pass via cryoet_submit)"),
    (r"conda_envs/", "site environment path"),
    (r"~/\.claude/skills/|\$HOME/\.claude/skills/", "hardcoded skill dir (use ${CLAUDE_SKILL_DIR})"),
]
_PRIV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local", "private_patterns.txt")
if os.path.isfile(_PRIV):  # one regex per line, optional "  # why"
    for _l in open(_PRIV):
        _l = _l.strip()
        if _l and not _l.startswith("#"):
            _rx, _, _why = _l.partition("  # ")
            SITE.append((_rx.strip(), _why.strip() or "private pattern (local/private_patterns.txt)"))
WARN = [(r"EMPIAR-?10499|EMD-?11650|TS_00\d{3}", "dataset-specific id outside references/")]
LIB = sorted(f for f in os.listdir(os.path.join(ROOT, "lib")) if not f.startswith((".", "__")))

def files():
    for d, sub, fs in os.walk(ROOT):
        sub[:] = [s for s in sub if s not in SKIP_DIRS]
        for f in fs:
            yield os.path.join(d, f)

def rel(p): return os.path.relpath(p, ROOT)

def main():
    strict = "--strict" in sys.argv
    err, warn = [], []
    for p in files():
        r = rel(p)
        if r.startswith(("tools/lint.py", "LICENSE")) or not re.search(r"\.(md|py|sh|sbatch|json|yaml|yml|txt|cxc|conf)$", p):
            continue
        try:
            lines = open(p, encoding="utf-8").read().splitlines()
        except UnicodeDecodeError:
            err.append("%s: not UTF-8" % r); continue
        in_ref = "/references/" in r or r.startswith("docs/")
        for i, ln in enumerate(lines, 1):
            if "lint: allow" in ln:
                continue
            for rx, why in SITE:
                if re.search(rx, ln):
                    err.append("%s:%d: %s: %s" % (r, i, why, ln.strip()[:110]))
            if not in_ref and not r.startswith("evals/"):
                for rx, why in WARN:
                    if re.search(rx, ln):
                        warn.append("%s:%d: %s" % (r, i, why))
        if p.endswith(".py"):
            try:
                py_compile.compile(p, cfile=os.path.join(tempfile.gettempdir(), "lint_%d.pyc" % os.getpid()), doraise=True)
            except py_compile.PyCompileError as e:
                err.append("%s: python syntax: %s" % (r, str(e).splitlines()[-1]))
        if re.search(r"\.(sh|sbatch)$", p) and subprocess.call(["bash", "-n", p], stderr=subprocess.DEVNULL):
            err.append("%s: bash -n failed" % r)
    sk = os.path.join(ROOT, "skills")
    for s in sorted(os.listdir(sk)):
        d = os.path.join(sk, s); md = os.path.join(d, "SKILL.md")
        if not os.path.isfile(md):
            err.append("skills/%s: no SKILL.md" % s); continue
        txt = open(md, encoding="utf-8").read()
        m = re.match(r"---\n(.*?)\n---\n", txt, re.S)
        if not m:
            err.append("skills/%s/SKILL.md: no frontmatter" % s); continue
        fm = m.group(1)
        name = re.search(r"^name:\s*(\S+)", fm, re.M)
        desc = re.search(r"^description:\s*(.+)$", fm, re.M)
        if not name or name.group(1) != s: err.append("skills/%s: frontmatter name != dir" % s)
        if not desc or len(desc.group(1)) > 1536: err.append("skills/%s: description missing or > 1536 chars" % s)
        if txt.count("\n") >= 500: err.append("skills/%s/SKILL.md: >= 500 lines" % s)
        if os.path.isdir(os.path.join(d, "scripts")):
            for f in LIB:
                v = os.path.join(d, "scripts", "_lib", f)
                if not os.path.isfile(v) or not filecmp.cmp(v, os.path.join(ROOT, "lib", f), shallow=False):
                    err.append("skills/%s/scripts/_lib/%s: missing or differs from lib/ (run tools/sync_lib.sh)" % (s, f))
        for p in files():
            if p.startswith(d + os.sep) and p.endswith((".py", ".sh", ".sbatch", ".md")):
                for i, ln in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                    for o in os.listdir(sk):
                        if o != s and re.search(r"(\.\./|skills/)%s/scripts" % re.escape(o), ln):
                            err.append("%s:%d: reaches into skill %s (vendor instead)" % (rel(p), i, o))
    for e in err: print("ERROR  " + e)
    for w in warn: print("warn   " + w)
    print("\n%d error(s), %d warning(s)" % (len(err), len(warn)))
    return 1 if err or (strict and warn) else 0

if __name__ == "__main__":
    sys.exit(main())
