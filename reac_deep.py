#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_deep.py -- comprehensive REAC capture analysis, no assumptions about tag
# or channel count. For every stream (src MAC + frame length) it reports:
#   * role + channel count (from length, tag-aware)
#   * PER-CHANNEL: RMS level, dominant frequency, spectral purity, pitch-wobble ppm
#   * control cadence per type (cfea/cdea): period in frames + regularity
#   * counter health: step histogram (dups / gaps / clean +1)
#   * header + descriptor + control-frame content (hex)
#
# Audio layout (per reac_decode): after the ethertype at offset e:
#   e+2 counter(LE16), e+4 type(2), e+6 descriptor(32), e+38 audio,
#   audio = sample-major [12 samples][nch][3B LE], then 2B marker.
#
# Usage: reac_deep.py <pcap> [label]

import sys
import struct
import numpy as np
import scipy.signal as sg
from collections import Counter, defaultdict

SR = 96000   # 8000 frames/s * 12 samples/frame


def frames(path):
    d = open(path, "rb").read()
    magic = struct.unpack("<I", d[:4])[0]
    end = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    o = 24
    while o + 16 <= len(d):
        incl, orig = struct.unpack(end + "II", d[o + 8:o + 16])
        o += 16
        p = d[o:o + incl]
        o += incl
        yield p, orig


def reac_off(p):
    for e in (12, 16, 20):
        if len(p) > e + 1 and p[e] == 0x88 and p[e + 1] == 0x19:
            return e
    return -1


def s24(a):
    v = (a[..., 0].astype(np.int32)
         | (a[..., 1].astype(np.int32) << 8)
         | (a[..., 2].astype(np.int32) << 16))
    return np.where(v >= (1 << 23), v - (1 << 24), v)


def chan_stats(x):
    """RMS, dominant freq, purity for one channel's sample vector."""
    x = x.astype(float)
    rms = float(np.sqrt(np.mean(x * x)))
    xz = x - x.mean()
    if np.sqrt(np.mean(xz * xz)) < 1.0:
        return rms, 0.0, 0.0
    w = sg.windows.hann(len(xz))
    spec = np.abs(np.fft.rfft(xz * w))
    freq = np.fft.rfftfreq(len(xz), 1.0 / SR)
    pk = 5 + int(np.argmax(spec[5:]))
    f0 = float(freq[pk])
    purity = float(spec[pk - 2:pk + 3].sum() / spec[5:].sum())
    return rms, f0, purity


def wobble_ppm(x, f0):
    if f0 < 50 or f0 > 20000:
        return 0.0
    sos = sg.butter(4, [max(f0 - 150, 20), min(f0 + 150, SR / 2 - 1)], "bandpass", fs=SR, output="sos")
    an = sg.hilbert(sg.sosfiltfilt(sos, x.astype(float) - x.mean()))
    inst = np.diff(np.unwrap(np.angle(an))) / (2 * np.pi) * SR
    insf = inst[(inst > f0 - 200) & (inst < f0 + 200)]
    if len(insf) < 100:
        return 0.0
    lo, hi = np.percentile(insf, [2, 98])
    core = insf[(insf >= lo) & (insf <= hi)]
    return float(core.std() / f0 * 1e6)


def hx(b):
    return " ".join(f"{x:02x}" for x in b)


def main():
    path = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else "run"
    streams = defaultdict(lambda: {
        "audio": {}, "e": Counter(), "ctrl_idx": defaultdict(list),
        "csteps": Counter(), "last": None, "dst": None, "n": 0,
        "sample_hdr": {}, "first_audio_hdr": None,
    })
    total = reac = 0
    for p, orig in frames(path):
        total += 1
        e = reac_off(p)
        if e < 0:
            continue
        reac += 1
        src = p[6:12].hex()
        st = streams[(src, orig)]
        st["dst"] = p[0:6].hex()
        st["e"][e] += 1
        st["n"] += 1
        cnt = p[e + 2] | (p[e + 3] << 8)
        if st["last"] is not None:
            st["csteps"][(cnt - st["last"]) & 0xFFFF] += 1
        st["last"] = cnt
        typ = bytes(p[e + 4:e + 6])
        idx = len(st["audio"])
        if typ != b"\x00\x00":
            st["ctrl_idx"][typ.hex()].append(idx)
            if typ.hex() not in st["sample_hdr"]:
                st["sample_hdr"][typ.hex()] = hx(p[e:e + 44])
        elif st["first_audio_hdr"] is None:
            st["first_audio_hdr"] = hx(p[e:e + 44])
        if cnt not in st["audio"]:                       # dedup (flood+mirror dups)
            st["audio"][cnt] = p[e + 38:]                # audio region onward

    print(f"==== {label}:  total={total} REAC={reac} streams={len(streams)} ====")
    for (src, orig), st in sorted(streams.items(), key=lambda kv: -kv[1]["n"]):
        e_dom = st["e"].most_common(1)[0][0]
        nch = round((orig - e_dom - 38 - 2) / 3 / 12)
        tag = "tagged" if e_dom > 12 else "untagged"
        role = "BOX-up" if nch <= 24 else "MIXER-down"
        dups = st["csteps"].get(0, 0)
        print(f"\n--- {role}  src={src} -> {st['dst']}  {orig}B  {nch}ch ({tag})  "
              f"frames={st['n']} uniq={len(st['audio'])} dups={dups} ---")
        # counter health
        cs = dict(st["csteps"].most_common(5))
        print(f"  counter steps (1=clean,0=dup): {cs}")
        # cadence per control type
        for t in sorted(st["ctrl_idx"]):
            ci = st["ctrl_idx"][t]
            if len(ci) >= 2:
                g = [b - a for a, b in zip(ci, ci[1:])]
                m = sum(g) / len(g)
                sd = (sum((x - m) ** 2 for x in g) / len(g)) ** 0.5
                reg = "REGULAR" if sd < max(1.0, 0.05 * m) else "irregular"
                print(f"  {t}: {len(ci)}x  every {m:.0f} frames (std {sd:.0f}, {reg})")
            else:
                print(f"  {t}: {len(ci)}x (too few)")
        # per-channel audio
        cnts = sorted(st["audio"])
        if cnts and nch > 0:
            per = nch * 12 * 3
            buf = b"".join(st["audio"][c][:per] for c in cnts if len(st["audio"][c]) >= per)
            a = np.frombuffer(buf, np.uint8)
            nf = len(a) // per
            if nf > 4:
                a = a[:nf * per].reshape(nf, 12, nch, 3)
                ch = s24(a).reshape(-1, nch)
                print(f"  per-channel ({nf} frames, {ch.shape[0]} samp):")
                rows = []
                for c in range(nch):
                    rms, f0, pur = chan_stats(ch[:, c])
                    rows.append((c + 1, rms, f0, pur))
                # show the active (non-silent) channels + a summary of the rest
                act = [r for r in rows if r[1] > 50]
                for cnum, rms, f0, pur in act:
                    wp = wobble_ppm(ch[:, cnum - 1], f0) if pur > 0.05 else 0.0
                    tag2 = f"  WOBBLE=±{wp:.0f}ppm" if wp else ""
                    print(f"    ch{cnum:2d}: rms={rms:8.0f}  f0={f0:7.1f}Hz  purity={pur:.3f}{tag2}")
                silent = [r[0] for r in rows if r[1] <= 50]
                if silent:
                    print(f"    (silent ch: {silent})")
        # headers
        if st["first_audio_hdr"]:
            print(f"  audio  hdr: {st['first_audio_hdr']}")
        for t, h in st["sample_hdr"].items():
            print(f"  {t} hdr: {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
