#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# reac_repacer_model.py -- a faithful Python model of the reac-repacer-clk (v3)
# frame transform, used to pin down its EXPECTED behaviour in unit tests. It mirrors
# the emit path of reac_repacer_v3.c (lines ~314-331):
#
#   emit_ctr seeded from the first emitted frame's counter
#   per output slot:
#     occ > 0  -> emit the next ring frame, REWRITING bytes 14-15 to emit_ctr
#     occ <= 0 -> PLC: re-emit a copy of the LAST frame under emit_ctr (not a stale
#                 counter -> the slave never sees 65535 lost)
#   emit_ctr += 1 after every emit
#
# Crucially: the AUDIO payload (bytes 18..) is never touched -- only the 2-byte
# counter is rewritten. This model lets the tests assert that property directly.

CNT_LO, CNT_HI = 14, 15


def get_counter(frame):
    return frame[CNT_LO] | (frame[CNT_HI] << 8)


def set_counter(frame, value):
    f = bytearray(frame)
    f[CNT_LO] = value & 0xFF
    f[CNT_HI] = (value >> 8) & 0xFF
    return bytes(f)


def repace(input_frames, emit_plan):
    """input_frames: list of frame bytes (in arrival order).
    emit_plan: per output slot, "R" = emit next real frame, "P" = PLC (conceal).
    Returns the emitted output frames. A drop is modelled by simply not listing an
    input frame's slot as "R" (skip it) -- the counter still advances cleanly."""
    out = []
    emit_ctr = None
    last = None
    in_idx = 0
    for act in emit_plan:
        if act == "R":
            if in_idx >= len(input_frames):
                act = "P"                                  # ran dry -> conceal
            else:
                f = input_frames[in_idx]
                in_idx += 1
                if emit_ctr is None:
                    emit_ctr = get_counter(f)
                f = set_counter(f, emit_ctr)
                out.append(f)
                last = f
                emit_ctr = (emit_ctr + 1) & 0xFFFF
                continue
        if act == "P" and last is not None and emit_ctr is not None:
            p = set_counter(last, emit_ctr)
            out.append(p)
            emit_ctr = (emit_ctr + 1) & 0xFFFF
    return out


def output_counters(frames):
    return [get_counter(f) for f in frames]
