#!/usr/bin/env python3
"""
Pin the CPU frequency on a kernel built WITHOUT CONFIG_CPU_FREQ.

The PREEMPT-RT kernel in use (6.12.79-rt17) has no cpufreq subsystem at all:
/sys/devices/system/cpu/cpu*/cpufreq does not exist, so there is no governor
to set to "performance". Frequency is left entirely to the hardware (Intel
Speed Shift / HWP), which keeps moving it around under load -- exactly the
DVFS noise seen in tasks 0.1-0.3.

This tool talks to the hardware directly through /dev/cpu/N/msr (CONFIG_X86_MSR=m,
module "msr"), which is the only remaining knob:

  IA32_PM_ENABLE       0x770  bit0    -> is HWP active?
  IA32_HWP_CAPABILITIES0x771          -> highest/guaranteed/efficient/lowest ratios
  IA32_HWP_REQUEST     0x774          -> min/max/desired performance + EPP
  IA32_PERF_CTL        0x199          -> legacy ratio request (used if HWP is off)
  IA32_MISC_ENABLE     0x1A0  bit38   -> turbo disable
  MSR_PLATFORM_INFO    0x0CE  [15:8]  -> max non-turbo (base) ratio
  MPERF/APERF          0xE7/0xE8      -> to measure the effective frequency

Usage (needs root):
  sudo ./cpu_freq.py info
  sudo ./cpu_freq.py pin [--ratio N] [--cpus 0,1,2]
  sudo ./cpu_freq.py reset

"pin" with no --ratio uses the guaranteed (base) ratio: the highest frequency
the part can hold indefinitely without thermal throttling, which is what makes
a WCET measurement reproducible. Turbo is disabled.

State for "reset" is saved in /run/rtsia-freq-backup.json (tmpfs: MSRs go back
to their power-on values on reboot anyway).
"""
import json
import os
import struct
import sys
import time

MSR_PLATFORM_INFO = 0x0CE
IA32_MPERF        = 0x0E7
IA32_APERF        = 0x0E8
IA32_PERF_STATUS  = 0x198
IA32_PERF_CTL     = 0x199
IA32_MISC_ENABLE  = 0x1A0
IA32_PM_ENABLE    = 0x770
IA32_HWP_CAPS     = 0x771
IA32_HWP_REQUEST  = 0x774

BACKUP = "/run/rtsia-freq-backup.json"
TURBO_DISABLE_BIT = 38


def online_cpus():
    cpus = []
    for entry in sorted(os.listdir("/sys/devices/system/cpu")):
        if entry.startswith("cpu") and entry[3:].isdigit():
            cpus.append(int(entry[3:]))
    return sorted(cpus)


def rd(cpu, msr):
    with open(f"/dev/cpu/{cpu}/msr", "rb") as f:
        f.seek(msr)
        return struct.unpack("<Q", f.read(8))[0]


def wr(cpu, msr, val):
    with open(f"/dev/cpu/{cpu}/msr", "wb") as f:
        f.seek(msr)
        f.write(struct.pack("<Q", val))


def require_root_and_msr():
    if os.geteuid() != 0:
        sys.exit("Run as root (sudo).")
    if not os.path.exists("/dev/cpu/0/msr"):
        sys.exit("/dev/cpu/0/msr missing: run 'sudo modprobe msr' first.")


def decode_caps(v):
    return dict(highest=v & 0xFF, guaranteed=(v >> 8) & 0xFF,
                efficient=(v >> 16) & 0xFF, lowest=(v >> 24) & 0xFF)


def decode_req(v):
    return dict(minimum=v & 0xFF, maximum=(v >> 8) & 0xFF,
                desired=(v >> 16) & 0xFF, epp=(v >> 24) & 0xFF)


def effective_mhz(cpu, window=0.3, load=True):
    """Measured average frequency over `window` seconds, via APERF/MPERF.

    APERF/MPERF only tick while the core is in C0, so an idle core gives a
    meaningless ratio. With load=True a child process is pinned to `cpu` and
    spins for the whole window, which is what we actually care about: the
    frequency the core runs at *while doing work*.
    """
    base = ((rd(cpu, MSR_PLATFORM_INFO) >> 8) & 0xFF) * 100
    pid = None
    if load:
        pid = os.fork()
        if pid == 0:
            try:
                os.sched_setaffinity(0, {cpu})
                end = time.time() + window + 0.15
                x = 0
                while time.time() < end:
                    for _ in range(20000):
                        x += 1
            finally:
                os._exit(0)
        time.sleep(0.05)
    m0, a0 = rd(cpu, IA32_MPERF), rd(cpu, IA32_APERF)
    time.sleep(window)
    m1, a1 = rd(cpu, IA32_MPERF), rd(cpu, IA32_APERF)
    if pid:
        os.waitpid(pid, 0)
    dm, da = (m1 - m0) & (2**64 - 1), (a1 - a0) & (2**64 - 1)
    return base * da / dm if dm else 0.0


