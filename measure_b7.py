#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# measure_b7.py <pcap> <tag> -- decode the B downstream tone channel, print one metric line.
import sys, struct, numpy as np, scipy.signal as sg
SR=96000; path=sys.argv[1]; tag=sys.argv[2] if len(sys.argv)>2 else ''
d=open(path,'rb').read(); o=24; st={}
while o+16<=len(d):
    incl,orig=struct.unpack('<II',d[o+8:o+16]); o+=16; p=d[o:o+incl]; o+=incl
    if len(p)<18 or p[12]!=0x88 or p[13]!=0x19 or p[16] or p[17] or orig<1400: continue
    st.setdefault(p[6:12].hex(),{})[p[14]|(p[15]<<8)]=p[50:50+((orig-52)//36)*12*3]
if not st: print(f'{tag}: NO-DOWNSTREAM'); sys.exit()
src=max(st,key=lambda s:len(st[s])); seen=st[src]; nch=40; nf=len(seen)
gaps=sum(((c2-c1)&0xffff)-1 for c1,c2 in zip(sorted(seen)[:-1],sorted(seen)[1:]))
ab=np.frombuffer(b''.join(seen[c] for c in sorted(seen)),np.uint8).reshape(nf,12,nch*3)
def chan(c):
    pp=c//2; blk=ab[:,:,pp*6:pp*6+6].reshape(-1,6).astype(np.int32)
    v=(blk[:,3]|blk[:,0]<<8|blk[:,1]<<16) if c%2==0 else (blk[:,4]|blk[:,5]<<8|blk[:,2]<<16)
    return np.where(v>=(1<<23),v-(1<<24),v).astype(float)
best=None
for c in range(nch):
    v=chan(c)
    if np.abs(v).max()<10000: continue
    n=len(v); sp=np.abs(np.fft.rfft((v-v.mean())*sg.windows.hann(n))); fr=np.fft.rfftfreq(n,1/SR); pk=5+int(np.argmax(sp[5:]))
    if not(800<fr[pk]<1200): continue
    pur=float(sp[pk-2:pk+3].sum()/sp[5:].sum())
    peak=np.percentile(np.abs(v),99)+1; clk=int(np.sum(np.abs(np.diff(v))>0.30*peak))/(n/SR)
    t=np.arange(n)/SR; bb=sg.sosfiltfilt(sg.butter(6,200,'lowpass',fs=SR,output='sos'),(v-v.mean())*np.exp(-2j*np.pi*1000*t))
    g=n//12; wob=float((np.diff(np.unwrap(np.angle(bb[g:-g])))/(2*np.pi)*SR).std())
    if best is None or pur>best[2]: best=(c,20*np.log10(np.abs(v).max()/8388607+1e-9),pur,clk,wob)
if best: print(f'{tag}: ch{best[0]} {best[1]:+.0f}dBFS  purity={best[2]:.3f}  clicks={best[3]:5.0f}/s  wobble={best[4]:4.1f}Hz  (cap gaps={gaps})')
else: print(f'{tag}: no-tone frames={nf}')
