import os, struct, time, sys
def rd(cpu, msr):
    with open("/dev/cpu/%d/msr"%cpu, "rb") as f:
        f.seek(msr); return struct.unpack("<Q", f.read(8))[0]
BASE = ((rd(0,0xCE) >> 8) & 0xFF) * 100.0
def eff(cpu, win=2.0):
    m0, a0 = rd(cpu,0xE7), rd(cpu,0xE8)
    time.sleep(win)
    m1, a1 = rd(cpu,0xE7), rd(cpu,0xE8)
    dm, da = m1-m0, a1-a0
    return BASE * da / dm if dm else 0
print("  base ratio -> %.0f MHz" % BASE)
for cpu in [int(x) for x in sys.argv[1:]]:
    print("  cpu%d effettiva: %7.1f MHz" % (cpu, eff(cpu)))
