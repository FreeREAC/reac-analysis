# reac-labtools

The **signal-analysis bench** for **Roland REAC** (audio-over-Ethernet,
EtherType `0x8819`) captures. Where [`reac-tools`](https://github.com/FreeREAC/reac-tools)
answers *"did the network deliver the frames?"*, reac-labtools answers
*"what does the audio inside them actually sound like, and is the recovered
clock any good?"* — heterodyne pitch and clock-wobble meters, spectrum
classification, per-channel decode health, glitch and A/B defect detection.

These are **instruments, not a library**: each one is a flat script that takes
a capture on `argv` and prints a measurement. They are meant to be read, forked
and adapted per experiment. There is no package, no stable API, no `pip install`.

## Relationship to reac-tools — read this first

The two repositories split on a hard constraint, not on taste:

|  | [`reac-tools`](https://github.com/FreeREAC/reac-tools) | **reac-labtools** (this repo) |
|---|---|---|
| Shape | importable `reac.*` package + CLI | flat single-purpose scripts |
| Dependencies | **none — Python standard library only** | **numpy + scipy** |
| Runs on | anything, including an OpenWrt router | a workstation with a scientific stack |
| Question | frame transport: loss, reorder, dup, cross-mix, jitter | signal quality: pitch, wobble, spectrum, clicks, PLC |
| Stability | versioned, unit-tested against a committed fixture | experiment-shaped, changes with the investigation |

`reac-tools` is deployable *because* it has no dependencies — it gets scp'd onto
a busybox router mid-session. Merging these tools into it would end that, so they
live here instead. **Neither repo is the whole toolkit**; if you landed here
looking for loss/jitter/cross-mix analysis or the Wireshark dissector, it is in
`reac-tools`.

Nothing here imports `reac.*`, so the two are independent — install neither to
use the other.

> Not to be confused with [`FreeREAC/reac-lab`](https://github.com/FreeREAC/reac-lab),
> which holds prose: design specs, rig journals and runbooks. `reac-lab` is
> writing; `reac-labtools` is code.

## Requirements

```sh
pip install -r requirements.txt   # numpy >= 1.24, scipy >= 1.10
```

Python 3.9+. `reac_frame_anatomy.py`, `reac_io_diff.py` and
`reac_repacer_model.py` happen to be standard-library-only, but they ship here
because they are the same kind of thing as their neighbours — and
`reac_repacer_model.py` is the fixture the numpy-based re-pacer tests drive.

## The instruments

Every tool reads a **classic pcap** and prints a report; none of them write to
the capture or to the rig.

| Tool | Measures |
|---|---|
| `reac_codec.py` | the shared, unit-tested upstream codec: decode + synthetic sine generator with injectable clock wobble + heterodyne pitch meter. **Everything else agrees with this or is wrong.** |
| `reac_pitch.py` | clipping-immune pitch-wobble meter — tight bandpass around the known fundamental, reports FM wobble in ppm |
| `reac_clock_measure.py` | the regression metric for recovered-clock wobble; emits a `CSV,` line for `reac-measure.sh` to log |
| `reac_spectrum.py` | classifies the recovered sine: TIGHT (clean clock) / SIDEBANDS (FM wobble) / BROADBAND (noise or level too low) |
| `reac_deep.py` | per-stream, per-channel sweep: RMS, dominant frequency, purity, wobble, control cadence, counter health |
| `reac_glitch.py` | what the ear hears on a box output: clicks, silence gaps, pitch jumps |
| `reac_out_health.py` | scans a re-pacer output in emitted order: silence runs, mute frames, PLC duplicates |
| `reac_ab_defect.py` | objective A/B defect score — auto-finds the tone channels and quantifies granularity |
| `reac_io_diff.py` | aligns a re-pacer's input against its output **by audio content** (the counter is rewritten) and reports exactly what changed |
| `reac_frame_anatomy.py` | frame characterisation with no assumption about tagging: finds `0x8819` at untagged/1-tag/QinQ offsets, decodes header and classifies |
| `decode_probe.py` | brute-forces the on-wire layout against a known 1 kHz reference — the check that the decode is right at all |
| `measure_b7.py` | one-line metric for a single downstream tone channel |
| `reac_repacer_model.py` | faithful Python model of the `reac-repacer` v3 emit transform (stdlib; the spec the tests assert against) |

## Rig scripts

Included deliberately: the measurements above are only comparable if the rig is
in a known state, and these are what put it there. They are the experiment's
control, so they belong beside the meters rather than in the transport repos.

| Script | Does |
|---|---|
| `reac-measure.sh` | the regression harness — captures the stagebox upstream over ssh, runs `reac_clock_measure.py`, appends a row to `measure-log.csv`. Run before *and* after every rig change. |
| `reac-hwbridge.sh` | puts an OpenWrt router into a pure-L2 hardware REAC bridge (no gretap, no re-pacer) so the box recovers the mixer's real cadence |
| `reac-untagged-test.sh` | flat untagged L2 bridge, single stream — tests whether the 802.1Q trunk tag, not a missing re-pacer, was breaking the link |

`reac-hwbridge.sh` and `reac-untagged-test.sh` run **on the router** and change
its bridge configuration; both are reversible via the rig's own restore scripts.
`reac-measure.sh` is read-only on the rig (tcpdump only).

`reac-measure.sh` takes the host as a **required argument** and authenticates
with your ssh agent or key — it carries no address and no password.

```sh
./reac-measure.sh baseline rig-router-alias           # default iface reactap.12
./reac-measure.sh etf-on   rig-router-alias lan2
REAC_SSH="ssh -J jump rig" ./reac-measure.sh via-jump ignored
```

## Usage

```sh
python3 reac_pitch.py capture.pcap wired-A            # ppm wobble, one number
python3 reac_pitch.py capture.pcap wired-A 1000       # explicit fundamental
python3 reac_spectrum.py capture.pcap                 # TIGHT / SIDEBANDS / BROADBAND
python3 reac_deep.py capture.pcap                     # full per-channel sweep
python3 reac_glitch.py capture.pcap                   # clicks, gaps, pitch jumps
python3 reac_io_diff.py in.pcap out.pcap              # what the re-pacer changed
python3 decode_probe.py capture.pcap                  # is the decode itself right?
```

## Tests

```sh
make test
# or
python3 test_reac_tools.py      # codec: round-trip purity, 0 ppm floor, wobble accuracy, dedup
python3 test_reac_repacer.py    # re-pacer model: payload bit-exactness, counter contiguity, PLC
```

These are plain scripts with their own `PASS`/`FAIL` counters, not a pytest
suite — they predate the split and are kept as they were. `test_reac_repacer.py`
is the executable **spec** of correct re-pacer behaviour: it is what refuted the
"re-pacing corrupts the frames" hypothesis (see
[`docs/REAC-REPACER-NIGHT.md`](docs/REAC-REPACER-NIGHT.md)).

## Provenance

These files were developed in a private lab repository alongside what is now
`reac-tools`, and were moved here with their original commit history — four
commits, original authorship and dates. One change was made on the way: the
measurement harness had a hard-coded rig address and a plaintext router
password, which are removed from every commit in this repository's history.

## Related

- [`FreeREAC/reac-tools`](https://github.com/FreeREAC/reac-tools) — the
  dependency-free transport analyzer and Wireshark dissector
- [`FreeREAC/reac-repacer`](https://github.com/FreeREAC/reac-repacer) — the L2
  de-jitter relay these tools were built to measure
- [`FreeREAC/reac-protocol`](https://github.com/FreeREAC/reac-protocol) — the
  protocol description
- [`FreeREAC/reac-lab`](https://github.com/FreeREAC/reac-lab) — design specs,
  journals, runbooks

### REAC protocol references

- https://github.com/per-gron/reacdriver — the original REAC reverse-engineering
- https://github.com/norihiro/obs-h8819-source — OBS source plugin; framing
- https://github.com/norihiro/reaccapture — pcap-to-WAV decoder; sample justification

## Acknowledgements

reac-labtools is original work, but the REAC wire protocol it decodes was made
intelligible by prior reverse-engineering. The `0x8819` framing, the 16-bit
little-endian sequence counter and the 24-bit slot layout were documented by the
projects above; reac-labtools re-implements those documented *facts* and copies
no upstream code. See [NOTICE](NOTICE).

## License

GPL-3.0-or-later. Copyright (C) 2026 Pau Aliagas. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).
