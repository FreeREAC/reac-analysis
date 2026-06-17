#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Expected-behaviour tests for the REAC re-pacer transform (reac_repacer_model,
# mirroring reac-repacer-clk v3). These encode the SPEC the operator asked to
# validate: a correct re-pacer must NOT alter audio, must keep the slave's counter
# contiguous through loss/conceal, and must PLC by duplicating the last frame under
# the next counter. Run: python3 test_reac_repacer.py

import numpy as np
import reac_codec as rc
import reac_repacer_model as rp

PASS, FAIL = 0, 0
AUDIO = slice(rc.HDR, None)        # bytes 50.. = audio+marker (payload)
TYPE = slice(16, 18)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {name}  {detail}")
    else:
        FAIL += 1; print(f"  FAIL  {name}  {detail}")


def sine_frames(nframes, start=5000, ftype=b"\x00\x00"):
    blocks = rc.make_sine_samples(1000.0, nframes, ch_idx=14, amp=0.25)
    return [rc.encode_frame(blocks[i], start + i, ftype=ftype) for i in range(nframes)]


def test_audio_bit_exact_steady_state():
    ins = sine_frames(500)
    outs = rp.repace(ins, ["R"] * 500)
    same = all(outs[i][AUDIO] == ins[i][AUDIO] for i in range(500))
    check("steady-state: audio payload is bit-exact (re-pacer never touches samples)",
          same, "500/500 frames identical" if same else "MUTATED")


def test_counter_contiguous_steady_state():
    ins = sine_frames(500, start=60000)        # also exercises 16-bit wrap
    cs = rp.output_counters(rp.repace(ins, ["R"] * 500))
    contig = all((cs[i] + 1) & 0xFFFF == cs[i + 1] for i in range(len(cs) - 1))
    check("steady-state: output counter is contiguous +1 (with wrap)", contig,
          f"{cs[0]}..{cs[-1]}")


def test_plc_duplicates_last_under_next_counter():
    ins = sine_frames(5)
    outs = rp.repace(ins, ["R", "R", "R", "P", "R"])     # underrun at slot 3
    cs = rp.output_counters(outs)
    contig = all((cs[i] + 1) & 0xFFFF == cs[i + 1] for i in range(len(cs) - 1))
    dup = outs[3][AUDIO] == outs[2][AUDIO]               # PLC = copy of last frame
    advanced = outs[4][AUDIO] == ins[3][AUDIO]           # real stream resumes (I3)
    check("PLC duplicates the last frame's audio", dup)
    check("PLC keeps counter contiguous (no 65535 gap at slave)", contig, str(cs))
    check("stream resumes with the next real frame after PLC", advanced)


def test_loss_stays_counter_clean():
    # I2 lost on Wi-Fi -> only [I0,I1,I3,I4] reach the ring; output must stay +1
    blocks = rc.make_sine_samples(1000.0, 5, ch_idx=14, amp=0.25)
    allf = [rc.encode_frame(blocks[i], 7000 + i) for i in range(5)]
    arrived = [allf[0], allf[1], allf[3], allf[4]]       # I2 dropped
    cs = rp.output_counters(rp.repace(arrived, ["R"] * 4))
    contig = all((cs[i] + 1) & 0xFFFF == cs[i + 1] for i in range(len(cs) - 1))
    check("loss concealed as a contiguous counter run (no slave glitch)", contig, str(cs))


def test_control_frame_passthrough():
    ins = sine_frames(3, ftype=b"\xcd\xea")              # a cdea channel-map run
    outs = rp.repace(ins, ["R", "R", "R"])
    type_ok = all(o[TYPE] == b"\xcd\xea" for o in outs)
    audio_ok = all(outs[i][AUDIO] == ins[i][AUDIO] for i in range(3))
    check("control frames pass through with type intact", type_ok)
    check("control frames keep their audio payload (only counter rewritten)", audio_ok)


if __name__ == "__main__":
    for t in (test_audio_bit_exact_steady_state, test_counter_contiguous_steady_state,
              test_plc_duplicates_last_under_next_counter, test_loss_stays_counter_clean,
              test_control_frame_passthrough):
        print(t.__name__); t()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
