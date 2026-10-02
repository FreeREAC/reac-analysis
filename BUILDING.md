# Building and testing reac-analysis

There is nothing to compile: the instruments are flat Python scripts run from
the checkout. "Building" is installing the two dependencies; the tests are plain
scripts driven by `make`.

## Requirements

```sh
pip install -r requirements.txt   # numpy >= 1.24, scipy >= 1.10
```

Python 3.9+. `reac_frame_anatomy.py`, `reac_io_diff.py` and
`reac_repacer_model.py` happen to be standard-library-only, but they ship here
because they are the same kind of thing as their neighbours — and
`reac_repacer_model.py` is the fixture the numpy-based re-pacer tests drive.

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
"re-pacing corrupts the frames" hypothesis. The audio payload is bit-exact through
re-pacing; only the 2-byte REAC counter is rewritten (investigation report
REAC-REPACER-NIGHT).
