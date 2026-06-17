#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_codec.py -- the shared, unit-tested REAC upstream codec + a synthetic sine
# generator with controllable clock wobble. Everything that decodes audio off the
# wire (reac_pitch, reac_spectrum, reac_deep, the re-pacer model) should agree with
# THIS so the analysis is provably correct on a known-good signal, independent of
# the rig.
#
# Frame layout (box upstream, matches reac_decode.c / on-rig captures):
#   [0:6]  dst MAC   [6:12] src MAC   [12:14] ethertype 0x8819
#   [14:16] counter LE16   [16:18] type (0000=audio, else control)
#   [18:50] 32-byte descriptor
#   [50:50+nch*12*3] audio: sample-major [12 samples][nch][3B signed LE]
#   [.. : ..+2] 2-byte marker
#
# SR = 8000 frames/s * 12 samples/frame = 96000 Hz.

import struct
import numpy as np

SR = 96000
NS = 12                       # samples per frame
HDR = 50                      # bytes before audio
MARKER = b"\xc2\xea"
ETHERTYPE = b"\x88\x19"


def encode_frame(block, counter, nch=16, ftype=b"\x00\x00",
                 dst=b"\x00\x40\xab\xca\x15\x4d", src=b"\x00\x40\xab\xc4\x80\x3b",
                 desc=None):
    """block: (NS, nch) int32 sample block -> full frame bytes."""
    assert block.shape == (NS, nch)
    if desc is None:
        desc = bytes(32)
    body = bytearray()
    body += dst + src + ETHERTYPE
    body += struct.pack("<H", counter & 0xFFFF)
    body += ftype
    body += desc
    v = block.astype(np.int64) & 0xFFFFFF           # to unsigned 24-bit
    flat = v.reshape(-1)                              # sample-major (NS outer, nch inner)
    audio = np.empty(flat.size * 3, np.uint8)
    audio[0::3] = flat & 0xFF
    audio[1::3] = (flat >> 8) & 0xFF
    audio[2::3] = (flat >> 16) & 0xFF
    body += audio.tobytes()
    body += MARKER
    return bytes(body)


def decode_frames(frames, nch=16):
    """list of frame bytes -> (nsamp, nch) int32, dedup by counter, counter order."""
    seen = {}
    for f in frames:
        if len(f) < HDR + nch * NS * 3 or f[12:14] != ETHERTYPE:
            continue
        if f[16] or f[17]:                           # audio only
            continue
        cnt = f[14] | (f[15] << 8)
        seen.setdefault(cnt, f[HDR:HDR + nch * NS * 3])
    if not seen:
        return np.zeros((0, nch), np.int32)
    buf = np.frombuffer(b"".join(seen[c] for c in sorted(seen)), np.uint8)
    a = buf.reshape(-1, NS, nch, 3)
    v = (a[..., 0].astype(np.int32)
         | (a[..., 1].astype(np.int32) << 8)
         | (a[..., 2].astype(np.int32) << 16))
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    return v.reshape(-1, nch)


def make_sine_samples(freq, nframes, nch=16, ch_idx=14, amp=0.2,
                      wobble_ppm=0.0, wobble_hz=1.0, noise=0.0, seed=0):
    """Synthetic stagebox upstream: a sine on ch_idx, optional FM wobble + noise.
    Returns (nframes, NS, nch) int32 ready for encode_frame."""
    n = nframes * NS
    t = np.arange(n) / SR
    inst = freq * (1.0 + (wobble_ppm / 1e6) * np.sin(2 * np.pi * wobble_hz * t))
    phase = 2 * np.pi * np.cumsum(inst) / SR
    full = (1 << 23) - 1
    sig = amp * full * np.sin(phase)
    blocks = np.zeros((n, nch), np.float64)
    blocks[:, ch_idx] = sig
    if noise > 0:
        rng = np.random.default_rng(seed)
        blocks += rng.normal(0, noise * full, blocks.shape)
    blocks = np.clip(blocks, -full, full).astype(np.int32)
    return blocks.reshape(nframes, NS, nch)


def measure_wobble(channels, target=1000.0):
    """channels: (nsamp, nch) int32. Return (ppm, purity, ch, f0) for the channel
    carrying `target`, via complex heterodyne demodulation (shift the tone to DC,
    lowpass, measure the residual phase slope). Far lower noise floor than a
    bandpass+Hilbert because it never lets AM/filter-ripple leak into the FM."""
    import scipy.signal as sg
    nch = channels.shape[1]
    sel = sg.butter(4, [target - 50, target + 50], "bandpass", fs=SR, output="sos")
    best, bestp = 0, -1.0
    for c in range(nch):
        y = sg.sosfiltfilt(sel, channels[:, c].astype(float))
        p = float(np.mean(y * y))
        if p > bestp:
            bestp, best = p, c
    x = channels[:, best].astype(float)
    x -= x.mean()
    n = len(x)
    # purity from the FFT (clipping-immune view of how tonal the channel is)
    w = sg.windows.hann(n)
    spec = np.abs(np.fft.rfft(x * w))
    freq = np.fft.rfftfreq(n, 1.0 / SR)
    pk = 5 + int(np.argmax(spec[5:]))
    purity = float(spec[pk - 2:pk + 3].sum() / spec[5:].sum())
    # heterodyne the tone to baseband and lowpass off the -2f0 image + other tones
    t = np.arange(n) / SR
    bb = x * np.exp(-2j * np.pi * target * t)
    lp = sg.butter(6, 250, "lowpass", fs=SR, output="sos")
    bb = sg.sosfiltfilt(lp, bb)
    g = max(1, n // 12)                                  # drop filtfilt edge transient
    bb = bb[g:-g]
    phase = np.unwrap(np.angle(bb))
    dev = np.diff(phase) / (2 * np.pi) * SR              # Hz offset from target
    lo, hi = np.percentile(dev, [1, 99])
    core = dev[(dev >= lo) & (dev <= hi)]
    f0 = float(target + core.mean())
    ppm = float(core.std() / target * 1e6)
    return ppm, purity, best, f0
