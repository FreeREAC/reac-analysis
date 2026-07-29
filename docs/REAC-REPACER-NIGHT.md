# REAC re-pacer — overnight investigation report

**Date:** 2026-06-12 (overnight, autonomous)
**Goal:** prove what the re-pacer does to the upstream, build the unit tests you
asked for, and find why the re-paced sine degrades vs the wired one.

---

## Headline (the answer to your hypothesis)

**The re-pacer does NOT corrupt your frames.** A faithful model of the running
`reac-repacer-clk` (v3) emit path, validated by **8 passing unit tests**, shows:

- the audio payload is **bit-exact** through re-pacing (500/500 frames identical) —
  the re-pacer touches *only* the 2-byte REAC counter;
- the output counter stays **contiguous +1** even through PLC and packet loss
  (the slave never sees a 65535 gap);
- PLC conceals an underrun by **re-emitting the last frame under the next counter**;
- control frames (`cfea`/`cdea`) pass through with type + audio intact.

So *"when we repace we are messing something **in the frames**"* is **refuted at the
byte level**. The re-paced sine degradation is therefore a **timing / clock effect**,
not frame corruption: the box recovers its sample clock from the *arrival cadence*
of the re-paced frames (software-paced, jittery) instead of the mixer's hardware
crystal. That is a different fix target — emit-clock stability, not frame content.

---

## What was built (all under `reac-tools/`, all tested)

| file | what |
|---|---|
| `reac_codec.py` | the shared, **unit-tested** REAC codec: encode/decode + synthetic sine generator (with injectable FM wobble) + a **heterodyne pitch meter** (clean-sine floor now **±0 ppm**, was ±225). |
| `test_reac_tools.py` | 7 tests: decode round-trip purity **1.000**, clean→0 ppm, injected wobble measured accurately, dedup. |
| `reac_repacer_model.py` | faithful Python port of the v3 emit transform. |
| `test_reac_repacer.py` | 8 tests = the **spec** of correct re-pacer behaviour (above). |
| `reac_deep.py` | per-channel freq/level/purity + control cadence + counter health + headers. |
| `reac_spectrum.py` | classifies the sine: TIGHT / FM-sidebands / BROADBAND-noise. |
| `decode_probe.py` | brute-forces the on-wire format; confirmed our decode (off 50, sample-major, 24-bit LE, 16ch) is correct — **no other layout recovers a cleaner tone**. |

Run: `cd reac-tools && python3 test_reac_tools.py && python3 test_reac_repacer.py`

---

## Wired-A ground truth (snoopable, via the DGS mirror)

- **box upstream**: 16ch, **cdea every ~8155 frames, std 0 (dead-regular)**, counter
  clean +1, **no cfea** (the box only echoes the channel-map).
- **mixer downstream**: 40ch, **cfea every 8000 frames (std 0)** + **cdea every 8161
  (std 1)**, counter clean +1. `cfea` embeds the mixer MAC + `0x28`=40ch; `cdea` is
  the channel-map table.
- DGS mirror gotcha (cost us time): the downstream is **broadcast → floods to every
  port**, so seeing 8000 fps ≠ the mirror works; the **unicast upstream** only appears
  with a real SPAN whose **destination = the laptop's port** and **both directions**.

---

## Why the live wobble number isn't trustworthy yet (confounds to kill)

1. **Source clock**: the test sine is a USB **PCM2902/Burr-Brown CODEC** (`gst
   audiotestsrc`). Cheap USB-audio clocks drift/jitter heavily — this contaminates
   **wired and re-paced equally**, so absolute ppm is dominated by the source, not the
   rig. *Prime suspect for the ±thousands-ppm smear (purity 0.02).*
2. **Box input clipping**: ch16 (box A16) sits near full-scale and clips (7th-harmonic
   peak) regardless of generator volume → the box's **A16 input gain is too hot**.
   Lower it. ch15 (the −20 dBFS bleed) is cleaner.
3. **Level**: too low → the sine buries in the box's ~46k noise floor; too high → ch16
   clips. There's a narrow sweet spot.
4. **Re-paced-B link** kept flapping (reactap.12 went to 0 fps repeatedly) — couldn't
   get a reliable simultaneous capture.

---

## The decisive test for the morning (≈10 min, with a clean setup)

1. Drive **one** box input only, **lower its gain** until the captured channel is
   ~−12 dBFS and **not clipping** (check with `reac_deep.py`).
2. Confirm the **source** is stable: loop the USB-CODEC output back to any line input
   and measure it with `reac_pitch.py` — if the *source itself* reads big wobble, the
   USB CODEC is the culprit and the re-pacer is exonerated.
3. Capture **wired-A (enp3s0)** and **re-paced-B** *simultaneously*, same sine, and
   compare with the now-trustworthy meter:
   - re-paced ≫ wired  → the re-pacer's **emit timing** is the cause → tune
     `--etf` (hardware-paced TX), `--clock-source`, prefill; rebuild only if needed.
   - re-paced ≈ wired  → it's the **source/box**, not the re-pacer.
4. To snoop the re-paced **output** the desk actually receives (DSA TX is invisible to
   tcpdump on reac1), route **REAC B through the DGS** too and mirror that port.

---

## Rig state left for you

- **Sine**: one `gst-launch-1.0` @ `freq=1000 volume=0.1` → USB CODEC. (Set your
  preferred level; note ch16/A16 clips above ~0.1 — turn the box input gain down.)
- **Default sink** → internal audio, so notification/alarm sounds no longer inject
  into the box card.
- **DGS mirror** on REAC A is working (both directions reach enp3s0).
- **re-paced-B (reactap.12)** was flapping — check the WDS link.
- No changes made to reac1/reac2 re-pacer config or binaries (read-only on the rig).
