#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_out_health.py -- scan a re-pacer OUTPUT capture (the upstream the mixer
# actually receives) IN EMITTED ORDER and flag every audible defect: SILENCE runs
# (audio zeroed), MUTE frames (the re-pacer's transition-mute blanks bytes 18.. =
# descriptor + audio), PLC duplicates (audio == previous frame), and control-frame
# (cdea/cfea) disruptions. Prints a coarse time line so it can be matched to what
# the ear hears.
#
# Usage: reac_out_health.py <pcap> <src_mac_hex> <frame_len>

import sys
import struct
import numpy as np

HDR = 50


def main():
    path, src, ln = sys.argv[1], sys.argv[2], int(sys.argv[3])
    nch = (ln - HDR - 2) // 36
    aud = nch * 12 * 3
    d = open(path, "rb").read()
    o = 24
    frames = []
    while o + 16 <= len(d):
        incl, orig = struct.unpack("<II", d[o + 8:o + 16])
        o += 16
        p = d[o:o + incl]
        o += incl
        if orig != ln or len(p) < ln or p[6:12].hex() != src:
            continue
        frames.append(p[:ln])
    n = len(frames)
    print(f"src={src} len={ln} {nch}ch  emitted frames={n}  (~{n/8000:.1f}s)")
    if n < 100:
        print("  too few frames"); return 1

    silent = np.zeros(n, bool)
    muted = np.zeros(n, bool)
    plc = np.zeros(n, bool)
    ctrl = np.zeros(n, bool)
    amp = np.zeros(n)
    prev_aud = None
    for i, p in enumerate(frames):
        a = p[HDR:HDR + aud]
        muted[i] = (p[18:HDR] == b"\x00" * (HDR - 18))            # descriptor blanked = transition mute
        # peak |sample| over the frame (cheap loudness)
        v = np.frombuffer(a, np.uint8).astype(np.int32)
        s = v[0::3] | (v[1::3] << 8) | (v[2::3] << 16)
        s = np.where(s >= (1 << 23), s - (1 << 24), s)
        amp[i] = np.abs(s).max()
        silent[i] = amp[i] < 256
        ctrl[i] = not (p[16] == 0 and p[17] == 0)
        if prev_aud is not None and a == prev_aud:
            plc[i] = True
        prev_aud = a

    def runs(mask):
        r, run = [], 0
        for b in mask:
            if b:
                run += 1
            elif run:
                r.append(run); run = 0
        if run:
            r.append(run)
        return r

    sr = runs(silent)
    print(f"  PLC repeats        : {plc.sum():6d}  ({100*plc.mean():.2f}%)")
    print(f"  MUTE frames (blank): {muted.sum():6d}  ({100*muted.mean():.2f}%)  <- transition-mute, blanks descriptor+audio")
    print(f"  SILENT frames      : {silent.sum():6d}  ({100*silent.mean():.2f}%)  runs={sorted(set(sr), reverse=True)[:8]} (frames; /8 = ms)")
    print(f"  control frames     : {ctrl.sum():6d}  (cdea/cfea)")
    # coarse timeline: 40 buckets, mark the worst event per bucket
    B = 40
    step = max(1, n // B)
    line = []
    for b in range(0, n, step):
        sl = slice(b, b + step)
        if muted[sl].any(): line.append("M")
        elif silent[sl].any(): line.append("_")
        elif plc[sl].sum() > step * 0.2: line.append("p")
        elif plc[sl].any(): line.append(".")
        else: line.append("=")
    print(f"  timeline (M=mute _=silence p=PLC-burst .=some-PLC ==clean):\n    {''.join(line)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
