#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Brute-force the true REAC upstream audio layout against the known 1 kHz reference.
# We KNOW the box is fed a clean 1 kHz sine, so the correct (offset, interleave,
# byte-order, channel-count) is the one that recovers a 1 kHz tone with high purity.
import sys
import struct
import numpy as np
import scipy.signal as sg

SR = 96000
path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/wa2.pcap"

from collections import defaultdict
d = open(path, "rb").read()
o = 24
bylen = defaultdict(dict)
while o + 16 <= len(d):
    incl, orig = struct.unpack("<II", d[o + 8:o + 16])
    o += 16
    p = d[o:o + incl]
    o += incl
    if len(p) < 64 or p[12] != 0x88 or p[13] != 0x19:
        continue
    if p[16] != 0 or p[17] != 0:        # audio frames only (type 0000)
        continue
    if len(p) < orig:
        continue
    cnt = p[14] | (p[15] << 8)
    bylen[orig].setdefault(cnt, p[:orig])
# the box upstream is the SMALLEST audio-frame length class with real traffic
cand = [(L, fr) for L, fr in bylen.items() if len(fr) > 100]
if not cand:
    print("no upstream frame class found"); sys.exit(1)
LEN, frames = min(cand, key=lambda kv: kv[0])
cnts = sorted(frames)
print(f"frames={len(cnts)}  frame_len={LEN}")
arr = np.frombuffer(b"".join(frames[c] for c in cnts), np.uint8).reshape(len(cnts), LEN)


def purity1k(x):
    x = x.astype(float) - x.mean()
    if np.sqrt(np.mean(x * x)) < 5:
        return 0.0, 0.0
    w = sg.windows.hann(len(x))
    spec = np.abs(np.fft.rfft(x * w))
    freq = np.fft.rfftfreq(len(x), 1.0 / SR)
    pk = 5 + int(np.argmax(spec[5:]))
    return float(freq[pk]), float(spec[pk - 2:pk + 3].sum() / spec[5:].sum())


def decode(off, nch, layout, order):
    need = nch * 12 * 3
    if off + need > LEN:
        return None
    a = arr[:, off:off + need]
    if layout == "sm":      # sample-major: [12 samp][nch][3]
        a = a.reshape(len(cnts), 12, nch, 3)
    else:                   # channel-major: [nch][12 samp][3]
        a = a.reshape(len(cnts), nch, 12, 3)
    if order == "le":
        v = a[..., 0].astype(np.int32) | (a[..., 1].astype(np.int32) << 8) | (a[..., 2].astype(np.int32) << 16)
    else:
        v = a[..., 2].astype(np.int32) | (a[..., 1].astype(np.int32) << 8) | (a[..., 0].astype(np.int32) << 16)
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    if layout == "sm":
        return v.reshape(-1, nch)
    return v.transpose(0, 2, 1).reshape(-1, nch)


results = []
for nch in (16,):
    for off in range(44, 58):
        for layout in ("sm", "cm"):
            for order in ("le", "be"):
                ch = decode(off, nch, layout, order)
                if ch is None:
                    continue
                for c in range(nch):
                    f0, pur = purity1k(ch[:, c])
                    if 980 < f0 < 1020:
                        results.append((pur, off, layout, order, c + 1, f0))
results.sort(reverse=True)
print("top 1 kHz decodes (purity, offset, layout, order, ch, f0):")
for r in results[:8]:
    print(f"  purity={r[0]:.3f}  off={r[1]} {r[2]} {r[3]}  ch{r[4]}  f0={r[5]:.1f}")
if not results:
    print("  NONE found a 1 kHz tone in any layout -> signal itself may be distorted")
