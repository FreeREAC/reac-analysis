#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
# reac_ab_defect.py -- objective defect detector: decode a REAC downstream capture
# (correct pair-interleave), auto-find channels carrying the ~1kHz test tone, and
# quantify granularity (clicks, purity, pitch wobble, frame-boundary glitch).
import sys, struct, numpy as np, scipy.signal as sg
SR=96000
def streams(path):
    d=open(path,'rb').read(); o=24; st={}
    while o+16<=len(d):
        incl,orig=struct.unpack('<II',d[o+8:o+16]); o+=16; p=d[o:o+incl]; o+=incl
        if len(p)<18 or p[12]!=0x88 or p[13]!=0x19 or p[16] or p[17]: continue
        st.setdefault((p[6:12].hex(),orig),{})[p[14]|(p[15]<<8)]=p[50:50+((orig-52)//36)*12*3]
    return st
def chan(ab,nch,c):
    p=c//2; blk=ab[:,:,p*6:p*6+6].reshape(-1,6).astype(np.int32)
    v=(blk[:,3]|blk[:,0]<<8|blk[:,1]<<16) if c%2==0 else (blk[:,4]|blk[:,5]<<8|blk[:,2]<<16)
    return np.where(v>=(1<<23),v-(1<<24),v).astype(float)
def analyze(path,label):
    st=streams(path)
    # downstream = the 40ch/largest mixer stream
    cand=sorted(st.items(),key=lambda kv:-(kv[0][1]*len(kv[1])))
    for (src,ln),seen in cand:
        nch=(ln-52)//36; nf=len(seen)
        if nf<3000 or nch<32: continue
        ab=np.frombuffer(b''.join(seen[c] for c in sorted(seen)),np.uint8).reshape(nf,12,nch*3)
        # find tone channels
        best=[]
        for c in range(nch):
            v=chan(ab,nch,c); 
            if np.abs(v).max()<20000: continue
            n=len(v); sp=np.abs(np.fft.rfft((v-v.mean())*sg.windows.hann(n))); fr=np.fft.rfftfreq(n,1/SR); pk=5+int(np.argmax(sp[5:]))
            if not(800<fr[pk]<1200): continue
            pur=sp[pk-2:pk+3].sum()/sp[5:].sum()
            peak=np.percentile(np.abs(v),99)+1
            dif=np.abs(np.diff(v)); clk=int(np.sum(dif>0.30*peak))
            # frame-boundary glitch: mean|jump| AT 12-sample boundaries vs interior
            bnd=dif[11::12]; interior=np.delete(dif,np.arange(11,len(dif),12))
            
            fbr=(bnd.mean()+1)/(interior.mean()+1)
            t=np.arange(n)/SR; bb=sg.sosfiltfilt(sg.butter(6,200,'lowpass',fs=SR,output='sos'),(v-v.mean())*np.exp(-2j*np.pi*1000*t))
            g=n//12; wob=(np.diff(np.unwrap(np.angle(bb[g:-g])))/(2*np.pi)*SR).std()
            best.append((c,20*np.log10(np.abs(v).max()/8388607+1e-9),fr[pk],pur,clk/(n/SR),fbr,wob))
        print(f'{label}: src={src} {nch}ch frames={nf}')
        for c,db,f0,pur,clks,fbr,wob in best:
            print(f'   ch{c:2d}: {db:+.0f}dBFS f0={f0:.0f}Hz  purity={pur:.3f}  clicks={clks:6.0f}/s  frame-bnd-glitch={fbr:4.1f}x  wobble={wob:.1f}Hz')
        return best
    print(f'{label}: no 32+ch downstream found'); return []
for p,l in [(sys.argv[1],'A8 (wired ref)'),(sys.argv[2],'B7 (re-paced)')]:
    analyze(p,l)