def cmd_info(cpus):
    pi = rd(0, MSR_PLATFORM_INFO)
    base_ratio = (pi >> 8) & 0xFF
    hwp_on = rd(0, IA32_PM_ENABLE) & 1
    misc = rd(0, IA32_MISC_ENABLE)

    turbo_off = (misc >> TURBO_DISABLE_BIT) & 1
    eist = (misc >> 16) & 1
    print(f"raw: PLATFORM_INFO=0x{pi:016x}  MISC_ENABLE=0x{misc:016x}  "
          f"PM_ENABLE=0x{rd(0, IA32_PM_ENABLE):x}  TURBO_RATIO_LIMIT=0x{rd(0, 0x1AD):016x}")
    trl = rd(0, 0x1AD)
    print(f"base (max non-turbo) ratio : {base_ratio}  ->  {base_ratio * 100} MHz")
    print(f"turbo ratio limit (1c..4c) : "
          f"{[(trl >> (8 * i)) & 0xFF for i in range(4)][::-1]}")
    print(f"HWP (Speed Shift) enabled  : {'yes' if hwp_on else 'no'}")
    print(f"turbo disabled             : {'yes' if turbo_off else 'no'}")
    if not hwp_on:
        print(f"EIST (SpeedStep) enabled   : {'yes' if eist else 'no'}"
              f"{'' if eist else '   <- PERF_CTL is ignored, core runs at base ratio'}")
    if hwp_on:
        c = decode_caps(rd(0, IA32_HWP_CAPS))
        print(f"HWP capabilities           : highest={c['highest']} guaranteed={c['guaranteed']} "
              f"efficient={c['efficient']} lowest={c['lowest']}")
    print()
    print(f"{'cpu':>4} {'hwp min/max/des/epp':>22} {'perf_ctl':>9} {'under load':>13}")
    for c in cpus:
        req = decode_req(rd(c, IA32_HWP_REQUEST)) if hwp_on else None

        reqs = (f"{req['minimum']}/{req['maximum']}/{req['desired']}/0x{req['epp']:02x}"
                if req else "-")
        pctl = (rd(c, IA32_PERF_CTL) >> 8) & 0xFF
        print(f"{c:>4} {reqs:>22} {pctl:>9} {effective_mhz(c):>9.0f} MHz")


def cmd_pin(cpus, ratio):
    print("=== before ===")
    cmd_info(cpus)
    print()
    hwp_on = rd(0, IA32_PM_ENABLE) & 1
    if ratio is None:
        if hwp_on:
            ratio = decode_caps(rd(0, IA32_HWP_CAPS))["guaranteed"]
        else:
            ratio = (rd(0, MSR_PLATFORM_INFO) >> 8) & 0xFF
    backup = {"hwp_on": bool(hwp_on), "cpus": {}}
    for c in cpus:
        entry = {"perf_ctl": rd(c, IA32_PERF_CTL),
                 "misc_enable": rd(c, IA32_MISC_ENABLE)}
        if hwp_on:
            entry["hwp_request"] = rd(c, IA32_HWP_REQUEST)
        backup["cpus"][str(c)] = entry
    with open(BACKUP, "w") as f:
        json.dump(backup, f)

    warned = False
    for c in cpus:
        # turbo off: one frequency, no opportunistic boost
        misc = rd(c, IA32_MISC_ENABLE) | (1 << TURBO_DISABLE_BIT)
        try:
            wr(c, IA32_MISC_ENABLE, misc)
        except OSError as e:
            if not warned:
                print(f"note: cannot set the turbo-disable bit ({e}); "
                      f"HWP maximum={ratio} still caps the frequency.")
                warned = True
        if hwp_on:
            # min = max = desired = ratio, EPP = 0 (performance): no autonomous choice left
            v = (ratio & 0xFF) | ((ratio & 0xFF) << 8) | ((ratio & 0xFF) << 16) | (0 << 24)
            wr(c, IA32_HWP_REQUEST, v)
        else:
            wr(c, IA32_PERF_CTL, (ratio & 0xFF) << 8)
    print(f"[freq] pinned {len(cpus)} cpus at ratio {ratio} (~{ratio * 100} MHz), turbo off.")
    print(f"[freq] backup written to {BACKUP}")
    print()
    print("=== after ===")
    cmd_info(cpus)


def cmd_reset(cpus):
    if not os.path.exists(BACKUP):
        sys.exit(f"No {BACKUP}: nothing to restore (MSRs reset on reboot anyway).")
    with open(BACKUP) as f:
        backup = json.load(f)
    for c_str, vals in backup["cpus"].items():
        c = int(c_str)
        try:
            wr(c, IA32_MISC_ENABLE, vals["misc_enable"])
        except OSError:
            pass
        if backup["hwp_on"] and "hwp_request" in vals:
            wr(c, IA32_HWP_REQUEST, vals["hwp_request"])
        else:
            wr(c, IA32_PERF_CTL, vals["perf_ctl"])
    os.remove(BACKUP)
    print(f"[freq] restored {len(backup['cpus'])} cpus from backup.")


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("info", "pin", "reset"):
        sys.exit(__doc__)
    cmd = args[0]
    ratio = None
    cpus = online_cpus()
    i = 1
    while i < len(args):
        if args[i] == "--ratio":
            ratio = int(args[i + 1]); i += 2
        elif args[i] == "--cpus":
            cpus = [int(x) for x in args[i + 1].split(",")]; i += 2
        else:
            sys.exit(f"unknown argument: {args[i]}")
    require_root_and_msr()
    {"info": lambda: cmd_info(cpus),
     "pin": lambda: cmd_pin(cpus, ratio),
     "reset": lambda: cmd_reset(cpus)}[cmd]()


if __name__ == "__main__":
    main()
