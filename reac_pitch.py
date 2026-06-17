#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_pitch.py -- clipping-immune pitch-wobble meter for a REAC stagebox upstream.
# Bandpasses TIGHTLY around the known fundamental (default 1000 Hz) so clipping
# harmonics can't corrupt the estimate, picks the channel with the most energy in
# that band, and reports the fundamental's frequency-modulation wobble in ppm plus
# amplitude stability. This is the honest clock-quality number to compare wired vs
# re-paced.
#
# Usage: reac_pitch.py <pcap> [label] [target_hz]

import sys
import struct
from collections import defaultdict, Counter
import numpy as np
import scipy.signal as sg

SR = 96000


def load(path):
    d = open(path, "rb").read()
    magic = struct.unpack("<I", d[:4])[0]
    end = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    o = 24
    streams = defaultdict(dict)
    while o + 16 <= len(d):
        incl, orig = struct.unpack(end + "II", d[o + 8:o + 16])
        o += 16
        p = d[o:o + incl]
        o += incl
        if len(p) < 18:
            continue
        e = -1
        for c in (12, 16, 20):
            if len(p) > c + 1 and p[c] == 0x88 and p[c + 1] == 0x19:
                e = c
                break
        if e < 0 or bytes(p[e + 4:e + 6]) != b"\x00\x00":   # REAC audio frames only
            continue
        cnt = p[e + 2] | (p[e + 3] << 8)
        key = (p[6:12].hex(), orig, e)
        if cnt not in streams[key]:
            streams[key][cnt] = p[e + 38:]
    best = None
    for key, fr in streams.items():
        src, orig, e = key
        nch = round((orig - e - 38 - 2) / 3 / 12)
        if nch <= 24 and (best is None or len(fr) > len(streams[best])):
            best = key
    if not best:
        return None, 0
    src, orig, e = best
    nch = round((orig - e - 38 - 2) / 3 / 12)
    fr = streams[best]
    cnts = sorted(fr)
    per = nch * 12 * 3
    buf = b"".join(fr[c][:per] for c in cnts if len(fr[c]) >= per)
    a = np.frombuffer(buf, np.uint8)
    nf = len(a) // per
    a = a[:nf * per].reshape(nf, 12, nch, 3)
    v = (a[..., 0].astype(np.int32)
         | (a[..., 1].astype(np.int32) << 8)
         | (a[..., 2].astype(np.int32) << 16))
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    return v.reshape(-1, nch), nch


def measure(path, label="run", target=1000.0):
    ch, nch = load(path)
    if ch is None or ch.shape[0] < 2000:
        print(f"{label}: no usable upstream ({0 if ch is None else ch.shape[0]} samp)")
        return None
    sos = sg.butter(6, [target - 40, target + 40], "bandpass", fs=SR, output="sos")
    best, bestp = -1, -1.0
    for c in range(nch):
        y = sg.sosfiltfilt(sos, ch[:, c].astype(float))
        p = float(np.sqrt(np.mean(y * y)))
        if p > bestp:
            bestp, best = p, c
    x = ch[:, best].astype(float)
    y = sg.sosfiltfilt(sos, x - x.mean())
    an = sg.hilbert(y)
    inst = np.diff(np.unwrap(np.angle(an))) / (2 * np.pi) * SR
    insf = inst[(inst > target - 60) & (inst < target + 60)]
    lo, hi = np.percentile(insf, [1, 99])
    core = insf[(insf >= lo) & (insf <= hi)]
    ppm = float(core.std() / target * 1e6)
    # slow-breath modulation rate of the pitch
    iw = core - core.mean()
    sp = np.abs(np.fft.rfft(iw * sg.windows.hann(len(iw))))
    fq = np.fft.rfftfreq(len(iw), 1.0 / SR) * (len(core) / len(insf))  # approx
    env = np.abs(an)
    amp_cv = float(env.std() / max(env.mean(), 1e-9))
    dur = len(x) / SR
    print(f"{label}: ch{best+1}/{nch}  {target:.0f}Hz  WOBBLE=±{ppm:.0f}ppm  "
          f"band_rms={bestp:.0f}  amp_cv={amp_cv:.2f}  {dur:.1f}s")
    return ppm


if __name__ == "__main__":
    measure(sys.argv[1],
            sys.argv[2] if len(sys.argv) > 2 else "run",
            float(sys.argv[3]) if len(sys.argv) > 3 else 1000.0)
