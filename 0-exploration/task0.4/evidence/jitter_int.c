/* Misura N volte la durata di una quantita' FISSA di lavoro CPU-bound.
   Proxy di WCET: quello che conta e' il massimo, non la media. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#define N 2000
#define LOOPS 60000
static volatile double sink;
static void work(void){ long r=1; for(long i=0;i<LOOPS;i++) r=(r*1103515245L+12345L)&0x7fffffff; sink=(double)r; }
static int cmp(const void*a,const void*b){ long x=*(long*)a,y=*(long*)b; return (x>y)-(x<y); }
int main(void){
    static long d[N]; struct timespec a,b;
    work(); /* warm-up */
    for(int i=0;i<N;i++){
        clock_gettime(CLOCK_MONOTONIC,&a); work(); clock_gettime(CLOCK_MONOTONIC,&b);
        d[i]=(b.tv_sec-a.tv_sec)*1000000000L+(b.tv_nsec-a.tv_nsec);
    }
    qsort(d,N,sizeof(long),cmp);
    printf("min %7.1f us | med %7.1f us | p99 %7.1f us | MAX %8.1f us | max/med %5.2fx\n",
           d[0]/1000.0, d[N/2]/1000.0, d[(int)(N*0.99)]/1000.0, d[N-1]/1000.0,
           (double)d[N-1]/d[N/2]);
    return 0;
}
