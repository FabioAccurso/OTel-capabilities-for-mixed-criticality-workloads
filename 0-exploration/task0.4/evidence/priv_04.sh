#!/bin/bash
P=/home/fabio/Scrivania/OTel-capabilities-for-mixed-criticality-workloads
echo "################ 1. pin frequenza (il reboot lo ha azzerato) ################"
/usr/bin/python3 $P/scripts/utils_freq/cpu_freq.py pin 2>&1 | tail -20
echo
echo "################ 2. isolate_cpus.sh 2,3 ################"
bash $P/scripts/utils_isolation/isolate_cpus.sh 2,3 2>&1
echo "--- exit code = $? ---"
echo
echo "################ 3. stato cset dopo ################"
cset shield --shield 2>&1 | head -20
echo "--- exit=$? ---"
cset set --list 2>&1 | head -20
echo
echo "################ 4. cosa ha mosso cset nel filesystem ################"
ls -d /cpusets /sys/fs/cgroup/cpuset 2>&1
mount | grep -i cpuset || echo "  nessun filesystem cpuset montato"
echo
echo "################ 5. IRQ affinity dopo ################"
for f in /proc/irq/*/smp_affinity_list; do cat $f 2>/dev/null; done | sort | uniq -c
