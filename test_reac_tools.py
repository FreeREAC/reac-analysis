#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Unit tests for the REAC analysis chain. They validate EXPECTED BEHAVIOUR on
# synthetic known-good signals, so a number off the rig can be trusted (or blamed
# on the rig, not the tool). Run: python3 test_reac_tools.py

import numpy as np
import reac_codec as rc

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}  {detail}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def frames_from_blocks(blocks, ftype=b"\x00\x00", start=1000):
    return [rc.encode_frame(blocks[i], start + i) for i in range(len(blocks))]


def test_roundtrip_clean_sine():
    # encode a clean 1 kHz sine on ch15 (idx 14), decode, recover it cleanly
    blocks = rc.make_sine_samples(1000.0, 4000, nch=16, ch_idx=14, amp=0.25)
    frames = frames_from_blocks(blocks)
    ch = rc.decode_frames(frames, nch=16)
    check("roundtrip preserves sample count", ch.shape[0] == 4000 * rc.NS,
          f"{ch.shape[0]} samp")
    ppm, purity, c, f0 = rc.measure_wobble(ch, 1000.0)
    check("roundtrip recovers 1 kHz on the right channel", c == 14 and abs(f0 - 1000) < 2,
          f"ch{c+1} f0={f0:.1f}")
    check("clean sine decodes with HIGH purity (>0.9)", purity > 0.9,
          f"purity={purity:.3f}")


def test_meter_clean_is_zero_wobble():
    blocks = rc.make_sine_samples(1000.0, 6000, ch_idx=14, amp=0.25, wobble_ppm=0.0)
    ch = rc.decode_frames(frames_from_blocks(blocks), 16)
    ppm, purity, c, f0 = rc.measure_wobble(ch, 1000.0)
    check("clean sine measures ~0 ppm wobble (<30)", ppm < 30, f"±{ppm:.0f}ppm")


def test_meter_tracks_known_wobble():
    # peak FM deviation 200 ppm at 1 Hz -> std (what the meter reports) ~= 200/sqrt(2) ~= 141
    blocks = rc.make_sine_samples(1000.0, 12000, ch_idx=14, amp=0.25,
                                  wobble_ppm=200.0, wobble_hz=1.0)
    ch = rc.decode_frames(frames_from_blocks(blocks), 16)
    ppm, purity, c, f0 = rc.measure_wobble(ch, 1000.0)
    check("injected 200 ppm wobble is measured in band (90..200)", 90 < ppm < 200,
          f"±{ppm:.0f}ppm")


def test_meter_orders_wobble():
    def w(ppm):
        b = rc.make_sine_samples(1000.0, 12000, ch_idx=14, amp=0.25,
                                 wobble_ppm=ppm, wobble_hz=1.0)
        return rc.measure_wobble(rc.decode_frames(frames_from_blocks(b), 16), 1000.0)[0]
    w0, w1, w2 = w(0), w(100), w(400)
    check("more wobble -> larger reading (monotone)", w0 < w1 < w2,
          f"{w0:.0f} < {w1:.0f} < {w2:.0f}")


def test_dedup_counter():
    blocks = rc.make_sine_samples(1000.0, 100, ch_idx=14, amp=0.25)
    frames = frames_from_blocks(blocks)
    doubled = []
    for f in frames:
        doubled += [f, f]                 # every frame duplicated (flood+mirror)
    ch = rc.decode_frames(doubled, 16)
    check("duplicate frames are deduped by counter", ch.shape[0] == 100 * rc.NS,
          f"{ch.shape[0]} samp from {len(doubled)} frames")


if __name__ == "__main__":
    for t in (test_roundtrip_clean_sine, test_meter_clean_is_zero_wobble,
              test_meter_tracks_known_wobble, test_meter_orders_wobble,
              test_dedup_counter):
        print(t.__name__)
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
