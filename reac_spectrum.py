#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_spectrum.py -- classify the recovered 1 kHz sine of a REAC box upstream:
# is its energy TIGHT (clean clock), in SIDEBANDS near 1 kHz (FM clock wobble), or
# spread BROADBAND (noise / level too low)? Reports energy fractions within
# +/-5/20/100 Hz of the peak plus a wobble estimate, so wired vs re-paced can be
# compared apples-to-apples regardless of the common source-clock contribution.
#
# Usage: reac_spectrum.py <pcap> [label] [target_hz]

import sys
import struct
from collections import defaultdict
import numpy as np
import scipy.signal as sg

SR = 96000


def load_upstream(path):
    d = open(path, "rb").read()
    magic = struct.unpack("<I", d[:4])[0]
    end = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    o = 24
    bylen = defaultdict(dict)
    while o + 16 <= len(d):
        incl, orig = struct.unpack(end + "II", d[o + 8:o + 16])
        o += 16
        p = d[o:o + incl]
        o += incl
        if len(p) < 64 or p[12] != 0x88 or p[13] != 0x19 or p[16] or p[17]:
            continue
        if len(p) < orig:
            continue
        bylen[orig].setdefault(p[14] | (p[15] << 8), p[:orig])
    cand = [(L, fr) for L, fr in bylen.items() if len(fr) > 200]
    if not cand:
        return None, 0
    L, fr = min(cand, key=lambda kv: kv[0])
    nch = round((L - 50 - 2) / 3 / 12)
    cnts = sorted(fr)
    per = nch * 12 * 3
    buf = b"".join(fr[c][50:50 + per] for c in cnts if len(fr[c]) >= 50 + per)
    a = np.frombuffer(buf, np.uint8)
    nf = len(a) // per
    a = a[:nf * per].reshape(nf, 12, nch, 3)
    v = (a[..., 0].astype(np.int32) | (a[..., 1].astype(np.int32) << 8) | (a[..., 2].astype(np.int32) << 16))
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    return v.reshape(-1, nch), nch


def analyze(path, label="run", target=1000.0):
    ch, nch = load_upstream(path)
    if ch is None or ch.shape[0] < 4000:
        print(f"{label}: no usable upstream")
        return
    # pick channel with most energy in target +-50 Hz
    sos = sg.butter(4, [target - 50, target + 50], "bandpass", fs=SR, output="sos")
    best, bestp = 0, -1.0
    for c in range(nch):
        y = sg.sosfiltfilt(sos, ch[:, c].astype(float))
        p = float(np.mean(y * y))
        if p > bestp:
            bestp, best = p, c
    x = ch[:, best].astype(float)
    x -= x.mean()
    w = sg.windows.hann(len(x))
    spec = np.abs(np.fft.rfft(x * w)) ** 2
    freq = np.fft.rfftfreq(len(x), 1.0 / SR)
    pk = int(np.argmax(spec[(freq > target - 50) & (freq < target + 50)])
             + np.searchsorted(freq, target - 50))
    f0 = freq[pk]
    tot = spec[5:].sum()

    def frac(hz):
        m = (freq > f0 - hz) & (freq < f0 + hz)
        return float(spec[m].sum() / tot)

    e5, e20, e100 = frac(5), frac(20), frac(100)
    # wobble: instantaneous freq via wide bandpass
    sos2 = sg.butter(4, [target - 120, target + 120], "bandpass", fs=SR, output="sos")
    an = sg.hilbert(sg.sosfiltfilt(sos2, x))
    inst = np.diff(np.unwrap(np.angle(an))) / (2 * np.pi) * SR
    insf = inst[(inst > f0 - 150) & (inst < f0 + 150)]
    lo, hi = np.percentile(insf, [2, 98])
    core = insf[(insf >= lo) & (insf <= hi)]
    ppm = float(core.std() / f0 * 1e6)
    rms = float(np.sqrt(np.mean(ch[:, best].astype(float) ** 2)))
    verdict = ("TIGHT/clean" if e5 > 0.7 else
               "FM-WOBBLE (sidebands)" if e100 > 0.6 else
               "BROADBAND noise")
    print(f"{label}: ch{best+1}/{nch} f0={f0:.1f}Hz rms={rms:.0f} "
          f"E±5Hz={e5:.2f} E±20={e20:.2f} E±100={e100:.2f} wobble=±{ppm:.0f}ppm -> {verdict}")
    return dict(ch=best + 1, f0=f0, e5=e5, e20=e20, e100=e100, ppm=ppm, rms=rms)


if __name__ == "__main__":
    analyze(sys.argv[1],
            sys.argv[2] if len(sys.argv) > 2 else "run",
            float(sys.argv[3]) if len(sys.argv) > 3 else 1000.0)
