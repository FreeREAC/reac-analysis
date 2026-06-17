#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_glitch.py -- decode a box OUTPUT channel (A8 / B7) from a downstream capture
# and find what the EAR hears: clicks (sample-to-sample discontinuities = granular),
# silence gaps (= beeps/dropouts), and pitch jumps. Picks the channel carrying the
# sine automatically. This turns "B7 sounds granular and beepy" into counted,
# timestamped events that can be compared against pristine A8.
#
# Usage: reac_glitch.py <pcap> <src_mac_hex> <frame_len> [label]

import sys
import struct
import numpy as np

HDR = 50
SR = 96000


def load(path, src, ln):
    nch = (ln - HDR - 2) // 36
    d = open(path, "rb").read()
    o, seen = 24, {}
    while o + 16 <= len(d):
        incl, orig = struct.unpack("<II", d[o + 8:o + 16])
        o += 16
        p = d[o:o + incl]
        o += incl
        if orig != ln or len(p) < ln or p[6:12].hex() != src or p[16] or p[17]:
            continue
        cnt = p[14] | (p[15] << 8)
        seen.setdefault(cnt, p[HDR:HDR + nch * 12 * 3])
    if not seen:
        return None, nch
    buf = np.frombuffer(b"".join(seen[c] for c in sorted(seen)), np.uint8)
    a = buf.reshape(-1, nch, 3) if False else buf.reshape(-1, 12, nch, 3)
    v = (a[..., 0].astype(np.int32) | (a[..., 1].astype(np.int32) << 8) | (a[..., 2].astype(np.int32) << 16))
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    return v.reshape(-1, nch), nch


def main():
    path, src, ln = sys.argv[1], sys.argv[2], int(sys.argv[3])
    label = sys.argv[4] if len(sys.argv) > 4 else "ch"
    ch, nch = load(path, src, ln)
    if ch is None or ch.shape[0] < 2000:
        print(f"{label}: no audio"); return 1
    # pick the channel with the most 1 kHz energy
    import scipy.signal as sg
    sos = sg.butter(4, [950, 1050], "bandpass", fs=SR, output="sos")
    pw = [float(np.mean(sg.sosfiltfilt(sos, ch[:, c].astype(float)) ** 2)) for c in range(nch)]
    c = int(np.argmax(pw))
    x = ch[:, c].astype(float)
    n = len(x)
    peak = np.percentile(np.abs(x), 99) + 1
    # clicks: sample step far beyond a 1 kHz sine's max slope (~0.066*amp/sample)
    dif = np.abs(np.diff(x))
    clicks = np.where(dif > 0.30 * peak)[0]
    # silences: |x| under 1% peak for a sustained run
    quiet = np.abs(x) < 0.01 * peak
    runs, run, sil_runs = 0, 0, []
    for q in quiet:
        if q: run += 1
        elif run:
            if run > 24: sil_runs.append(run)
            run = 0
    if run > 24: sil_runs.append(run)
    # pitch excursions via heterodyne
    t = np.arange(n) / SR
    bb = sg.sosfiltfilt(sg.butter(6, 250, "lowpass", fs=SR, output="sos"),
                        (x - x.mean()) * np.exp(-2j * np.pi * 1000 * t))
    g = n // 12
    dev = np.diff(np.unwrap(np.angle(bb[g:-g]))) / (2 * np.pi) * SR
    jumps = int(np.sum(np.abs(np.diff(dev)) > 20))     # >20 Hz instantaneous jumps
    dur = n / SR
    print(f"{label}: ch{c+1}/{nch}  {dur:.1f}s  peak={int(peak)}")
    print(f"   CLICKS (granular)   : {len(clicks):5d}  ({len(clicks)/dur:.1f}/s)")
    print(f"   SILENCE gaps >0.25ms: {len(sil_runs):5d}  lens(ms)={[round(r/96,1) for r in sorted(sil_runs, reverse=True)[:8]]}")
    print(f"   pitch jumps >20Hz   : {jumps:5d}  ({jumps/dur:.1f}/s)")
    # 50-char timeline of click density
    B = 50
    step = max(1, n // B)
    tl = "".join("X" if np.any((clicks >= b) & (clicks < b + step)) else "." for b in range(0, n, step))
    print(f"   click timeline: {tl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
