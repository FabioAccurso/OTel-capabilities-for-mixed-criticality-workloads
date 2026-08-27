#!/usr/bin/env python3
"""
Generate an rt-app mixed-criticality task-set JSON config.

- HI_task: SCHED_FIFO, prio 90, period ~10ms (2ms run + 8ms sleep) -> the
  critical task whose WCET/jitter/deadline-miss we track as response variable.
- LO_noise: SCHED_OTHER, period ~1ms (0.5ms run + 0.5ms sleep), replicated
  N times via "instance" -> best-effort background load that also generates
  OTel telemetry, used to stress the exporter/sampler/processor.

Usage:
  ./gen_config.py --n-lo 4 --duration 20 --out cfg_n4.json
  ./gen_config.py --n-lo 0 --duration 20 --out cfg_hi_only.json   # Block 1
"""
import argparse
import json


def build_config(n_lo, duration, hi_cpu, lo_cpus):
    tasks = {
        "HI_task": {
            "policy": "SCHED_FIFO",
            "priority": 90,
            "cpus": [hi_cpu],
            "loop": -1,
            "run": 2000,
            "sleep": 8000,
        }
    }
    if n_lo > 0:
        tasks["LO_noise"] = {
            "instance": n_lo,
            "policy": "SCHED_OTHER",
            "cpus": lo_cpus,
            "loop": -1,
            "run": 500,
            "sleep": 500,
        }
    return {
        "tasks": tasks,
        "global": {
            "duration": duration,
            "default_policy": "SCHED_OTHER",
            "calibration": "CPU0",
            "logdir": "./",
            "log_basename": "rtapp",
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-lo", type=int, default=0, help="number of LO_noise instances")
    ap.add_argument("--duration", type=int, default=20, help="run duration in seconds")
    ap.add_argument("--hi-cpu", type=int, default=2, help="CPU pinned for HI_task")
    ap.add_argument("--lo-cpus", type=int, nargs="+", default=[3],
                     help="CPU(s) for LO_noise instances")
    ap.add_argument("--out", required=True, help="output JSON path")
    args = ap.parse_args()

    cfg = build_config(args.n_lo, args.duration, args.hi_cpu, args.lo_cpus)
    with open(args.out, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"wrote {args.out}  (n_lo={args.n_lo}, duration={args.duration}s)")
