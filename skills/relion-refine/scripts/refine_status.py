#!/usr/bin/env python3
"""Status of a RELION 5 auto-refine job directory (for monitoring), or posterior stats of one data STAR.

  "$CRYOET_PYTHON" refine_status.py --jobdir Refine3D/jobNNN [--slurm-job 123456 | local:PID] [--input-n N]
                                    [--stall-min 90]
  "$CRYOET_PYTHON" refine_status.py --posteriors run_it001_data.star [--label TAG]

Per iteration: finish time, minutes since previous, _rlnCurrentResolution (half1 model), changes in orientations /
offsets, converged flag. Then: posteriors of the newest data STAR (median MaxValueProb / NrOfSignificantSamples),
fatal patterns in the job's logs, the success marker, final particle count vs input, and Slurm state.
Verdicts it prints and what they mean:
  FLAT POSTERIORS  median significant samples > 200 or maxprob < 0.02 at iteration 1 -> greyscale/reference problem
                   (--firstiter_cc), not I/O
  OSCILLATING      changes in orientations went UP twice in the last 4 iterations while resolution is flat ->
                   oversized mask or missing --solvent_correct_fsc
  STALLED          no new iteration for > max(--stall-min, 2.5 x the slowest recent iteration) while the job is
                   RUNNING. --stall-min defaults to $STALL_MIN or 90: pass the same value the refine3d.sbatch job got
  CRASHED          fatal pattern in a log (KERNEL_ERROR, illegal memory access, Segmentation fault, MPI_ABORT,
                   error-code 700, Aborted, core dumped, srun: error, CUFFT_ALLOC_FAILED)
  DONE             RELION_JOB_EXIT_SUCCESS present (authoritative; sacct may say FAILED after a teardown crash)
"""
import argparse, glob, os, re, shutil, statistics, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite

FATAL = re.compile(r"KERNEL_ERROR|illegal memory access|Segmentation fault|MPI_ABORT|error-code 700|Aborted|core dumped|"
                   r"srun: error|CUFFT_ALLOC_FAILED", re.I)


def kv(path):
    out = {}
    for l in open(path):
        p = l.split()
        if len(p) >= 2 and p[0].startswith("_rln") and not p[1].startswith("#"):
            out[p[0]] = p[1]
    return out


def posteriors(star, label=""):
    P = starlite.particles(starlite.read(star))
    s = [float(x) for x in P.values("_rlnNrOfSignificantSamples")] if "_rlnNrOfSignificantSamples" in P.cols else []
    m = [float(x) for x in P.values("_rlnMaxValueProbDistribution")] if "_rlnMaxValueProbDistribution" in P.cols else []
    if not s or not m:
        print(f"{label} no posterior columns in {star}"); return None
    ss = sorted(s); med_s = statistics.median(s); med_m = statistics.median(m)
    print(f"{label} posteriors n={len(s):,}: significant samples median {med_s:.0f} p90 {ss[int(0.9 * len(ss))]:.0f} "
          f"max {ss[-1]:.0f} | MaxValueProb median {med_m:.3f} mean {statistics.mean(m):.3f}")
    return med_s, med_m


def _run(cmd):   # Python 3.6: no capture_output/text
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                          timeout=30).stdout.strip()


