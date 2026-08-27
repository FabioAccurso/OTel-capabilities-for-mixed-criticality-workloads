#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#define N 2000
#define LOOPS 15000
static volatile double sink;
/* copia fedele del corpo di waste_cpu_cycles() di rt-app */
static void work(void){
    double param=0.95, result, n=4;
    for(long i=0;i<LOOPS;i++){
        result = ldexp(param, (ldexp(param, ldexp(param, n))));
        result = ldexp(param, (ldexp(param, ldexp(param, n))));
        result = ldexp(param, (ldexp(param, ldexp(param, n))));
        result = ldexp(param, (ldexp(param, ldexp(param, n))));
    }
    sink=result;
}
static int cmp(const void*a,const void*b){ long x=*(long*)a,y=*(long*)b; return (x>y)-(x<y); }
int main(void){
    static long d[N]; struct timespec a,b; work();
    for(int i=0;i<N;i++){ clock_gettime(CLOCK_MONOTONIC,&a); work(); clock_gettime(CLOCK_MONOTONIC,&b);
        d[i]=(b.tv_sec-a.tv_sec)*1000000000L+(b.tv_nsec-a.tv_nsec); }
    qsort(d,N,sizeof(long),cmp);
    printf("min %7.1f us | med %7.1f us | MAX %8.1f us | max/med %5.2fx\n",
           d[0]/1000.0, d[N/2]/1000.0, d[N-1]/1000.0, (double)d[N-1]/d[N/2]);
    return 0; }
