#!/bin/bash
P=/home/fabio/Scrivania/OTel-capabilities-for-mixed-criticality-workloads
echo "############ A. chi e' rimasto nel cpuset root (188 task) ############"
head -5 /cpusets/tasks | while read t; do echo "  pid $t -> $(cat /proc/$t/comm 2>/dev/null)  affinity=$(taskset -cp $t 2>/dev/null | sed 's/.*: //')"; done
echo "  totale in root: $(wc -l < /cpusets/tasks)"
echo "  di cui kthread: $(while read t; do [ -e /proc/$t/exe ] || echo x; done < /cpusets/tasks | wc -l)"
echo "  cpus del cpuset root: $(cat /cpusets/cpuset.cpus 2>/dev/null || cat /cpusets/cpus)"
echo
echo "############ B. un processo dentro lo shield e' confinato? ############"
cset shield --exec -- bash -c 'echo "  affinity dentro shield: $(taskset -cp $$ | sed "s/.*: //")"; echo "  psr: $(ps -o psr= -p $$)"' 2>&1 | grep -v '^cset: --> last message'
echo
echo "############ C. il loop IRQ dello script: funziona o fallisce in silenzio? ############"
IRQ=$(ls -d /proc/irq/[0-9]* | head -1 | xargs basename)
echo "  provo a scrivere '0,1,4,5,6,7' su /proc/irq/$IRQ/smp_affinity_list (quello che fa lo script con ISO=2,3)"
echo "0,1,4,5,6,7" > /proc/irq/$IRQ/smp_affinity_list
echo "  exit=$?   valore riletto: $(cat /proc/irq/$IRQ/smp_affinity_list)"
echo "  provo con '0,1,4,5' (corretto per il nostro isolcpus)"
echo "0,1,4,5" > /proc/irq/$IRQ/smp_affinity_list
echo "  exit=$?   valore riletto: $(cat /proc/irq/$IRQ/smp_affinity_list)"
echo
echo "############ D. reset_isolation.sh ############"
bash $P/scripts/utils_isolation/reset_isolation.sh 2>&1
echo "--- exit=$? ---"
cset set --list 2>&1 | head -10
echo "  mount cpuset dopo reset: $(mount | grep -c cpuset) righe"
echo "  IRQ dopo reset: $(for f in /proc/irq/*/smp_affinity_list; do cat $f; done | sort | uniq -c | tr '\n' ' ')"
