#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_clock_measure.py -- objective regression metric for the recovered-clock
# wobble of a Roland REAC stagebox upstream, decoded straight off the wire.
#
# Decodes the test sine carried in the 628 B REAC upstream frame and reports:
#   * pitch wobble in ppm (1st..99th percentile of the instantaneous frequency)
#   * wobble modulation rate (Hz) -- how fast the pitch breathes
#   * dropout (beep) count over the window
#   * spectral purity (fundamental / total power; 1.0 = clean sine)
#
# A pure hardware-forwarded clock reads ~0 ppm / purity ~1.0; the software
# re-pacer reconstruction reads ~±385 ppm / purity ~0.25. Run before and after
# any rig change and compare the ppm -- that number is the regression test.
#
# Usage: reac_clock_measure.py <pcap> [label]
#   <pcap>  tcpdump capture of the 628 B upstream, full frame (snaplen >= 628)
# Emits one human line and one "CSV,..." line for appending to a log.

import sys
import struct
import numpy as np
import scipy.signal as sg

UP_LEN = 628          # REAC upstream frame length (bytes)
HDR = 50              # 14 eth + 2 LE counter + 2 type + 32 unknown
NCH = 16              # upstream channel count (576 B audio / 12 / 3)
NS = 12               # samples per frame
SR = 96000            # 8000 pps * 12 samples
TONE_MAX_HZ = 20000   # ignore ultrasonic/aliased channels when picking the sine


def load_audio(path):
    """Parse the pcap, dedup by REAC counter, return (nframes, NS, NCH, 3) uint8."""
    data = open(path, "rb").read()
    magic = struct.unpack("<I", data[:4])[0]
    end = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    off, seen = 24, {}
    while off + 16 <= len(data):
        _, _, incl, orig = struct.unpack(end + "IIII", data[off:off + 16])
        off += 16
        pkt = data[off:off + incl]
        off += incl
        if orig != UP_LEN or len(pkt) < UP_LEN:
            continue
        if pkt[12] != 0x88 or pkt[13] != 0x19:
            continue
        cnt = pkt[14] | (pkt[15] << 8)
        if cnt not in seen:                 # drop bridge duplicates; keep first
            seen[cnt] = pkt[HDR:HDR + NS * NCH * 3]
    cnts = sorted(seen)                      # counter order == time order (<65536)
    if not cnts:
        return None
    buf = np.frombuffer(b"".join(seen[c] for c in cnts), dtype=np.uint8)
    return buf.reshape(len(cnts), NS, NCH, 3)


def s24(a):
    """De-interleaved 24-bit LE -> signed int32. a shape (..., 3)."""
    v = (a[..., 0].astype(np.int32)
         | (a[..., 1].astype(np.int32) << 8)
         | (a[..., 2].astype(np.int32) << 16))
    return np.where(v >= (1 << 23), v - (1 << 24), v)


def dominant(x):
    x = x.astype(float) - x.mean()
    if np.sqrt(np.mean(x * x)) < 10:
        return -1.0
    spec = np.abs(np.fft.rfft(x * sg.windows.hann(len(x))))
    freq = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(freq[5 + int(np.argmax(spec[5:]))])   # skip DC/sub-bass bins


def measure(path, label):
    frames = load_audio(path)
    if frames is None:
        return f"{label}: NO upstream frames in {path}", f"CSV,{label},0,,,,,"
    chan = s24(frames).reshape(-1, NCH)                  # (nsamp, NCH), sample-major
    rms = np.sqrt(np.mean(chan.astype(float) ** 2, axis=0))
    f0s = [dominant(chan[:, c]) for c in range(NCH)]
    cand = [(c, f0s[c], rms[c]) for c in range(NCH) if 50 < f0s[c] < TONE_MAX_HZ]
    if not cand:
        return f"{label}: no tonal channel found", f"CSV,{label},{len(chan)//NS},,,,,"
    ci, f0, _ = max(cand, key=lambda t: t[2])           # loudest in-band tone = the sine
    x = chan[:, ci].astype(float)
    x -= x.mean()
    spec = np.abs(np.fft.rfft(x * sg.windows.hann(len(x))))
    pk = 5 + int(np.argmax(spec[5:]))
    purity = float(spec[pk - 3:pk + 4].sum() / spec[5:].sum())
    sos = sg.butter(4, [max(f0 - 150, 20), f0 + 150], "bandpass", fs=SR, output="sos")
    an = sg.hilbert(sg.sosfiltfilt(sos, x))
    inst = np.diff(np.unwrap(np.angle(an))) / (2 * np.pi) * SR
    insf = inst[(inst > f0 - 200) & (inst < f0 + 200)]
    lo, hi = np.percentile(insf, [2, 98])           # trim dropout-glitch outliers
    core = insf[(insf >= lo) & (insf <= hi)]
    ppm = core.std() / f0 * 1e6                      # robust 1-sigma pitch wobble
    iw = insf - insf.mean()
    iwspec = np.abs(np.fft.rfft(iw * sg.windows.hann(len(iw))))
    iwfreq = np.fft.rfftfreq(len(iw), 1.0 / SR)
    band = (iwfreq > 0.3) & (iwfreq < 5.0)          # audible slow-breath band
    wobble = float(iwfreq[band][int(np.argmax(iwspec[band]))]) if band.any() else 0.0
    env = np.abs(an)
    beeps = int(np.sum(np.diff((env < 0.3 * np.median(env)).astype(int)) == 1))
    dur = len(x) / SR
    human = (f"{label}: ch{ci + 1} f0={f0:.1f}Hz purity={purity:.3f} "
             f"wobble=±{ppm:.0f}ppm @{wobble:.1f}Hz beeps={beeps}/{dur:.1f}s")
    csv = f"CSV,{label},{len(chan)//NS},{f0:.1f},{purity:.3f},{ppm:.0f},{wobble:.1f},{beeps}"
    return human, csv


def main():
    if len(sys.argv) < 2:
        print("usage: reac_clock_measure.py <pcap> [label]", file=sys.stderr)
        return 2
    human, csv = measure(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "run")
    print(human)
    print(csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