def job_state(job):
    """'RUNNING ...' / 'ended: ...' for a Slurm id, or for 'local:PID' (SCHEDULER=none) from /proc."""
    if job.startswith("local:"):
        pid = job.split(":", 1)[1].split()[0]
        return "RUNNING (local pid %s)" % pid if os.path.exists("/proc/" + pid) else "ended: local pid %s gone" % pid
    if not shutil.which("squeue"):
        return "(no squeue on this machine)"
    try:
        st = _run(["squeue", "-h", "-j", job, "-o", "%T %M %N"])
        if not st and shutil.which("sacct"):
            st = "ended: " + _run(["sacct", "-X", "-n", "-j", job, "-o", "State,Elapsed,ExitCode"])
        return st or "ended: (not in squeue; sacct unavailable)"
    except Exception as e:
        return f"(slurm query failed: {e})"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobdir"); ap.add_argument("--slurm-job"); ap.add_argument("--input-n", type=int)
    ap.add_argument("--posteriors"); ap.add_argument("--label", default="")
    ap.add_argument("--stall-min", type=float, default=float(os.environ.get("STALL_MIN") or 90),
                    help="minimum stall threshold in minutes (match the job's STALL_MIN; default $STALL_MIN or 90)")
    a = ap.parse_args()
    if a.posteriors:
        r = posteriors(a.posteriors, a.label)
        if r and r[0] <= 1 and r[1] >= 0.999:
            print(f"{a.label} VERDICT: CC MODE - every particle has 1 significant sample and MaxValueProb 1.0: this iteration "
                  "ran with --firstiter_cc (hard assignments), so posteriors say NOTHING about the reference. Judge greyscale "
                  "with a benchmark arm WITHOUT --firstiter_cc, or judge the refine from iteration 2.")
        elif r and (r[0] > 200 or r[1] < 0.02):
            print(f"{a.label} VERDICT: FLAT POSTERIORS -> reference greyscale/hand problem; try --firstiter_cc or an own-data reference")
        return
    d = a.jobdir; rows = []
    for opt in sorted(glob.glob(os.path.join(d, "run_it[0-9][0-9][0-9]_optimiser.star"))):
        base = opt[:-len("_optimiser.star")]; o = kv(opt)
        h1 = base + "_half1_model.star"; res = kv(h1).get("_rlnCurrentResolution") if os.path.exists(h1) else None
        rows.append(dict(it=int(o.get("_rlnCurrentIteration", -1)), t=os.path.getmtime(opt), res=float(res) if res else None,
                         ang=float(o.get("_rlnChangesOptimalOrientations", "nan")),
                         off=float(o.get("_rlnChangesOptimalOffsets", "nan")), conv=o.get("_rlnHasConverged", "?"),
                         solv=o.get("_rlnDoSolventFscCorrection", "?"),
                         mask=o.get("_rlnSolventMaskName", "None")))
    print(f"job dir {d}")
    print(f"{'iter':>4} {'finished':>16} {'min':>6} {'res A':>7} {'d_ang':>7} {'d_off':>7} conv")
    prev = None; durs = []
    for r in rows:
        dt = (r["t"] - prev) / 60 if prev else float("nan"); prev = r["t"]
        if dt == dt:
            durs.append(dt)
        print(f"{r['it']:>4} {time.strftime('%m-%d %H:%M', time.localtime(r['t'])):>16} {dt:6.1f} "
              f"{(r['res'] or float('nan')):7.2f} {r['ang']:7.2f} {r['off']:7.2f} {r['conv']}")
    verdicts = []
    if rows and rows[-1]["solv"] == "0" and rows[-1]["mask"] not in ("", "None", "none"):
        verdicts.append("NOTE solvent-corrected FSC is OFF (_rlnDoSolventFscCorrection 0): a solvent mask alone does not "
                        "drive sampling; add --solvent_correct_fsc (allowed on --continue)")
    if len(rows) >= 5:
        ang = [r["ang"] for r in rows[-5:]]
        ups = sum(1 for x, y in zip(ang, ang[1:]) if y > x * 1.05)
        rs = [r["res"] for r in rows[-5:] if r["res"]]
        if ups >= 2 and rs and max(rs) - min(rs) < 0.3 and ang[-1] > 5:
            verdicts.append("OSCILLATING angle changes with flat resolution -> oversized mask / no --solvent_correct_fsc")
    datas = sorted(glob.glob(os.path.join(d, "run_it[0-9][0-9][0-9]_data.star")))
    if datas:
        r = posteriors(datas[-1], os.path.basename(datas[-1]))
        if r and r[0] <= 1 and r[1] >= 0.999:
            verdicts.append("CC MODE posteriors (1 sample, MaxValueProb 1.0) in the newest iteration: --firstiter_cc hard "
                            "assignments are not diagnostic - read posteriors from iteration 2 on")
        elif r and len(datas) <= 2 and (r[0] > 200 or r[1] < 0.02):
            verdicts.append("FLAT POSTERIORS at the start -> reference greyscale/hand problem (--firstiter_cc), not I/O")
    logs = [p for p in glob.glob(os.path.join(d, "*.log")) + glob.glob(os.path.join(d, "*.out")) + glob.glob(os.path.join(d, "*.err"))]
    for lp in logs:
        try:
            txt = open(lp, errors="replace").read()
        except OSError:
            continue
        hits = FATAL.findall(txt)
        if hits:
            verdicts.append(f"CRASHED? fatal pattern(s) {sorted(set(hits))} in {os.path.basename(lp)}")
        fr = re.findall(r"Final resolution.*?([\d.]+)", txt)
        if fr:
            print(f"log {os.path.basename(lp)}: final resolution {fr[-1]} A")
    done = os.path.exists(os.path.join(d, "RELION_JOB_EXIT_SUCCESS"))
    if done:   # RELION often segfaults in MPI teardown AFTER writing the marker: known and harmless
        verdicts = [v.replace("CRASHED? fatal pattern(s)", "teardown crash after success (harmless):") for v in verdicts]
    state = ""
    if a.slurm_job:
        state = job_state(a.slurm_job)
        print(f"job {a.slurm_job}: {state}")
    if done:
        fin = os.path.join(d, "run_data.star")
        if os.path.exists(fin):
            n = len(starlite.particles(starlite.read(fin)).rows)
            msg = f"DONE: RELION_JOB_EXIT_SUCCESS; run_data.star has {n:,} particles"
            if a.input_n is not None and n != a.input_n:
                msg += f"  != input {a.input_n:,}  <- CHECK"
            verdicts.append(msg)
        else:
            verdicts.append("DONE marker but no run_data.star - check outputs")
    elif rows and state.startswith("RUNNING"):
        idle = (time.time() - rows[-1]["t"]) / 60
        lim = max(a.stall_min, 2.5 * max(durs[-3:])) if durs else max(a.stall_min, 180.0)
        print(f"{idle:.0f} min since the last iteration finished (stall threshold {lim:.0f} min)")
        if idle > lim:
            verdicts.append("STALLED: no new iteration past the threshold while RUNNING - check the log, consider scancel + resubmit (auto-continues)")
    for v in verdicts:
        print("VERDICT:", v)
    if not verdicts:
        print("VERDICT: running normally" if rows else "VERDICT: no iterations yet (staging or queued)")


if __name__ == "__main__":
    main()
