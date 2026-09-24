#!/usr/bin/env python3
"""Derive the Section 6.4 A/B macros from the two committed authmode runs.

    python3 analysis/make_ab_macros.py > paper/ab_macros.tex

Arms:
  INSITU-AB-authmode-jwt   service-a validates the token   (validation enabled)
  INSITU-AB-authmode-none  no validation                   (validation disabled)

Both are open-loop k6 steps at one target rate against the same images. Every
value below is read from a committed file; none is typed. Each emitted macro
carries the file it came from, matching the convention in keypath_macros.tex.

Two quantities are reported because they answer different questions:

  * http_req_duration  -- client-observed wall clock, which cannot separate
    executing from waiting;
  * cpu_app_millicores -- CPU actually consumed by the application container,
    which can. A request that waits accrues no CPU.

cpu_sidecar_millicores and eventloop_lag_p99_ms are emitted as controls: if the
difference were mesh work or event-loop saturation rather than validation, they
would move with it.
"""
import csv, json, pathlib, re, sys

ART = pathlib.Path(__file__).resolve().parents[1]
RUNS = ART / "data" / "runs"
ARMS = {"Enabled": "INSITU-AB-authmode-jwt", "Disabled": "INSITU-AB-authmode-none"}


def load(arm_dir):
    d = RUNS / arm_dir
    with open(d / "openloop_ramp.csv", newline="") as fh:
        row = next(iter(csv.DictReader(fh)))
    meta = json.loads((d / "run_metadata.json").read_text())
    up = meta["host"]["uptime_at_run_start"]
    m = re.search(r"load averages?:\s*([0-9.]+)", up)
    rps = float(row["achieved_rps"])
    cpu_app = float(row["cpu_app_millicores"])
    return {
        "dir": arm_dir,
        "scenario": row["scenario"],
        "rps": rps,
        "wall_ms": float(row["latency_mean_ms"]),
        "p99_ms": float(row["latency_p99_ms"]),
        "cpu_app_mc": cpu_app,
        "cpu_side_mc": float(row["cpu_sidecar_millicores"]),
        "loop_lag_ms": float(row["eventloop_lag_p99_ms"]),
        # millicores are milli-core-seconds per second; divide by req/s for
        # core-seconds per request, then to microseconds.
        "cpu_us_per_req": (cpu_app / 1000.0) / rps * 1e6,
        "load1": float(m.group(1)) if m else None,
        "reqs": int(json.loads((d / "k6_summary.json").read_text())
                    ["metrics"]["http_reqs"]["values"]["count"]),
        "node": meta.get("node_version"),
        "started": meta.get("started_at_utc"),
    }


def main():
    a = {k: load(v) for k, v in ARMS.items()}
    on, off = a["Enabled"], a["Disabled"]

    if abs(on["rps"] - off["rps"]) / on["rps"] > 0.01:
        print("WARNING: arms differ in achieved rate", file=sys.stderr)

    d_wall = on["wall_ms"] - off["wall_ms"]
    d_cpu = on["cpu_us_per_req"] - off["cpu_us_per_req"]
    d_side = on["cpu_side_mc"] - off["cpu_side_mc"]
    src = "data/runs/{}/openloop_ramp.csv + run_metadata.json"

    def emit(name, val, arm):
        print(f"\\newcommand{{\\{name}}}{{{val}}}% " + src.format(a[arm]["dir"]))

    emit("ABRate", f"{on['rps']:.0f}", "Enabled")
    emit("ABReqs", f"{on['reqs']:,}".replace(",", r"\,"), "Enabled")
    for arm in ("Enabled", "Disabled"):
        emit(f"AB{arm}Wall", f"{a[arm]['wall_ms']:.4f}", arm)
        emit(f"AB{arm}WallPNine", f"{a[arm]['p99_ms']:.3f}", arm)
        emit(f"AB{arm}CpuMc", f"{a[arm]['cpu_app_mc']:.3f}", arm)
        emit(f"AB{arm}CpuUs", f"{a[arm]['cpu_us_per_req']:.1f}", arm)
        emit(f"AB{arm}SideMc", f"{a[arm]['cpu_side_mc']:.3f}", arm)
        emit(f"AB{arm}LoopLag", f"{a[arm]['loop_lag_ms']:.3f}", arm)
        emit(f"AB{arm}Load", f"{a[arm]['load1']:.2f}", arm)
    emit("ABDeltaWall", f"{d_wall:.4f}", "Enabled")
    emit("ABDeltaCpuUs", f"{d_cpu:.1f}", "Enabled")
    emit("ABDeltaCpuPct", f"{100*d_cpu/on['cpu_us_per_req']:.1f}", "Enabled")
    emit("ABDeltaWallPct", f"{100*d_wall/on['wall_ms']:.1f}", "Enabled")
    emit("ABDeltaSideMc", f"{d_side:+.3f}", "Enabled")
    emit("ABLoadRatio", f"{on['load1']/off['load1']:.2f}", "Enabled")

    print("%% arms:", json.dumps({k: {kk: vv for kk, vv in v.items()
                                      if kk in ("dir", "scenario", "started", "node")}
                                  for k, v in a.items()}), file=sys.stderr)


if __name__ == "__main__":
    main()
